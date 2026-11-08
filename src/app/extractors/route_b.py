"""Route B: Qwen-VL end-to-end extraction directly from the receipt image."""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any

import pymupdf

from app.config import settings
from app.evaluation.metrics import FieldSpec
from app.extraction_result import ExtractionResult, FieldValue, LineItem
from app.extractors.llm_client import chat
from app.extractors.route_a import (
    FIELD_HINTS,
    LLMFieldPayload,
    LLMPayload,
    parse_payload,
)

SYSTEM_PROMPT = """You are a document field extraction engine. Read the supplied receipt image.
Return one JSON object only; never wrap it in markdown.
Copy values exactly as printed. Never compute or derive values.
Use null when a field is not visible. Keep line items in the printed visual order.
"""


def _image_data_url(image_path: Path, max_side: int) -> str:
    pixmap = pymupdf.Pixmap(str(image_path))
    width, height = pixmap.width, pixmap.height
    raw = image_path.read_bytes()
    if max(width, height) <= max_side:
        mime = "image/png" if raw[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
        return f"data:{mime};base64,{base64.b64encode(raw).decode()}"

    doc = pymupdf.open(image_path)
    page = doc[0]
    # account for PyMuPDF's 96dpi default page scaling, then cap the long side
    zoom = (width / page.rect.width) * (max_side / max(width, height))
    render = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    data = render.tobytes("jpeg")
    doc.close()
    return "data:image/jpeg;base64," + base64.b64encode(data).decode()


def _prompt(spec: FieldSpec, doc_type: str) -> str:
    header_fields = "\n".join(
        f"- {name}: {FIELD_HINTS.get(name, name)}" for name in spec.fields
    ) or "- (none)"
    item_fields = "\n".join(
        f"- {name}: {FIELD_HINTS.get(name, name)}" for name in spec.line_items
    ) or "- (none)"
    example_fields = {
        name: {"value": "<verbatim value or null>", "quote": None, "confidence": 0.9}
        for name in spec.fields
    }
    example_item = {
        name: {"value": "<verbatim value or null>", "quote": None, "confidence": 0.9}
        for name in spec.line_items
    }
    example = {"fields": example_fields, "line_items": [example_item] if spec.line_items else []}
    return f"""Document type: {doc_type}

Header fields:
{header_fields}

Line-item fields:
{item_fields}

Read the image and return exactly this JSON shape:
{json.dumps(example, ensure_ascii=False)}

Rules:
- line_items must follow the printed visual row order, one element per purchased row.
- Skip subtotal, tax, discount, total, payment, change and loyalty rows.
- If a receipt has N product names and N line amounts, pair them in order.
- amount is the printed line total; unit_price only when printed as a unit price.
"""


def _field_value(payload: LLMFieldPayload) -> FieldValue:
    value: Any = payload.value
    if isinstance(value, str):
        value = value.strip()
        if not value or value.casefold() in {"null", "none", "n/a", "-"}:
            value = None
    confidence = max(0.0, min(1.0, float(payload.confidence)))
    return FieldValue(
        value=value,
        quote=payload.quote,
        bbox=None,
        confidence=round(confidence, 4) if value is not None else 0.0,
        source="vlm",
    )


def _call_and_parse(
    messages: list[dict], model: str, debug_dir: Path | None
) -> tuple[LLMPayload, int, int, float]:
    response = chat(
        messages,
        model=model,
        max_tokens=3072,
        input_price_per_1k=settings.vlm_input_price_per_1k,
        output_price_per_1k=settings.vlm_output_price_per_1k,
    )
    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / "vlm.raw.txt").write_text(response.content, encoding="utf-8")
    prompt_tokens = response.prompt_tokens
    completion_tokens = response.completion_tokens
    cost = response.cost_cny
    try:
        return parse_payload(response.content), prompt_tokens, completion_tokens, cost
    except (ValueError, json.JSONDecodeError) as first_error:
        repair = messages + [
            {"role": "assistant", "content": response.content},
            {
                "role": "user",
                "content": f"Your reply was not valid JSON ({first_error}). Return only the JSON object.",
            },
        ]
        retry = chat(
            repair,
            model=model,
            max_tokens=3072,
            input_price_per_1k=settings.vlm_input_price_per_1k,
            output_price_per_1k=settings.vlm_output_price_per_1k,
        )
        prompt_tokens += retry.prompt_tokens
        completion_tokens += retry.completion_tokens
        cost += retry.cost_cny
        try:
            return parse_payload(retry.content), prompt_tokens, completion_tokens, cost
        except (ValueError, json.JSONDecodeError) as second_error:
            raise ValueError(f"VLM returned invalid JSON twice: {second_error}") from second_error


def extract_route_b(
    image_path: Path,
    doc_id: str,
    spec: FieldSpec,
    doc_type: str = "receipt",
    model: str | None = None,
    debug_dir: Path | None = None,
) -> ExtractionResult:
    if not image_path.is_file():
        raise FileNotFoundError(image_path)
    model = model or settings.vlm_model
    data_url = _image_data_url(image_path, settings.vlm_max_image_side)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": _prompt(spec, doc_type)},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]

    started = time.perf_counter()
    payload, prompt_tokens, completion_tokens, cost = _call_and_parse(messages, model, debug_dir)

    fields = {
        name: _field_value(payload.fields.get(name, LLMFieldPayload(value=None, confidence=0.0)))
        for name in spec.fields
    }
    line_items = [
        LineItem(
            **{
                name: _field_value(getattr(item, name))
                for name in ("description", "quantity", "unit_price", "amount")
            }
        )
        for item in payload.line_items
    ]
    return ExtractionResult(
        doc_id=doc_id,
        doc_type=doc_type,
        pipeline="vlm_e2e",
        model=model,
        fields=fields,
        line_items=line_items,
        latency_ms=round((time.perf_counter() - started) * 1000),
        parse_latency_ms=0,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_cny=round(cost, 6),
    )
