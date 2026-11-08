"""Run route B (Qwen-VL end-to-end) over the annotated manifest."""
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
from app.extractors.route_b import extract_route_b  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="cord")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--pred-dir", type=Path, default=ROOT / "data/predictions/route_b")
    parser.add_argument("--force", action="store_true")
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
            out_path = args.pred_dir / f"{doc_id}.json"
            if out_path.is_file() and not args.force:
                print(f"[{index}/{len(rows)}] {doc_id} skipped", flush=True)
                continue
            started = time.perf_counter()
            record = {"doc_id": doc_id, "dataset": args.dataset, "status": "ok"}
            try:
                result = extract_route_b(
                    ROOT / row["filename"],
                    doc_id,
                    spec,
                    doc_type=row.get("doc_type", "receipt"),
                    model=args.model,
                    debug_dir=args.pred_dir / "debug" / doc_id,
                )
                out_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
                record.update(
                    {
                        "vlm_ms": result.latency_ms,
                        "prompt_tokens": result.prompt_tokens,
                        "completion_tokens": result.completion_tokens,
                        "cost_cny": result.cost_cny,
                        "fields": len(result.fields),
                        "line_items": len(result.line_items),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - batch must report per-doc failures
                failures += 1
                record.update({"status": "error", "error": f"{type(exc).__name__}: {exc}"})
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
                f"[{index}/{len(rows)}] {doc_id} ok vlm={record['vlm_ms']}ms "
                f"items={record['line_items']} tokens={record['prompt_tokens']}+{record['completion_tokens']}",
                flush=True,
            )
            log.write(json.dumps(record, ensure_ascii=False) + "\n")
            log.flush()

    print(f"done: {len(rows) - failures} ok / {len(rows)} total, failures={failures}", flush=True)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
