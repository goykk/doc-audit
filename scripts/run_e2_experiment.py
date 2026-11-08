"""E2: free text vs JSON object vs strict JSON Schema output constraint.

Same images, same prompt, same model; only response_format changes.
Each mode writes predictions to data/predictions/e2_{mode} and stats to reports/.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from app.config import settings  # noqa: E402
from app.evaluation.metrics import FieldSpec  # noqa: E402
from app.evaluation.runner import load_manifest  # noqa: E402
from app.extraction_result import ExtractionResult, LineItem  # noqa: E402
from app.extractors import route_b  # noqa: E402
from app.extractors.llm_client import chat  # noqa: E402
from app.extractors.route_a import LLMFieldPayload, parse_payload  # noqa: E402

MODES = ("free", "object", "schema")
FIELD_SCHEMA = {
    "type": "object",
    "properties": {
        "value": {"anyOf": [{"type": "string"}, {"type": "number"}, {"type": "null"}]},
        "quote": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "confidence": {"type": "number"},
    },
    "required": ["value", "quote", "confidence"],
    "additionalProperties": False,
}


def _response_format(mode: str, spec: FieldSpec) -> dict | None:
    if mode == "free":
        return None
    if mode == "object":
        return {"type": "json_object"}
    item_props = {
        name: FIELD_SCHEMA for name in ("description", "quantity", "unit_price", "amount")
    }
    schema = {
        "type": "object",
        "properties": {
            "fields": {
                "type": "object",
                "properties": {name: FIELD_SCHEMA for name in spec.fields},
                "required": list(spec.fields),
                "additionalProperties": False,
            },
            "line_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": item_props,
                    "required": list(item_props),
                    "additionalProperties": False,
                },
            },
        },
        "required": ["fields", "line_items"],
        "additionalProperties": False,
    }
    return {
        "type": "json_schema",
        "json_schema": {"name": "receipt_extraction", "strict": True, "schema": schema},
    }


def _build_messages(image_path: Path, spec: FieldSpec, doc_type: str) -> list[dict]:
    data_url = route_b._image_data_url(image_path, settings.vlm_max_image_side)
    return [
        {"role": "system", "content": route_b.SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": route_b._prompt(spec, doc_type)},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]


def _to_result(payload, doc_id: str, doc_type: str, spec: FieldSpec, latency_ms: int, tokens, cost, model: str):
    fields = {
        name: route_b._field_value(payload.fields.get(name, LLMFieldPayload(value=None, confidence=0.0)))
        for name in spec.fields
    }
    items = [
        LineItem(
            **{
                name: route_b._field_value(getattr(item, name))
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
        line_items=items,
        latency_ms=latency_ms,
        prompt_tokens=tokens[0],
        completion_tokens=tokens[1],
        cost_cny=round(cost, 6),
    )


def run_mode(mode: str, dataset: str, limit: int) -> dict:
    rows = [r for r in load_manifest(ROOT / "data/ground_truth/manifest.jsonl") if r["source_dataset"] == dataset]
    if limit:
        rows = rows[:limit]
    import yaml

    raw = yaml.safe_load((ROOT / "data/ground_truth/dataset_fields.yaml").read_text(encoding="utf-8"))[dataset]
    spec = FieldSpec(fields=list(raw["fields"]), line_items=list(raw["line_items"]))

    pred_dir = ROOT / "data" / "predictions" / f"e2_{mode}"
    pred_dir.mkdir(parents=True, exist_ok=True)
    log_path = pred_dir / "run_log.jsonl"
    stats = {
        "mode": mode,
        "docs": 0,
        "raw_json_valid": 0,
        "payload_valid": 0,
        "repairs": 0,
        "failed": 0,
        "latency_ms": [],
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cost_cny": 0.0,
    }

    with log_path.open("w", encoding="utf-8") as log:
        for row in rows:
            doc_id = row["doc_id"]
            rf = _response_format(mode, spec)
            messages = _build_messages(ROOT / row["filename"], spec, row.get("doc_type", "receipt"))
            started = time.perf_counter()
            response = chat(
                messages,
                model=settings.vlm_model,
                max_tokens=3072,
                input_price_per_1k=settings.vlm_input_price_per_1k,
                output_price_per_1k=settings.vlm_output_price_per_1k,
                response_format=rf,
                json_mode=(mode != "free"),
            )
            prompt_tokens = response.prompt_tokens
            completion_tokens = response.completion_tokens
            cost = response.cost_cny
            strict_ok = True
            try:
                json.loads(response.content)
            except json.JSONDecodeError:
                strict_ok = False
            stats["raw_json_valid"] += int(strict_ok)

            repaired = False
            try:
                payload = parse_payload(response.content)
            except Exception:
                repaired = True
                repair = chat(
                    messages
                    + [
                        {"role": "assistant", "content": response.content},
                        {"role": "user", "content": "Your reply was not valid JSON. Return only the JSON object."},
                    ],
                    model=settings.vlm_model,
                    max_tokens=3072,
                    input_price_per_1k=settings.vlm_input_price_per_1k,
                    output_price_per_1k=settings.vlm_output_price_per_1k,
                    response_format=rf,
                    json_mode=(mode != "free"),
                )
                prompt_tokens += repair.prompt_tokens
                completion_tokens += repair.completion_tokens
                cost += repair.cost_cny
                try:
                    payload = parse_payload(repair.content)
                except Exception:
                    stats["failed"] += 1
                    empty = ExtractionResult(
                        doc_id=doc_id, pipeline="vlm_e2e", model=settings.vlm_model,
                        fields={}, line_items=[], latency_ms=round((time.perf_counter() - started) * 1000)
                    )
                    (pred_dir / f"{doc_id}.json").write_text(empty.model_dump_json(indent=2), encoding="utf-8")
                    log.write(json.dumps({"doc_id": doc_id, "status": "format_error"}, ensure_ascii=False) + "\n")
                    continue
            stats["payload_valid"] += 1
            stats["repairs"] += int(repaired)
            latency = round((time.perf_counter() - started) * 1000)
            result = _to_result(
                payload,
                doc_id,
                row.get("doc_type", "receipt"),
                spec,
                latency,
                (prompt_tokens, completion_tokens),
                cost,
                settings.vlm_model,
            )
            (pred_dir / f"{doc_id}.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
            stats["docs"] += 1
            stats["latency_ms"].append(latency)
            stats["prompt_tokens"] += prompt_tokens
            stats["completion_tokens"] += completion_tokens
            stats["cost_cny"] += cost
            log.write(
                json.dumps(
                    {
                        "doc_id": doc_id,
                        "status": "ok",
                        "strict_json": strict_ok,
                        "repaired": repaired,
                        "latency_ms": latency,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    stats["cost_cny"] = round(stats["cost_cny"], 6)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--dataset", default="cord")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    stats = run_mode(args.mode, args.dataset, args.limit)
    out = ROOT / "reports" / f"e2_{args.mode}_stats.json"
    out.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
