"""Route A: MinerU layout/text/table -> LLM structured extraction.

The LLM is constrained by the dataset field whitelist, and every value carries a
verbatim quote that is mapped back to a MinerU block bbox for evidence display.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.config import settings
from app.evaluation.metrics import FieldSpec
from app.extraction_result import BoundingBox, ExtractionResult, FieldValue, LineItem
from app.extractors.llm_client import chat

FIELD_HINTS = {
    "invoice_number": "invoice number printed on the document",
    "invoice_date": "issue date, as printed (YYYY-MM-DD preferred, keep original if unclear)",
    "seller_name": "seller / merchant name",
    "seller_tax_id": "seller tax identification number",
    "buyer_name": "buyer name",
    "buyer_tax_id": "buyer tax identification number",
    "subtotal": "subtotal before tax and discount",
    "tax_total": "tax amount",
    "discount_total": "discount amount, preserve the printed sign (e.g. -60.000)",
    "amount_total": "grand total actually paid",
    "total_with_tax": "total including tax",
    "amount_in_words": "amount written in Chinese capital characters",
    "merchant_name": "merchant / store name",
    "address": "store address",
    "receipt_date": "transaction date, as printed",
    "description": "item name only, excluding leading item codes/barcodes",
    "quantity": "quantity printed for this item (keep forms like 1X), never derived from price",
    "unit_price": "per-unit price only when marked with @, x or '/unit'; otherwise null",
    "amount": "printed line total for this item, never computed",
}

SYSTEM_PROMPT = """You are a document field extraction engine for receipts and invoices.
Return one JSON object only. Never wrap it in markdown.

Hard rules:
1. Copy values exactly as printed. Do not convert currencies, dates, or number formats.
2. If a field is not present on the document, use {"value": null, "quote": null, "confidence": 0.0}.
3. "quote" must be a short verbatim substring from the supplied document text that supports the value.
4. "confidence" is a number in [0,1] reflecting your own certainty.
5. line_items must follow the printed row order. Do not invent rows or merge rows.
6. Never compute, sum, or derive a value. Copy only numbers actually printed.
7. amount_total is the line labelled TOTAL / AMOUNT DUE, not subtotal, tax, change, or cash tendered.
8. Keep the printed separator style exactly (28.000 must not become 28,000).
"""


class LLMFieldPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    value: Any = None
    quote: str | None = None
    confidence: float = 0.8


class LLMItemPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    description: LLMFieldPayload = LLMFieldPayload()
    quantity: LLMFieldPayload = LLMFieldPayload()
    unit_price: LLMFieldPayload = LLMFieldPayload()
    amount: LLMFieldPayload = LLMFieldPayload()


class LLMPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    fields: dict[str, LLMFieldPayload] = {}
    line_items: list[LLMItemPayload] = []


def _header_prompt(document_text: str, spec: FieldSpec, doc_type: str) -> str:
    header_fields = "\n".join(
        f"- {name}: {FIELD_HINTS.get(name, name)}" for name in spec.fields
    ) or "- (none)"
    example_fields = {
        name: {
            "value": "<verbatim value or null>",
            "quote": "<verbatim quote or null>",
            "confidence": 0.9,
        }
        for name in spec.fields
    }
    return f"""Document type: {doc_type}

Extract ONLY these header fields:
{header_fields}

Return exactly:
{json.dumps({"fields": example_fields}, ensure_ascii=False)}

Document text (layout parser output; tables may be HTML):
<<<DOCUMENT
{document_text[:16000]}
DOCUMENT
"""


def _items_prompt(document_text: str, spec: FieldSpec, doc_type: str) -> str:
    example_item = {
        name: {
            "value": "<verbatim value or null>",
            "quote": "<verbatim quote or null>",
            "confidence": 0.9,
        }
        for name in spec.line_items
    }
    return f"""Document type: {doc_type}

Extract every purchased product/service row as one line item. Skip subtotal, tax, discount,
total, payment, change and loyalty lines.
The layout parser often flattens a table: item names may be listed together, then their amounts.
If you see N names and N amounts, pair them in printed order.
Example printed row "COFFEE 2 18.00": description COFFEE, quantity 2, amount 18.00, unit_price null.
Never compute or invent a value; copy what is printed.

Line-item fields are the keys in this JSON shape (return exactly this shape):
{json.dumps({"line_items": [example_item]}, ensure_ascii=False)}

