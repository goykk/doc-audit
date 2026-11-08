"""Export the shared extraction contract as JSON Schema.

Used by route A (structured output constraint) and route B (prompt contract),
and by the E2 ablation (constrained vs. unconstrained decoding).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from app.extraction_result import ExtractionResult  # noqa: E402


def main() -> None:
    schema = ExtractionResult.model_json_schema()
    out = ROOT / "infra" / "extraction_result.schema.json"
    out.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
