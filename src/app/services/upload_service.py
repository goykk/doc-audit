"""Upload storage and one-shot route-B extraction for the demo UI."""
from __future__ import annotations

import uuid
from pathlib import Path

import pymupdf

from app.config import PROJECT_ROOT
from app.db import repository
from app.evaluation.runner import load_field_specs
from app.extractors.route_b import extract_route_b
from app.validation.duplicates import DuplicateIndex
from app.validation.engine import load_rules, validate

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
UPLOAD_DIR = PROJECT_ROOT / "data" / "uploads"


def _detect(content: bytes) -> str:
    if content.startswith(b"%PDF"):
        return "pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if content.startswith(b"\xff\xd8"):
        return "jpg"
    raise ValueError("仅支持 PDF / PNG / JPG 文件")


def save_uploaded_document(filename: str, content: bytes, doc_type: str) -> dict:
    if not content:
        raise ValueError("文件为空")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError(f"文件超过 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB 限制")
    if doc_type not in {"cn_invoice", "receipt"}:
        raise ValueError("doc_type 必须是 cn_invoice 或 receipt")

    kind = _detect(content)
    doc_id = "upload_" + uuid.uuid4().hex[:10]
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    original = UPLOAD_DIR / f"{doc_id}.{kind}"
    original.write_bytes(content)

    page_count = 1
    if kind == "pdf":
        try:
            document = pymupdf.open(original)
        except Exception as exc:  # noqa: BLE001 - convert library error
            original.unlink(missing_ok=True)
            raise ValueError("PDF 无法解析") from exc
        page_count = max(1, document.page_count)
        page = document[0]
        zoom = min(200 / 72, 3000 / max(page.rect.width, page.rect.height))
        preview_path = UPLOAD_DIR / f"{doc_id}.png"
        page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False).save(preview_path)
        document.close()
    else:
        try:
            pixmap = pymupdf.Pixmap(str(original))
        except Exception as exc:  # noqa: BLE001
            original.unlink(missing_ok=True)
            raise ValueError("图片无法解析") from exc
        if pixmap.width < 20 or pixmap.height < 20:
            original.unlink(missing_ok=True)
            raise ValueError("图片尺寸过小")
        preview_path = original

    relative = preview_path.relative_to(PROJECT_ROOT).as_posix()
    repository.create_document(
        doc_id=doc_id,
        filename=relative,
        doc_type=doc_type,
        page_count=page_count,
        status="uploaded",
    )
    data = repository.get_document(doc_id)
    if data is None:
        raise RuntimeError("文档写入数据库失败")
    return data


def extract_uploaded_document(doc_id: str) -> dict:
    detail = repository.get_document(doc_id)
    if detail is None:
        raise FileNotFoundError(doc_id)
    document = detail["document"]
    source = (PROJECT_ROOT / document["filename"]).resolve()
    if not source.is_file():
        raise FileNotFoundError(str(source))

    doc_type = document["doc_type"]
    spec_key = "synthetic" if doc_type == "cn_invoice" else "upload_receipt"
    spec = load_field_specs(PROJECT_ROOT / "data/ground_truth/dataset_fields.yaml")[spec_key]

    index = DuplicateIndex(threshold=float(load_rules()["engine"]["duplicate_vector_threshold"]))
    for existing_doc_id, dataset, extraction in repository.load_current_extractions(exclude_doc_id=doc_id):
        index.add(extraction, dataset)

    extraction = extract_route_b(source, doc_id, spec, doc_type=doc_type)
    validation = validate(extraction, dataset="upload", duplicate_index=index)

    row = {
        "doc_id": doc_id,
        "filename": document["filename"],
        "doc_type": doc_type,
        "source_dataset": "upload",
        "quality_tier": "unknown",
        "layout_tier": "single_page",
        "page_count": document["page_count"],
    }
    repository.save_extraction(row, extraction, validation)
    data = repository.get_document(doc_id)
    if data is None:
        raise RuntimeError("抽取结果写入失败")
    return data


__all__ = ["MAX_UPLOAD_BYTES", "save_uploaded_document", "extract_uploaded_document"]
