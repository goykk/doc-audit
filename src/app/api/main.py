"""FastAPI entrypoint: health, review queue, review actions, document read APIs."""
from __future__ import annotations

import csv
import io
import json
from datetime import date
from typing import Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError

from app import auth
from app.config import PROJECT_ROOT, settings
from app.db import repository
from app.extractors.llm_client import LLMError
from app.services import upload_service

app = FastAPI(title="DocAudit", version="0.3.0")


@app.middleware("http")
async def api_key_guard(request: Request, call_next):
    if not settings.auth_required or request.method == "OPTIONS" or request.url.path in auth.PUBLIC_PATHS:
        return await call_next(request)
    token = request.headers.get("X-API-Key", "")
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    principal = auth.authenticate(token)
    if principal is None:
        return JSONResponse(status_code=401, content={"detail": "missing or invalid API key"})
    if not auth.allowed(principal, request.method):
        return JSONResponse(status_code=403, content={"detail": "insufficient role"})
    request.state.principal = principal
    return await call_next(request)


def _csv_safe(value: Any) -> str:
    if value is None:
        return ""
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
    if text.startswith(("=", "+", "@", "\t", "\r")):
        return "'" + text
    return text


class ReviewAction(BaseModel):
    action: Literal["accept", "modify", "reject"]
    value: Any = None
    note: str | None = None


class ExtractRequest(BaseModel):
    doc_id: str
    pipeline: Literal["vlm_e2e"] = "vlm_e2e"


class PipelineSelection(BaseModel):
    field_path: str
    source_pipeline: Literal["layout_llm", "vlm_e2e"]
    note: str | None = None


class BatchReviewAction(BaseModel):
    item_ids: list[int] = Field(min_length=1, max_length=200)
    action: Literal["reject", "accept"] = "reject"
    note: str | None = None


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "llm_model": settings.llm_model,
        "vlm_model": settings.vlm_model,
        "pdf_render_dpi": settings.pdf_render_dpi,
        "auto_accept_confidence": settings.auto_accept_confidence,
    }


@app.post("/api/v1/documents")
async def upload_document(
    file: UploadFile = File(...),
    doc_type: Literal["cn_invoice", "receipt"] = Form("cn_invoice"),
) -> dict:
    content = await file.read()
    try:
        detail = upload_service.save_uploaded_document(file.filename or "upload", content, doc_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return detail


@app.post("/api/v1/extract")
def extract_document(payload: ExtractRequest) -> dict:
    try:
        return upload_service.extract_uploaded_document(payload.doc_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="document or source file not found") from exc
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=f"model call failed: {str(exc)[:300]}") from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/review/queue")
def review_queue(
    status: Literal["pending", "accepted", "corrected", "rejected"] = "pending",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    rule_id: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=100),
) -> dict:
    try:
        items = repository.get_review_queue(
            status=status, limit=limit, offset=offset, rule_id=rule_id, search=q
        )
        total = repository.count_review_queue(status=status, rule_id=rule_id, search=q)
        rules = repository.list_review_rules(status=status)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {
        "items": items,
        "count": len(items),
        "total": total,
        "limit": limit,
        "offset": offset,
        "rules": rules,
        "status": status,
    }


@app.post("/api/v1/review/batch")
def batch_review(payload: BatchReviewAction) -> dict:
    processed = 0
    errors: list[dict] = []
    seen: set[int] = set()
    for item_id in payload.item_ids:
        if item_id in seen:
            continue
        seen.add(item_id)
        try:
            item = repository.apply_review_action(
                item_id, payload.action, note=payload.note
            )
            if not item:
                errors.append({"item_id": item_id, "error": "not found"})
                continue
            processed += 1
        except repository.ReviewConflict as exc:
            errors.append({"item_id": item_id, "error": str(exc)})
        except ValueError as exc:
            errors.append({"item_id": item_id, "error": str(exc)})
        except SQLAlchemyError:
            errors.append({"item_id": item_id, "error": "database unavailable"})
    return {"processed": processed, "failed": len(errors), "errors": errors[:20]}


@app.post("/api/v1/review/{item_id}")
def review_action(item_id: int, payload: ReviewAction) -> dict:
    if payload.action == "modify" and payload.value is None:
        raise HTTPException(status_code=400, detail="modify requires a value")
    try:
        item = repository.apply_review_action(
            item_id, payload.action, value=payload.value, note=payload.note
        )
    except repository.ReviewConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    if not item:
        raise HTTPException(status_code=404, detail="review item not found")
    return item


@app.get("/api/v1/documents")
def documents(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    dataset: str | None = Query(default=None, max_length=32),
    status: str | None = Query(default=None, max_length=16),
    q: str | None = Query(default=None, max_length=100),
) -> dict:
    try:
        rows = repository.list_documents(
            limit=limit, offset=offset, dataset=dataset, status=status, search=q
        )
        total = repository.count_documents(dataset=dataset, status=status, search=q)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {
        "items": rows,
        "count": len(rows),
        "total": total,
        "limit": limit,
        "offset": offset,
        "dataset": dataset,
        "status": status,
        "q": q,
    }


