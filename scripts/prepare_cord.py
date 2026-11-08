"""Convert CORD-v2 parquet rows into project images + ground-truth files.

CORD is CC-BY-4.0 and contains no real customer identity data. Only the fields
declared in data/ground_truth/dataset_fields.yaml for `cord` are annotated.
CORD has no merchant/date annotation, so those fields are intentionally absent.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from app.extraction_result import ExtractionResult, FieldValue, LineItem  # noqa: E402


def _scalar(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _menus(gt: dict) -> list[dict]:
    menu = gt.get("menu") or []
    if isinstance(menu, dict):
        return [menu]
    return [m for m in menu if isinstance(m, dict)]


def to_extraction(gt: dict, doc_id: str) -> ExtractionResult:
    sub_total = gt.get("sub_total") or {}
    total = gt.get("total") or {}
    fields = {
        "subtotal": FieldValue(value=_scalar(sub_total.get("subtotal_price")), source="parser"),
        "tax_total": FieldValue(value=_scalar(sub_total.get("tax_price")), source="parser"),
        "discount_total": FieldValue(value=_scalar(sub_total.get("discount_price")), source="parser"),
        "amount_total": FieldValue(value=_scalar(total.get("total_price")), source="parser"),
    }
    line_items = []
    for menu in _menus(gt):
        line_items.append(
            LineItem(
                description=FieldValue(value=_scalar(menu.get("nm")), source="parser"),
                quantity=FieldValue(value=_scalar(menu.get("cnt")), source="parser"),
                unit_price=FieldValue(value=_scalar(menu.get("unitprice")), source="parser"),
                amount=FieldValue(value=_scalar(menu.get("price")), source="parser"),
            )
        )
    return ExtractionResult(
        doc_id=doc_id,
        doc_type="receipt",
        pipeline="layout_llm",
        model="cord_ground_truth",
        fields=fields,
        line_items=line_items,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("parquet", type=Path, default=ROOT / "data/raw/cord_test.parquet", nargs="?")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    images_dir = ROOT / "data" / "raw" / "cord"
    gt_dir = ROOT / "data" / "ground_truth" / "cord"
    for directory in (images_dir, gt_dir):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)

    rows = pq.read_table(args.parquet).to_pylist()
    manifest: list[dict] = []
    for row in rows:
        if len(manifest) >= args.limit:
            break
        raw = json.loads(row["ground_truth"])
        gt = raw.get("gt_parse") or {}
        meta = raw.get("meta") or {}
        image_id = int(meta.get("image_id", len(manifest)))
        doc_id = f"cord_test_{image_id:04d}"

        image_bytes = row["image"]["bytes"]
        if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
            extension = ".png"
        elif image_bytes[:2] == b"\xff\xd8":
            extension = ".jpg"
        else:
            raise ValueError(f"{doc_id}: unsupported image magic {image_bytes[:8]!r}")
        image_path = images_dir / f"{doc_id}{extension}"
        image_path.write_bytes(image_bytes)

        extraction = to_extraction(gt, doc_id)
        (gt_dir / f"{doc_id}.json").write_text(
            extraction.model_dump_json(indent=2), encoding="utf-8"
        )
        size = meta.get("image_size") or {}
        width = int(size.get("width") or 0)
        height = int(size.get("height") or 0)
        # Resolution is an objective proxy; blur/rotation still needs manual review.
        quality_tier = "lowres" if 0 < min(width, height) < 700 else "scan"
        manifest.append(
            {
                "doc_id": doc_id,
                "filename": image_path.relative_to(ROOT).as_posix(),
                "doc_type": "receipt",
                "source_dataset": "cord",
                "quality_tier": quality_tier,
                "layout_tier": "single_column",
                "page_count": 1,
                "image_width": size.get("width"),
                "image_height": size.get("height"),
                "annotation": f"data/ground_truth/cord/{doc_id}.json",
                "split": "test",
            }
        )

    manifest_path = ROOT / "data" / "ground_truth" / "manifest.jsonl"
    existing = []
    if manifest_path.is_file():
        existing = [
            json.loads(line)
            for line in manifest_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and json.loads(line).get("source_dataset") != "cord"
        ]
    combined = existing + manifest
    manifest_path.write_text(
        "\n".join(json.dumps(m, ensure_ascii=False) for m in combined) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(manifest)} cord samples -> {images_dir}, {gt_dir}, {manifest_path}")


if __name__ == "__main__":
    main()
