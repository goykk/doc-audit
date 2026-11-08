import json
from pathlib import Path

import pytest

from app.evaluation.metrics import FieldSpec
from app.extractors import route_a
from app.extractors.llm_client import LLMResponse
from app.extractors.route_a import locate_quote, parse_payload


def test_parse_payload_accepts_fenced_json_and_ignores_extra_keys():
    content = '```json\n{"fields":{"subtotal":{"value":"10","quote":"10","confidence":0.9}},"line_items":[],"extra":1}\n```'
    payload = parse_payload(content)
    assert payload.fields["subtotal"].value == "10"


def test_locate_quote_prefers_smaller_block_and_handles_table_html():
    blocks = [
        {"page": 1, "type": "table", "text": "<table><tr><td>Total</td><td>55.12</td></tr></table>", "bbox": [0, 0, 100, 50]},
        {"page": 1, "type": "text", "text": "Total: 55.12", "bbox": [10, 60, 40, 70]},
    ]
    box = locate_quote("55.12", blocks)
    assert box is not None and box.page == 1
    assert (box.x0, box.y0, box.x1, box.y1) == (10, 60, 40, 70)
    assert locate_quote("not-on-page", blocks) is None


def _doc(tmp_path: Path) -> Path:
    d = tmp_path / "doc"
    d.mkdir()
    (d / "manifest.json").write_text(
        json.dumps({"doc_id": "d1", "elapsed_ms": 100}), encoding="utf-8"
    )
    (d / "blocks.json").write_text(
        json.dumps(
            [{"page": 1, "type": "text", "text": "TOTAL 55.12", "bbox": [1, 2, 30, 40], "table_html": None}]
        ),
        encoding="utf-8",
    )
    (d / "content.md").write_text("TOTAL 55.12", encoding="utf-8")
    return d


def test_extract_route_a_maps_values_and_evidence(tmp_path, monkeypatch):
    calls = []

    def fake_chat(messages, model=None, **kwargs):
        calls.append(messages)
        return LLMResponse(
            content=json.dumps(
                {
                    "fields": {"amount_total": {"value": "55.12", "quote": "55.12", "confidence": 0.91}},
                    "line_items": [],
                }
            ),
            prompt_tokens=100,
            completion_tokens=20,
            latency_ms=10,
            cost_cny=0.001,
        )

    monkeypatch.setattr(route_a, "chat", fake_chat)
    spec = FieldSpec(fields=["amount_total", "tax_total"], line_items=[])
    result = route_a.extract_route_a(_doc(tmp_path), spec, parse_latency_ms=100)

    assert result.fields["amount_total"].value == "55.12"
    assert result.fields["amount_total"].bbox is not None
    assert result.fields["tax_total"].value is None
    assert result.fields["tax_total"].confidence == 0.0
    assert result.prompt_tokens == 100 and result.cost_cny == 0.001
    assert result.latency_ms >= 100
    assert len(calls) == 1


def test_extract_route_a_repairs_invalid_json_once(tmp_path, monkeypatch):
    responses = iter(
        [
            LLMResponse("not json", 10, 2, 1, 0.0),
            LLMResponse('{"fields":{},"line_items":[]}', 20, 3, 1, 0.0),
        ]
    )
    calls = []

    def fake_chat(messages, model=None, **kwargs):
        calls.append(messages)
        return next(responses)

    monkeypatch.setattr(route_a, "chat", fake_chat)
    result = route_a.extract_route_a(
        _doc(tmp_path), FieldSpec(fields=["amount_total"], line_items=[])
    )
    assert len(calls) == 2
    assert result.prompt_tokens == 30 and result.completion_tokens == 5
    assert result.fields["amount_total"].value is None


def test_line_items_are_extracted_in_a_separate_call(tmp_path, monkeypatch):
    calls = []

    def fake_chat(messages, model=None, **kwargs):
        user = messages[-1]["content"]
        calls.append(user)
        if "Line-item fields" in user:
            content = json.dumps(
                {
                    "line_items": [
                        {
                            "description": {"value": "Latte", "quote": "TOTAL", "confidence": 0.9},
                            "quantity": {"value": "2", "quote": None, "confidence": 0.8},
                            "unit_price": {"value": None, "confidence": 0.0},
                            "amount": {"value": "36", "quote": None, "confidence": 0.8},
                        }
                    ]
                }
            )
        else:
            content = json.dumps(
                {"fields": {"amount_total": {"value": "55.12", "quote": "55.12", "confidence": 0.9}}}
            )
        return LLMResponse(content, 10, 5, 1, 0.0)

    monkeypatch.setattr(route_a, "chat", fake_chat)
    spec = FieldSpec(fields=["amount_total"], line_items=["description", "quantity", "unit_price", "amount"])
    result = route_a.extract_route_a(_doc(tmp_path), spec)

    assert len(calls) == 2
    assert len(result.line_items) == 1
    assert result.line_items[0].description.value == "Latte"
    assert result.line_items[0].description.bbox is not None
    assert result.line_items[0].unit_price.value is None
    assert result.prompt_tokens == 20 and result.completion_tokens == 10


def test_extract_route_a_fails_after_two_invalid_json_replies(tmp_path, monkeypatch):
    monkeypatch.setattr(
        route_a,
        "chat",
        lambda messages, model=None, **kwargs: LLMResponse("still bad", 1, 1, 1, 0.0),
    )
    with pytest.raises(ValueError, match="invalid JSON twice"):
        route_a.extract_route_a(_doc(tmp_path), FieldSpec(fields=["amount_total"], line_items=[]))
