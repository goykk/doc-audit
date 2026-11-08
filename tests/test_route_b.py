import json
from pathlib import Path

import pymupdf
import pytest

from app.evaluation.metrics import FieldSpec
from app.extractors import route_b
from app.extractors.llm_client import LLMResponse


def _image(tmp_path: Path) -> Path:
    path = tmp_path / "receipt.png"
    doc = pymupdf.open()
    page = doc.new_page(width=200, height=300)
    page.insert_text((10, 20), "TOTAL 55.12")
    page.get_pixmap(dpi=200).save(path)
    doc.close()
    return path


def test_extract_route_b_sends_image_and_maps_fields(tmp_path, monkeypatch):
    captured = {}

    def fake_chat(messages, model=None, **kwargs):
        captured["messages"] = messages
        captured["model"] = model
        return LLMResponse(
            content=json.dumps(
                {
                    "fields": {"amount_total": {"value": "55.12", "confidence": 0.92}},
                    "line_items": [
                        {
                            "description": {"value": "Latte", "confidence": 0.9},
                            "quantity": {"value": "2", "confidence": 0.9},
                            "unit_price": {"value": None, "confidence": 0.0},
                            "amount": {"value": "55.12", "confidence": 0.9},
                        }
                    ],
                }
            ),
            prompt_tokens=500,
            completion_tokens=100,
            latency_ms=2000,
            cost_cny=0.0024,
        )

    monkeypatch.setattr(route_b, "chat", fake_chat)
    spec = FieldSpec(fields=["amount_total"], line_items=["description", "quantity", "unit_price", "amount"])
    result = route_b.extract_route_b(_image(tmp_path), "d1", spec)

    content = captured["messages"][1]["content"]
    assert content[0]["type"] == "text" and "line_items" in content[0]["text"]
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert result.pipeline == "vlm_e2e"
    assert result.fields["amount_total"].value == "55.12"
    assert result.fields["amount_total"].bbox is None
    assert result.line_items[0].description.value == "Latte"
    assert result.line_items[0].unit_price.confidence == 0.0
    assert result.prompt_tokens == 500 and result.cost_cny == 0.0024


def test_route_b_rejects_missing_image(tmp_path):
    with pytest.raises(FileNotFoundError):
        route_b.extract_route_b(tmp_path / "missing.png", "d1", FieldSpec(fields=[], line_items=[]))