@app.get("/api/v1/stats")
def stats(
    dataset: str | None = Query(default=None, max_length=32),
    status: str | None = Query(default=None, max_length=16),
) -> dict:
    try:
        return repository.stats_overview(dataset=dataset, status=status)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc


@app.get("/api/v1/documents/facets")
def document_facets(
    dataset: str | None = Query(default=None, max_length=32),
    status: str | None = Query(default=None, max_length=16),
) -> dict:
    try:
        return repository.document_facets(dataset=dataset, status=status)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc


@app.post("/api/v1/documents/{doc_id}/revalidate")
def revalidate_document(
    doc_id: str, pipeline: str | None = Query(default=None, max_length=32)
) -> dict:
    try:
        return repository.revalidate_document(doc_id, pipeline=pipeline)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc


@app.get("/api/v1/documents/{doc_id}/audit")
def document_audit(
    doc_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    pipeline: str | None = Query(default=None, max_length=32),
    event: str | None = Query(default=None, max_length=40),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
) -> dict:
    try:
        data = repository.get_document_audit(
            doc_id,
            limit=limit,
            offset=offset,
            pipeline=pipeline,
            event=event,
            date_from=date_from.isoformat() if date_from else None,
            date_to=date_to.isoformat() if date_to else None,
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    if data is None:
        raise HTTPException(status_code=404, detail="document not found")
    return data


@app.get("/api/v1/documents/{doc_id}/audit.csv")
def document_audit_csv(
    doc_id: str,
    pipeline: str | None = Query(default=None, max_length=32),
    event: str | None = Query(default=None, max_length=40),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
) -> Response:
    try:
        data = repository.get_document_audit(
            doc_id,
            limit=5000,
            pipeline=pipeline,
            event=event,
            date_from=date_from.isoformat() if date_from else None,
            date_to=date_to.isoformat() if date_to else None,
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    if data is None:
        raise HTTPException(status_code=404, detail="document not found")
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["at", "pipeline", "event", "field_path", "old_value", "new_value",
         "action", "note", "by", "validation_status"]
    )
    for item in data["events"]:
        writer.writerow(
            [
                _csv_safe(item.get("at")),
                _csv_safe(item.get("pipeline")),
                _csv_safe(item.get("event")),
                _csv_safe(item.get("field_path")),
                _csv_safe(item.get("old_value")),
                _csv_safe(item.get("new_value")),
                _csv_safe(item.get("action")),
                _csv_safe(item.get("note")),
                _csv_safe(item.get("by")),
                _csv_safe(item.get("validation_status")),
            ]
        )
    safe_name = "".join(ch for ch in doc_id if ch.isalnum() or ch in "._-")[:80] or "document"
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}_audit.csv"'},
    )


@app.get("/api/v1/documents/{doc_id}")
def document(
    doc_id: str,
    pipeline: Literal["layout_llm", "vlm_e2e", "merged"] | None = None,
) -> dict:
    try:
        data = repository.get_document(doc_id, pipeline=pipeline)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    if data is None:
        raise HTTPException(status_code=404, detail="document not found")
    if pipeline and data.get("extraction") is None:
        raise HTTPException(status_code=404, detail=f"pipeline {pipeline} not found for document")
    return data


@app.get("/api/v1/documents/{doc_id}/compare")
def compare_document(doc_id: str) -> dict:
    try:
        layout = repository.get_document(doc_id, pipeline="layout_llm")
        vlm = repository.get_document(doc_id, pipeline="vlm_e2e")
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    if layout is None or vlm is None:
        raise HTTPException(status_code=404, detail="document not found")
    if not layout.get("extraction") or not vlm.get("extraction"):
        raise HTTPException(status_code=404, detail="both pipelines are required for comparison")
    current = repository.get_document(doc_id)
    return {
        "document": layout["document"],
        "layout_llm": layout,
        "vlm_e2e": vlm,
        "current": current,
        "current_pipeline": current.get("selected_pipeline") if current else None,
    }


@app.post("/api/v1/documents/{doc_id}/select")
def select_pipeline_value(doc_id: str, payload: PipelineSelection) -> dict:
    try:
        return repository.apply_pipeline_selection(
            doc_id,
            payload.field_path,
            payload.source_pipeline,
            note=payload.note,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="document not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc


@app.get("/api/v1/documents/{doc_id}/image")
def document_image(doc_id: str) -> FileResponse:
    try:
        filename = repository.get_document_file(doc_id)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    if not filename:
        raise HTTPException(status_code=404, detail="document not found")
    path = (PROJECT_ROOT / filename).resolve()
    data_root = (PROJECT_ROOT / "data").resolve()
    if not path.is_relative_to(data_root) or not path.is_file():
        raise HTTPException(status_code=404, detail="source image not found")
    return FileResponse(path)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(PROJECT_ROOT / "src" / "frontend" / "index.html")
