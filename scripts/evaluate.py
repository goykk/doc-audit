"""Evaluate predictions against annotated ground truth.

Example:
  PYTHONPATH=src python scripts/evaluate.py \
    --pred-dir data/predictions/route_a \
    --dataset cord --out reports/eval_cord_route_a
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from app.evaluation.metrics import render_markdown  # noqa: E402
from app.evaluation.runner import run_evaluation  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pred-dir", type=Path, required=True)
    parser.add_argument("--gt-manifest", type=Path, default=ROOT / "data/ground_truth/manifest.jsonl")
    parser.add_argument("--fields", type=Path, default=ROOT / "data/ground_truth/dataset_fields.yaml")
    parser.add_argument("--dataset", default=None, help="cord/sroie/synthetic; inferred when unique")
    parser.add_argument("--out", type=Path, default=ROOT / "reports/eval")
    args = parser.parse_args()

    report = run_evaluation(
        manifest_path=args.gt_manifest,
        pred_dir=args.pred_dir.resolve(),
        fields_path=args.fields,
        project_root=ROOT,
        dataset=args.dataset,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    json_path = args.out.with_suffix(".json")
    md_path = args.out.with_suffix(".md")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    summary = report["summary"]
    metrics = summary["field_metrics"]
    print(
        f"docs={summary['docs']} F1={metrics['f1']:.4f} "
        f"P={metrics['precision']:.4f} R={metrics['recall']:.4f} "
        f"hallucination={metrics['hallucination_rate']:.4f} miss={metrics['miss_rate']:.4f} "
        f"line_item_acc={summary['line_item_doc_accuracy']:.4f}"
    )
    print(f"wrote {json_path} and {md_path}")


if __name__ == "__main__":
    main()