Document text (layout parser output; tables may be HTML):
<<<DOCUMENT
{document_text[:16000]}
DOCUMENT
"""


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object found in LLM response")
    return text[start : end + 1]


def parse_payload(content: str) -> LLMPayload:
    return LLMPayload.model_validate(json.loads(_strip_fences(content)))


def _plain(text: str) -> str:
    return re.sub(r"[\s,，¥￥$€£]+", "", text).casefold()


def _html_text(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text)


def locate_quote(quote: str | None, blocks: list[dict]) -> BoundingBox | None:
    if not quote or not quote.strip():
        return None
    needle = _plain(quote)
    if not needle:
        return None
    matches: list[tuple[float, dict]] = []
    for block in blocks:
        text = block.get("text") or ""
        if block.get("type") == "table" or "<table" in text:
            text = _html_text(text)
        if needle in _plain(text):
            x0, y0, x1, y1 = block["bbox"]
            matches.append(((x1 - x0) * (y1 - y0), block))
    if not matches:
        return None
    block = min(matches, key=lambda pair: pair[0])[1]
    x0, y0, x1, y1 = block["bbox"]
    return BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1, page=int(block["page"]))


def _field_value(payload: LLMFieldPayload, blocks: list[dict]) -> FieldValue:
    value = payload.value
    if isinstance(value, str):
        value = value.strip()
        if not value or value.casefold() in {"null", "none", "n/a", "-"}:
            value = None
    confidence = max(0.0, min(1.0, float(payload.confidence)))
    return FieldValue(
        value=value,
        quote=payload.quote,
        bbox=locate_quote(payload.quote, blocks),
        confidence=round(confidence, 4) if value is not None else 0.0,
        source="llm",
    )


def _load_document(doc_dir: Path, blocks: list[dict]) -> str:
    markdown = doc_dir / "content.md"
    if markdown.is_file():
        return markdown.read_text(encoding="utf-8")
    return "\n".join(_html_text(block.get("text") or "") for block in blocks)


def _call_json(
    messages: list[dict],
    model: str | None,
    label: str,
    debug_dir: Path | None = None,
) -> tuple[LLMPayload, int, int, float]:
    response = chat(messages, model=model)
    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / f"{label}.raw.txt").write_text(response.content, encoding="utf-8")
    prompt_tokens = response.prompt_tokens
    completion_tokens = response.completion_tokens
    cost = response.cost_cny
    try:
        return parse_payload(response.content), prompt_tokens, completion_tokens, cost
    except (ValueError, json.JSONDecodeError) as first_error:
        repair_messages = messages + [
            {"role": "assistant", "content": response.content},
            {
                "role": "user",
                "content": f"Your reply was not valid JSON ({first_error}). Return only the JSON object.",
            },
        ]
        retry = chat(repair_messages, model=model)
        if debug_dir is not None:
            (debug_dir / f"{label}.repair.txt").write_text(retry.content, encoding="utf-8")
        prompt_tokens += retry.prompt_tokens
        completion_tokens += retry.completion_tokens
        cost += retry.cost_cny
        try:
            payload = parse_payload(retry.content)
        except (ValueError, json.JSONDecodeError) as second_error:
            raise ValueError(
                f"{label} extraction returned invalid JSON twice: {second_error}"
            ) from second_error
        return payload, prompt_tokens, completion_tokens, cost


def extract_route_a(
    doc_dir: Path,
    spec: FieldSpec,
    doc_type: str = "receipt",
    model: str | None = None,
    parse_latency_ms: int = 0,
    debug_dir: Path | None = None,
) -> ExtractionResult:
    doc_dir = doc_dir.resolve()
    manifest_path = doc_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"missing parse manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    blocks = json.loads((doc_dir / "blocks.json").read_text(encoding="utf-8"))
    document_text = _load_document(doc_dir, blocks)
    if not document_text.strip():
        raise ValueError(f"empty document text for {doc_dir}")

    started = time.perf_counter()
    header_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _header_prompt(document_text, spec, doc_type)},
    ]
    header_payload, prompt_tokens, completion_tokens, cost = _call_json(
        header_messages, model, "header", debug_dir
    )

    line_items: list[LineItem] = []
    if spec.line_items:
        item_messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _items_prompt(document_text, spec, doc_type)},
        ]
        item_payload, item_prompt, item_completion, item_cost = _call_json(
            item_messages, model, "line_items", debug_dir
        )
        prompt_tokens += item_prompt
        completion_tokens += item_completion
        cost += item_cost
        for item in item_payload.line_items:
            line_items.append(
                LineItem(
                    **{
                        name: _field_value(getattr(item, name), blocks)
                        for name in ("description", "quantity", "unit_price", "amount")
                    }
                )
            )

    fields = {
        name: _field_value(
            header_payload.fields.get(
                name, LLMFieldPayload(value=None, confidence=0.0)
            ),
            blocks,
        )
        for name in spec.fields
    }

    total_latency = parse_latency_ms + round((time.perf_counter() - started) * 1000)
    return ExtractionResult(
        doc_id=manifest["doc_id"],
        doc_type=doc_type,
        pipeline="layout_llm",
        model=model or settings.llm_model,
        fields=fields,
        line_items=line_items,
        latency_ms=total_latency,
        parse_latency_ms=parse_latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_cny=round(cost, 6),
    )
