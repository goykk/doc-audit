"""Run validation / audit over route A or route B predictions."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from app.validation.runner import render_markdown, run_validation  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pred-dir", type=Path, required=True)
    parser.add_argument("--dataset", default="cord")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    report = run_validation(
        pred_dir=args.pred_dir.resolve(),
        dataset=args.dataset,
        project_root=ROOT,
        manifest_path=ROOT / "data/ground_truth/manifest.jsonl",
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    json_path = args.out.with_suffix(".json")
    md_path = args.out.with_suffix(".md")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    counts = report["status_counts"]
    print(
        f"docs={report['docs']} accepted={counts['accepted']} "
        f"review={counts['review']} rejected={counts['rejected']} issues={report['issue_count']}"
    )
    print(f"wrote {json_path} and {md_path}")


if __name__ == "__main__":
    main()
