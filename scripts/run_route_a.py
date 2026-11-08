"""Run route A (MinerU + LLM) over the annotated manifest.

Example:
  PYTHONPATH=src python scripts/run_route_a.py --dataset cord --limit 1 --device cpu --force-parse
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from app.evaluation.runner import load_field_specs, load_manifest  # noqa: E402
from app.extractors.route_a import extract_route_a  # noqa: E402
from app.pipelines.image_pdf import image_to_pdf  # noqa: E402
from app.pipelines.mineru_runner import parse_pdf  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="cord")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda", "cuda:0"])
    parser.add_argument("--pred-dir", type=Path, default=ROOT / "data/predictions/route_a")
    parser.add_argument("--force-parse", action="store_true")
    parser.add_argument("--force-extract", action="store_true")
    parser.add_argument("--stop-on-error", action="store_true")
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    specs = load_field_specs(ROOT / "data/ground_truth/dataset_fields.yaml")
    if args.dataset not in specs:
        raise SystemExit(f"no field spec for dataset {args.dataset}")
    spec = specs[args.dataset]

    rows = [r for r in load_manifest(ROOT / "data/ground_truth/manifest.jsonl") if r["source_dataset"] == args.dataset]
    if args.limit:
        rows = rows[: args.limit]
    if not rows:
        raise SystemExit("no manifest rows matched")

    args.pred_dir.mkdir(parents=True, exist_ok=True)
    log_path = args.pred_dir / "run_log.jsonl"
    failures = 0
    with log_path.open("a", encoding="utf-8") as log:
        for index, row in enumerate(rows, 1):
            doc_id = row["doc_id"]
            started = time.perf_counter()
            record = {"doc_id": doc_id, "dataset": args.dataset, "status": "ok"}
            try:
                image_path = ROOT / row["filename"]
                pdf_path = image_to_pdf(image_path, ROOT / "data/processed/_pdfs" / f"{doc_id}.pdf")
                parse_manifest_path = ROOT / "data/processed" / doc_id / "manifest.json"
                if args.force_parse or not parse_manifest_path.is_file():
                    manifest = parse_pdf(pdf_path, doc_id, device=args.device)
                    parse_latency_ms = manifest.elapsed_ms
                else:
                    manifest = json.loads(parse_manifest_path.read_text(encoding="utf-8"))
                    parse_latency_ms = int(manifest.get("elapsed_ms") or 0)

                out_path = args.pred_dir / f"{doc_id}.json"
                if out_path.is_file() and not args.force_extract:
                    record["status"] = "skipped"
                else:
                    result = extract_route_a(
                        ROOT / "data/processed" / doc_id,
                        spec,
                        doc_type=row.get("doc_type", "receipt"),
                        model=args.model,
                        parse_latency_ms=parse_latency_ms,
                        debug_dir=args.pred_dir / "debug" / doc_id,
                    )
                    out_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
                    record.update(
                        {
                            "parse_ms": parse_latency_ms,
                            "llm_ms": result.latency_ms - parse_latency_ms,
                            "total_ms": result.latency_ms,
                            "prompt_tokens": result.prompt_tokens,
                            "completion_tokens": result.completion_tokens,
                            "cost_cny": result.cost_cny,
                            "fields": len(result.fields),
                            "line_items": len(result.line_items),
                        }
                    )
            except Exception as exc:  # noqa: BLE001 - batch must report per-doc failures
                failures += 1
                record.update(
                    {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
                )
                (args.pred_dir / f"{doc_id}.error.log").write_text(
                    traceback.format_exc(), encoding="utf-8"
                )
                print(f"[{index}/{len(rows)}] {doc_id} ERROR {exc}", flush=True)
                log.write(json.dumps(record, ensure_ascii=False) + "\n")
                log.flush()
                if args.stop_on_error:
                    raise
                continue
            record["wall_ms"] = round((time.perf_counter() - started) * 1000)
            print(
                f"[{index}/{len(rows)}] {doc_id} {record['status']} "
                f"parse={record.get('parse_ms')}ms llm={record.get('llm_ms')}ms "
                f"items={record.get('line_items')}",
                flush=True,
            )
            log.write(json.dumps(record, ensure_ascii=False) + "\n")
            log.flush()

    print(f"done: {len(rows) - failures} ok / {len(rows)} total, failures={failures}", flush=True)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
