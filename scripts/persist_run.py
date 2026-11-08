"""Persist validation results and review items into MySQL."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from app.db.repository import persist_predictions  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pred-dir", type=Path, required=True)
    parser.add_argument("--dataset", default="cord")
    args = parser.parse_args()

    summary = persist_predictions(
        pred_dir=args.pred_dir.resolve(),
        dataset=args.dataset,
        manifest_path=ROOT / "data/ground_truth/manifest.jsonl",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
