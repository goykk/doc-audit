"""CLI: render and parse one PDF with MinerU.

Example:
  PYTHONPATH=src python scripts/parse_pdf.py data/raw/sample_receipt.pdf sample_receipt --device cuda
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from app.pipelines.mineru_runner import parse_pdf  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("doc_id")
    parser.add_argument("--device", default="cuda", choices=["cuda", "cuda:0", "cpu"])
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--source", default="modelscope", choices=["modelscope", "huggingface", "local"])
    parser.add_argument("--lang", default="ch")
    args = parser.parse_args()

    manifest = parse_pdf(
        args.pdf,
        args.doc_id,
        device=args.device,
        dpi=args.dpi,
        source=args.source,
        lang=args.lang,
    )
    print(json.dumps(asdict(manifest), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
