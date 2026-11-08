"""MySQL persistence and review-queue queries."""
from __future__ import annotations

import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.config import settings
from app.evaluation.runner import load_manifest
from app.extraction_result import ExtractionResult
from app.validation.duplicates import DuplicateIndex
from app.validation.engine import ValidationReport, load_rules, validate
from app.validation.input_validation import validate_review_value

LINE_ITEM_PATH = re.compile(r"^line_items\[(\d+)\]\.(description|quantity|unit_price|amount)$")

REVIEW_ACTION_STATUS = {
    "accept": "accepted",
    "modify": "corrected",
    "reject": "rejected",
}


class ReviewConflict(RuntimeError):
    """The review item has already been resolved."""


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(settings.database_url, pool_pre_ping=True, pool_recycle=1800)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _loads(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    return json.loads(value)


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def set_field_value(result: dict, field_path: str, value: Any) -> dict:
    """Set a value inside an ExtractionResult dict; returns the mutated dict."""
    match = LINE_ITEM_PATH.match(field_path)
    if match:
        index = int(match.group(1))
        name = match.group(2)
        items = result.setdefault("line_items", [])
        while len(items) <= index:
            items.append(
                {
                    "description": {"value": None, "quote": None, "bbox": None, "confidence": 1.0, "source": "reviewer"},
                    "quantity": {"value": None, "quote": None, "bbox": None, "confidence": 1.0, "source": "reviewer"},
                    "unit_price": {"value": None, "quote": None, "bbox": None, "confidence": 1.0, "source": "reviewer"},
                    "amount": {"value": None, "quote": None, "bbox": None, "confidence": 1.0, "source": "reviewer"},
                }
            )
        item = items[index].setdefault(name, {})
        item["value"] = value
        item["source"] = "reviewer"
        item["confidence"] = 1.0
        return result
    if field_path.startswith("line_items["):
        raise ValueError(f"unsupported line item path: {field_path}")
    field = result.setdefault("fields", {}).setdefault(
        field_path, {"value": None, "quote": None, "bbox": None, "confidence": 1.0, "source": "reviewer"}
    )
    field["value"] = value
    field["source"] = "reviewer"
    field["confidence"] = 1.0
    return result


def _document_status(validation: ValidationReport) -> str:
    return validation.status


def _persist_one(
    conn,
    row: dict,
    extraction: ExtractionResult,
    validation: ValidationReport,
) -> tuple[int, int]:
    conn.execute(
        text(
            """
            INSERT INTO documents
                (doc_id, filename, doc_type, source_dataset, quality_tier, layout_tier, page_count, status)
            VALUES
                (:doc_id, :filename, :doc_type, :source_dataset, :quality_tier, :layout_tier, :page_count, :status)
            ON DUPLICATE KEY UPDATE
                filename=VALUES(filename), doc_type=VALUES(doc_type),
                source_dataset=VALUES(source_dataset), quality_tier=VALUES(quality_tier),
                layout_tier=VALUES(layout_tier), page_count=VALUES(page_count), status=VALUES(status)
            """
        ),
        {
            "doc_id": row["doc_id"],
            "filename": row["filename"],
            "doc_type": row.get("doc_type", "receipt"),
            "source_dataset": row.get("source_dataset", "unknown"),
            "quality_tier": row.get("quality_tier", "unknown"),
            "layout_tier": row.get("layout_tier", "unknown"),
            "page_count": int(row.get("page_count", 1)),
            "status": _document_status(validation),
        },
    )
    document_id = conn.execute(
        text("SELECT id FROM documents WHERE doc_id=:doc_id"), {"doc_id": row["doc_id"]}
    ).scalar_one()

    # Re-running a pipeline replaces only that pipeline; the other route stays intact.
    conn.execute(
        text("UPDATE extractions SET is_current=0 WHERE document_id=:document_id"),
        {"document_id": document_id},
    )
    conn.execute(
        text("DELETE FROM extractions WHERE document_id=:document_id AND pipeline=:pipeline"),
        {"document_id": document_id, "pipeline": extraction.pipeline},
    )
    insert = conn.execute(
        text(
            """
            INSERT INTO extractions
                (document_id, pipeline, is_current, model, result_json, latency_ms,
                 prompt_tokens, completion_tokens, cost_cny)
            VALUES
                (:document_id, :pipeline, 1, :model, :result_json, :latency_ms,
                 :prompt_tokens, :completion_tokens, :cost_cny)
            """
        ),
        {
            "document_id": document_id,
            "pipeline": extraction.pipeline,
            "model": extraction.model,
            "result_json": extraction.model_dump_json(),
            "latency_ms": extraction.latency_ms,
            "prompt_tokens": extraction.prompt_tokens,
            "completion_tokens": extraction.completion_tokens,
            "cost_cny": extraction.cost_cny,
        },
    )
    extraction_id = int(insert.lastrowid)

    for path, field_value in extraction.iter_fields():
        conn.execute(
            text(
                """
                INSERT INTO field_values
                    (extraction_id, field_path, field_value, quote, bbox, confidence, source)
                VALUES
                    (:extraction_id, :field_path, :field_value, :quote, :bbox, :confidence, :source)
                """
            ),
            {
                "extraction_id": extraction_id,
                "field_path": path,
                "field_value": _json(field_value.value),
                "quote": field_value.quote,
                "bbox": field_value.bbox.model_dump_json() if field_value.bbox else None,
                "confidence": field_value.confidence,
                "source": field_value.source,
            },
        )

    audit_log = [
        {
            "event": "validated",
            "by": "system",
            "at": datetime.now(timezone.utc).isoformat(),
            "pipeline": extraction.pipeline,
            "model": extraction.model,
        }
    ]
    conn.execute(
        text(
            """
            INSERT INTO validations
                (extraction_id, rule_hits, passed, warn_count, error_count, status, audit_log)
            VALUES
                (:extraction_id, :rule_hits, :passed, :warn_count, :error_count, :status, :audit_log)
            """
        ),
        {
            "extraction_id": extraction_id,
            "rule_hits": _json([issue.as_dict() for issue in validation.issues]),
            "passed": 1 if validation.status == "accepted" else 0,
            "warn_count": len(validation.warnings),
            "error_count": len(validation.errors),
            "status": validation.status,
            "audit_log": _json(audit_log),
        },
    )

    for issue in validation.issues:
        conn.execute(
            text(
                """
                INSERT INTO review_items
                    (document_id, extraction_id, field_path, rule_id, reason,
                     original_value, suggested_value, status)
                VALUES
                    (:document_id, :extraction_id, :field_path, :rule_id, :reason,
                     :original_value, :suggested_value, 'pending')
                """
            ),
            {
                "document_id": document_id,
                "extraction_id": extraction_id,
                "field_path": issue.field_path,
                "rule_id": issue.rule_id,
                "reason": issue.message,
                "original_value": _json(issue.current_value),
                "suggested_value": _json(issue.suggested_value),
            },
        )
    conn.execute(
        text("UPDATE documents SET updated_at=NOW() WHERE id=:id"), {"id": document_id}
    )
    _bump_stats_version(conn)
    invalidate_stats_cache()
    return document_id, extraction_id


def persist_predictions(
    pred_dir: Path,
    dataset: str,
    manifest_path: Path,
    rules_config: dict | None = None,
) -> dict:
    config = rules_config or load_rules()
    rows = [row for row in load_manifest(manifest_path) if row.get("source_dataset") == dataset]
    if not rows:
        raise ValueError(f"no manifest rows for dataset {dataset}")

    predictions: list[tuple[dict, ExtractionResult]] = []
    for row in rows:
        path = pred_dir / f"{row['doc_id']}.json"
        if not path.is_file():
            raise FileNotFoundError(path)
        predictions.append(
            (row, ExtractionResult.model_validate_json(path.read_text(encoding="utf-8")))
        )

    index = DuplicateIndex(
        threshold=float(config["engine"].get("duplicate_vector_threshold", 0.92))
    )
    for _, extraction in predictions:
        index.add(extraction, dataset)

    reports = [
        (row, extraction, validate(extraction, dataset=dataset, rules_config=config, duplicate_index=index))
        for row, extraction in predictions
    ]

    status_counts = {"accepted": 0, "review": 0, "rejected": 0}
    review_items = 0
    with get_engine().begin() as conn:
        for row, extraction, validation in reports:
            _persist_one(conn, row, extraction, validation)
            status_counts[validation.status] += 1
            review_items += len(validation.issues)

    return {
        "dataset": dataset,
        "documents": len(reports),
        "status_counts": status_counts,
        "review_items": review_items,
    }


def _review_item_dict(row) -> dict:
    data = dict(row)
    for key in ("original_value", "suggested_value"):
        data[key] = _loads(data.get(key))
    if data.get("created_at"):
        data["created_at"] = _iso(data["created_at"])
    return data


def _search_mode(search: str | None) -> tuple[str, str | None]:
    if not search or not search.strip():
        return "none", None
    text_q = search.strip()
    if re.fullmatch(r"[Rr]\d{3}", text_q):
        return "rule", text_q.upper()
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", text_q):
        return "prefix", text_q
    return "fulltext", text_q


def _review_base(status: str, rule_id: str | None = None) -> tuple[list[str], dict[str, Any]]:
    clauses = ["r.status = :status"]
    params: dict[str, Any] = {"status": status}
    if rule_id:
        clauses.append("r.rule_id = :rule_id")
        params["rule_id"] = rule_id
    return clauses, params


def _prefix_id_sql(status: str, rule_id: str | None, prefix_text: str):
    """UNION of three index-friendly prefix lookups; avoids OR + full scan."""
    base, params = _review_base(status, rule_id)
    where = " AND ".join(base)
    params["prefix"] = f"{prefix_text}%"
    sql = f"""
        SELECT r.id FROM review_items r
        JOIN documents d ON d.id = r.document_id
        WHERE {where} AND d.doc_id LIKE :prefix
        UNION
        SELECT r.id FROM review_items r
        WHERE {where} AND r.rule_id LIKE :prefix
        UNION
        SELECT r.id FROM review_items r
        WHERE {where} AND r.field_path LIKE :prefix
    """
    return sql, params


def _review_where(status: str, rule_id: str | None = None, search: str | None = None):
    clauses, params = _review_base(status, rule_id)
    mode, text_q = _search_mode(search)
    if mode == "rule":
        clauses.append("r.rule_id = :rule_exact")
        params["rule_exact"] = text_q
    elif mode == "prefix":
        # Kept for direct query callers; get_review_queue uses _prefix_id_sql instead.
        clauses.append(
            "(d.doc_id LIKE :prefix OR r.rule_id LIKE :prefix OR r.field_path LIKE :prefix)"
        )
        params["prefix"] = f"{text_q}%"
    elif mode == "fulltext":
        clauses.append("MATCH(r.reason) AGAINST (:ft_q IN BOOLEAN MODE)")
        params["ft_q"] = f'"{text_q.replace(chr(34), " ")}"'
    return " AND ".join(clauses), params


def get_review_queue(
    status: str = "pending",
    limit: int = 50,
    offset: int = 0,
    rule_id: str | None = None,
    search: str | None = None,
) -> list[dict]:
    mode, text_q = _search_mode(search)
    select_fields = """
        SELECT r.id, r.document_id, r.extraction_id, r.field_path, r.rule_id, r.reason,
               r.original_value, r.suggested_value, r.status, r.created_at,
               d.doc_id, d.doc_type, d.source_dataset, d.quality_tier,
               e.pipeline, e.model
        FROM review_items r
        JOIN documents d ON d.id = r.document_id
        JOIN extractions e ON e.id = r.extraction_id
    """
    if mode == "prefix":
        ids_sql, params = _prefix_id_sql(status, rule_id, text_q)
        query = text(
            f"""
            SELECT r.id, r.document_id, r.extraction_id, r.field_path, r.rule_id, r.reason,
                   r.original_value, r.suggested_value, r.status, r.created_at,
                   d.doc_id, d.doc_type, d.source_dataset, d.quality_tier,
                   e.pipeline, e.model
            FROM ({ids_sql}) ids
            JOIN review_items r ON r.id = ids.id
            JOIN documents d ON d.id = r.document_id
            JOIN extractions e ON e.id = r.extraction_id
            ORDER BY r.id
            LIMIT :limit OFFSET :offset
            """
        )
    else:
        where, params = _review_where(status, rule_id, search)
        query = text(f"{select_fields} WHERE {where} ORDER BY r.id LIMIT :limit OFFSET :offset")
    with get_engine().connect() as conn:
        rows = conn.execute(
            query, {**params, "limit": limit, "offset": offset}
        ).mappings()
        return [_review_item_dict(row) for row in rows]


def count_review_queue(
    status: str = "pending", rule_id: str | None = None, search: str | None = None
) -> int:
    mode, text_q = _search_mode(search)
    if mode == "prefix":
        ids_sql, params = _prefix_id_sql(status, rule_id, text_q)
        query = text(f"SELECT COUNT(*) FROM ({ids_sql}) AS matched")
    else:
        where, params = _review_where(status, rule_id, search)
        query = text(
            f"""
            SELECT COUNT(*)
            FROM review_items r
            JOIN documents d ON d.id = r.document_id
            WHERE {where}
            """
        )
    with get_engine().connect() as conn:
        return int(conn.execute(query, params).scalar_one())


def list_review_rules(status: str = "pending") -> list[str]:
    query = text(
        "SELECT DISTINCT rule_id FROM review_items WHERE status=:status ORDER BY rule_id"
    )
    with get_engine().connect() as conn:
        return [row[0] for row in conn.execute(query, {"status": status})]


def get_review_item(item_id: int) -> dict | None:
    query = text(
        """
        SELECT r.id, r.document_id, r.extraction_id, r.field_path, r.rule_id, r.reason,
               r.original_value, r.suggested_value, r.status, r.reviewer_note,
               r.created_at, r.resolved_at, d.doc_id, d.doc_type, e.pipeline, e.model
        FROM review_items r
        JOIN documents d ON d.id = r.document_id
        JOIN extractions e ON e.id = r.extraction_id
        WHERE r.id = :item_id
        """
    )
    with get_engine().connect() as conn:
        row = conn.execute(query, {"item_id": item_id}).mappings().first()
    if row is None:
        return None
    data = _review_item_dict(row)
    for key in ("created_at", "resolved_at"):
        if data.get(key):
            data[key] = _iso(data[key])
    return data


def _revalidate_extraction(
    conn,
    extraction_id: int,
    document_id: int,
    dataset: str,
    event: dict | None = None,
) -> ValidationReport:
    row = conn.execute(
        text("SELECT result_json FROM extractions WHERE id=:id"), {"id": extraction_id}
    ).mappings().first()
    if row is None:
        raise ValueError("extraction not found")
    result = _loads(row["result_json"]) or {}
    extraction = ExtractionResult.model_validate(result)

    rules = load_rules()
    index = DuplicateIndex(threshold=float(rules["engine"]["duplicate_vector_threshold"]))
    others = conn.execute(
        text(
            """
            SELECT d.source_dataset, e.result_json
            FROM documents d
            JOIN extractions e ON e.id = (
                SELECT id FROM extractions
                WHERE document_id=d.id AND is_current=1 ORDER BY id DESC LIMIT 1
            )
            WHERE d.id <> :document_id
            """
        ),
        {"document_id": document_id},
    ).mappings()
    for other in others:
        index.add(ExtractionResult.model_validate_json(other["result_json"]), other["source_dataset"])

    report = validate(extraction, dataset=dataset, rules_config=rules, duplicate_index=index)
    validation = conn.execute(
        text(
            "SELECT id, status, audit_log FROM validations WHERE extraction_id=:id ORDER BY id DESC LIMIT 1"
        ),
        {"id": extraction_id},
    ).mappings().first()
    old_status = validation["status"] if validation else None
    audit = (_loads(validation["audit_log"]) or []) if validation else []
    if event:
        audit.append(event)
    audit.append(
        {
            "event": "revalidated",
            "before_status": old_status,
            "after_status": report.status,
            "rules": [issue.rule_id for issue in report.issues],
            "by": "system",
            "at": datetime.now(timezone.utc).isoformat(),
        }
    )

    payload = {
        "rule_hits": _json([issue.as_dict() for issue in report.issues]),
        "passed": 1 if report.status == "accepted" else 0,
        "warn_count": len(report.warnings),
        "error_count": len(report.errors),
        "status": report.status,
        "audit": _json(audit),
    }
    if validation is None:
        conn.execute(
            text(
                """
                INSERT INTO validations
                    (extraction_id, rule_hits, passed, warn_count, error_count, status, audit_log)
                VALUES
                    (:extraction_id, :rule_hits, :passed, :warn_count, :error_count, :status, :audit)
                """
            ),
            {**payload, "extraction_id": extraction_id},
        )
    else:
        conn.execute(
            text(
                """
                UPDATE validations
                SET rule_hits=:rule_hits, passed=:passed, warn_count=:warn_count,
                    error_count=:error_count, status=:status, audit_log=:audit
                WHERE id=:id
                """
            ),
            {**payload, "id": validation["id"]},
        )
    return report


def revalidate_document(doc_id: str, pipeline: str | None = None) -> dict:
    with get_engine().begin() as conn:
        document = conn.execute(
            text("SELECT id, source_dataset FROM documents WHERE doc_id=:doc_id"),
            {"doc_id": doc_id},
        ).mappings().first()
        if document is None:
            raise LookupError("document not found")
        extraction = conn.execute(
            text(
                """
                SELECT id, pipeline, is_current FROM extractions
                WHERE document_id=:document_id
                  AND (:pipeline IS NULL OR pipeline=:pipeline)
                ORDER BY is_current DESC, id DESC LIMIT 1
                """
            ),
            {"document_id": document["id"], "pipeline": pipeline},
        ).mappings().first()
        if extraction is None:
            raise LookupError("extraction not found for pipeline")
        event = {
            "event": "manual_revalidate",
            "pipeline": extraction["pipeline"],
            "by": "human",
            "at": datetime.now(timezone.utc).isoformat(),
        }
        report = _revalidate_extraction(
            conn,
            int(extraction["id"]),
            int(document["id"]),
            document["source_dataset"],
            event=event,
        )
        if extraction["is_current"]:
            conn.execute(
                text("UPDATE documents SET status=:status WHERE id=:id"),
                {"status": report.status, "id": document["id"]},
            )
        else:
            conn.execute(
                text("UPDATE documents SET updated_at=NOW() WHERE id=:id"),
                {"id": document["id"]},
            )
        _bump_stats_version(conn)
        invalidate_stats_cache()
    return {
        "doc_id": doc_id,
        "pipeline": extraction["pipeline"],
        "status": report.status,
        "errors": len(report.errors),
        "warnings": len(report.warnings),
        "is_current": bool(extraction["is_current"]),
    }


def apply_review_action(item_id: int, action: str, value: Any = None, note: str | None = None) -> dict:
    if action not in REVIEW_ACTION_STATUS:
        raise ValueError(f"unsupported action: {action}")

    with get_engine().begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT r.id, r.document_id, r.extraction_id, r.field_path, r.suggested_value, r.rule_id, r.status,
                       e.result_json, e.is_current, d.source_dataset, v.id AS validation_id, v.audit_log
                FROM review_items r
                JOIN extractions e ON e.id = r.extraction_id
                JOIN documents d ON d.id = r.document_id
                JOIN validations v ON v.extraction_id = r.extraction_id
                WHERE r.id = :item_id
                """
            ),
            {"item_id": item_id},
        ).mappings().first()
        if row is None:
            return {}
        if row["status"] != "pending":
            raise ReviewConflict(f"review item already {row['status']}")

        suggested = _loads(row["suggested_value"])
        if action == "accept" and row["rule_id"] in {"R003", "R005"}:
            raise ValueError("该问题必须人工修正字段，不能直接采纳")
        effective_value = value
        if effective_value is None and action == "accept" and row["field_path"]:
            effective_value = suggested
        if action == "modify" and effective_value is None:
            raise ValueError("modify action requires a value")

        if effective_value is not None and row["field_path"]:
            effective_value = validate_review_value(
                row["field_path"], effective_value, row["source_dataset"]
            )

        result_json = _loads(row["result_json"]) or {}
        if effective_value is not None and row["field_path"]:
            set_field_value(result_json, row["field_path"], effective_value)
            conn.execute(
                text("UPDATE extractions SET result_json=:payload WHERE id=:id"),
                {"payload": _json(result_json), "id": row["extraction_id"]},
            )
            conn.execute(
                text(
                    """
                    UPDATE field_values
                    SET field_value=:value, source='reviewer', confidence=1.0
                    WHERE extraction_id=:extraction_id AND field_path=:field_path
                    """
                ),
                {
                    "value": _json(effective_value),
                    "extraction_id": row["extraction_id"],
                    "field_path": row["field_path"],
                },
            )

        status = REVIEW_ACTION_STATUS[action]
        conn.execute(
            text(
                """
                UPDATE review_items
                SET status=:status, reviewer_note=:note, resolved_at=NOW()
                WHERE id=:item_id
                """
            ),
            {"status": status, "note": note, "item_id": item_id},
        )

        revalidated = False
        final_status = None
        if (
            action in {"modify", "accept"}
            and effective_value is not None
            and row["field_path"]
        ):
            report = _revalidate_extraction(
                conn,
                int(row["extraction_id"]),
                int(row["document_id"]),
                row["source_dataset"],
                event={
                    "event": "review_action",
                    "action": action,
                    "item_id": item_id,
                    "field_path": row["field_path"],
                    "old_value": _loads(row["original_value"]),
                    "new_value": effective_value,
                    "value": effective_value,
                    "note": note,
                    "by": "human",
                    "at": datetime.now(timezone.utc).isoformat(),
                },
            )
            pending = {
                (item["rule_id"], item["field_path"])
                for item in conn.execute(
                    text(
                        """
                        SELECT rule_id, field_path FROM review_items
                        WHERE extraction_id=:extraction_id AND status='pending'
                        """
                    ),
                    {"extraction_id": row["extraction_id"]},
                ).mappings()
            }
            for issue in report.issues:
                if (issue.rule_id, issue.field_path) in pending:
                    continue
                conn.execute(
                    text(
                        """
                        INSERT INTO review_items
                            (document_id, extraction_id, field_path, rule_id, reason,
                             original_value, suggested_value, status)
                        VALUES
                            (:document_id, :extraction_id, :field_path, :rule_id, :reason,
                             :original_value, :suggested_value, 'pending')
                        """
                    ),
                    {
                        "document_id": row["document_id"],
                        "extraction_id": row["extraction_id"],
                        "field_path": issue.field_path,
                        "rule_id": issue.rule_id,
                        "reason": issue.message,
                        "original_value": _json(issue.current_value),
                        "suggested_value": _json(issue.suggested_value),
                    },
                )
            pending_count = conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM review_items
                    WHERE extraction_id=:extraction_id AND status='pending'
                    """
                ),
                {"extraction_id": row["extraction_id"]},
            ).scalar_one()
            rejected_count = conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM review_items
                    WHERE extraction_id=:extraction_id AND status='rejected'
                    """
                ),
                {"extraction_id": row["extraction_id"]},
            ).scalar_one()
            if rejected_count:
                final_status = "rejected"
            elif report.status == "rejected":
                final_status = "rejected"
            elif pending_count:
                final_status = "review"
            else:
                final_status = report.status
            if row["is_current"]:
                conn.execute(
                    text("UPDATE documents SET status=:status WHERE id=:id"),
                    {"status": final_status, "id": row["document_id"]},
                )
            conn.execute(
                text(
                    """
                    UPDATE validations SET status=:status, passed=:passed
                    WHERE extraction_id=:extraction_id
                    """
                ),
                {
                    "status": final_status,
                    "passed": 1 if final_status == "accepted" else 0,
                    "extraction_id": row["extraction_id"],
                },
            )
            revalidated = True
        else:
            # A rejection (or an accept without a field change) closes the item directly.
            remaining = conn.execute(
                text(
                    """
                    SELECT status, COUNT(*) AS n FROM review_items
                    WHERE extraction_id=:extraction_id AND status='pending'
                    GROUP BY status
                    """
                ),
                {"extraction_id": row["extraction_id"]},
            ).all()
            if not remaining:
                rejected = conn.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM review_items
                        WHERE extraction_id=:extraction_id AND status='rejected'
                        """
                    ),
                    {"extraction_id": row["extraction_id"]},
                ).scalar_one()
                final_status = "rejected" if rejected else "accepted"
                if row["is_current"]:
                    conn.execute(
                        text("UPDATE documents SET status=:status WHERE id=:id"),
                        {"status": final_status, "id": row["document_id"]},
                    )
                conn.execute(
                    text(
                        """
                        UPDATE validations SET status=:status, passed=:passed
                        WHERE extraction_id=:extraction_id
                        """
                    ),
                    {
                        "status": final_status,
                        "passed": 1 if final_status == "accepted" else 0,
                        "extraction_id": row["extraction_id"],
                    },
                )

        latest = conn.execute(
            text("SELECT audit_log FROM validations WHERE id=:id"), {"id": row["validation_id"]}
        ).mappings().first()
        audit = (_loads(latest["audit_log"]) or []) if latest else []
        audit.append(
            {
                "event": "reviewed",
                "item_id": item_id,
                "action": action,
                "field_path": row["field_path"],
                "value": effective_value,
                "note": note,
                "by": "human",
                "at": datetime.now(timezone.utc).isoformat(),
                "document_status": final_status,
                "revalidated": revalidated,
            }
        )
        conn.execute(
            text("UPDATE validations SET audit_log=:audit WHERE id=:id"),
            {"audit": _json(audit), "id": row["validation_id"]},
        )
        conn.execute(
            text("UPDATE documents SET updated_at=NOW() WHERE id=:id"),
            {"id": row["document_id"]},
        )
        _bump_stats_version(conn)
        invalidate_stats_cache()

    return get_review_item(item_id) or {}


def _replace_field_values(conn, extraction_id: int, result: dict) -> None:
    conn.execute(
        text("DELETE FROM field_values WHERE extraction_id=:extraction_id"),
        {"extraction_id": extraction_id},
    )
    rows = []
    for path, field in (result.get("fields") or {}).items():
        rows.append((path, field))
    for index, item in enumerate(result.get("line_items") or []):
        for name in ("description", "quantity", "unit_price", "amount"):
            field = item.get(name) or {}
            rows.append((f"line_items[{index}].{name}", field))
    for path, field in rows:
        bbox = field.get("bbox")
        conn.execute(
            text(
                """
                INSERT INTO field_values
                    (extraction_id, field_path, field_value, quote, bbox, confidence, source)
                VALUES
                    (:extraction_id, :field_path, :field_value, :quote, :bbox, :confidence, :source)
                """
            ),
            {
                "extraction_id": extraction_id,
                "field_path": path,
                "field_value": _json(field.get("value")),
                "quote": field.get("quote"),
                "bbox": _json(bbox) if isinstance(bbox, dict) else None,
                "confidence": field.get("confidence", 1.0),
                "source": field.get("source", "reviewer"),
            },
        )


def _result_value(result: dict, field_path: str) -> Any:
    match = LINE_ITEM_PATH.match(field_path)
    if match:
        index, name = int(match.group(1)), match.group(2)
        items = result.get("line_items") or []
        if index >= len(items):
            return None
        field = items[index].get(name) or {}
        return field.get("value")
    field = (result.get("fields") or {}).get(field_path) or {}
    return field.get("value")


def apply_pipeline_selection(
    doc_id: str, field_path: str, source_pipeline: str, note: str | None = None
) -> dict:
    """Adopt a field (or whole line item) from route A/B into a separate merged version.

    The source pipelines are never modified, so every decision remains reversible by
    selecting the other side again.
    """
    with get_engine().begin() as conn:
        document = conn.execute(
            text("SELECT id, status, source_dataset, doc_type FROM documents WHERE doc_id=:doc_id"),
            {"doc_id": doc_id},
        ).mappings().first()
        if document is None:
            raise FileNotFoundError(doc_id)

        current = conn.execute(
            text(
                """
                SELECT * FROM extractions WHERE document_id=:document_id AND is_current=1
                ORDER BY id DESC LIMIT 1
                """
            ),
            {"document_id": document["id"]},
        ).mappings().first()
        source = conn.execute(
            text(
                """
                SELECT * FROM extractions WHERE document_id=:document_id AND pipeline=:pipeline
                ORDER BY id DESC LIMIT 1
                """
            ),
            {"document_id": document["id"], "pipeline": source_pipeline},
        ).mappings().first()
        if current is None:
            raise ValueError("current extraction not found")
        if source is None:
            raise ValueError(f"source pipeline {source_pipeline} not found")

        merged = conn.execute(
            text(
                """
                SELECT * FROM extractions WHERE document_id=:document_id AND pipeline='merged'
                ORDER BY id DESC LIMIT 1
                """
            ),
            {"document_id": document["id"]},
        ).mappings().first()

        if merged is None:
            target_result = _loads(current["result_json"]) or {}
            target_result["pipeline"] = "merged"
            target_result["model"] = "merged"
            conn.execute(
                text("UPDATE extractions SET is_current=0 WHERE document_id=:document_id"),
                {"document_id": document["id"]},
            )
            insert = conn.execute(
                text(
                    """
                    INSERT INTO extractions
                        (document_id, pipeline, is_current, model, result_json, latency_ms,
                         prompt_tokens, completion_tokens, cost_cny)
                    VALUES
                        (:document_id, 'merged', 1, 'merged', :result_json, 0, 0, 0, 0)
                    """
                ),
                {
                    "document_id": document["id"],
                    "result_json": _json(target_result),
                },
            )
            target_id = int(insert.lastrowid)
            current_validation = conn.execute(
                text(
                    "SELECT * FROM validations WHERE extraction_id=:id ORDER BY id DESC LIMIT 1"
                ),
                {"id": current["id"]},
            ).mappings().first()
            if current_validation is None:
                current_validation = {
                    "rule_hits": "[]",
                    "passed": 0,
                    "warn_count": 0,
                    "error_count": 0,
                    "status": document["status"],
                }
            conn.execute(
                text(
                    """
                    INSERT INTO validations
                        (extraction_id, rule_hits, passed, warn_count, error_count, status, audit_log)
                    VALUES
                        (:extraction_id, :rule_hits, :passed, :warn_count, :error_count, :status, :audit_log)
                    """
                ),
                {
                    "extraction_id": target_id,
                    "rule_hits": current_validation["rule_hits"],
                    "passed": current_validation["passed"],
                    "warn_count": current_validation["warn_count"],
                    "error_count": current_validation["error_count"],
                    "status": current_validation["status"],
                    "audit_log": _json(
                        [
                            {
                                "event": "merged_created",
                                "from_pipeline": current["pipeline"],
                                "by": "system",
                                "at": datetime.now(timezone.utc).isoformat(),
                            }
                        ]
                    ),
                },
            )
            conn.execute(
                text("UPDATE documents SET status=:status WHERE id=:id"),
                {"status": current_validation["status"], "id": document["id"]},
            )
        else:
            target_id = int(merged["id"])
            target_result = _loads(merged["result_json"]) or {}
            conn.execute(
                text("UPDATE extractions SET is_current=0 WHERE document_id=:document_id"),
                {"document_id": document["id"]},
            )
            conn.execute(
                text("UPDATE extractions SET is_current=1 WHERE id=:id"), {"id": target_id}
            )

        source_result = _loads(source["result_json"]) or {}
        old_value = _result_value(target_result, field_path)

        match = LINE_ITEM_PATH.match(field_path)
        if match:
            index = int(match.group(1))
            source_items = source_result.get("line_items") or []
            if index >= len(source_items):
                target_items = target_result.setdefault("line_items", [])
                if index < len(target_items):
                    del target_items[index]
            else:
                source_item = source_items[index]
                for name in ("description", "quantity", "unit_price", "amount"):
                    field = source_item.get(name) or {}
                    set_field_value(
                        target_result, f"line_items[{index}].{name}", field.get("value")
                    )
        else:
            if field_path not in (source_result.get("fields") or {}) and field_path not in (
                target_result.get("fields") or {}
            ):
                raise ValueError(f"unknown field path: {field_path}")
            field = (source_result.get("fields") or {}).get(field_path) or {}
            set_field_value(target_result, field_path, field.get("value"))

        target_result["pipeline"] = "merged"
        target_result["model"] = "merged"
        new_value = _result_value(target_result, field_path)
        conn.execute(
            text("UPDATE extractions SET result_json=:payload WHERE id=:id"),
            {"payload": _json(target_result), "id": target_id},
        )
        _replace_field_values(conn, target_id, target_result)

        report = _revalidate_extraction(
            conn,
            target_id,
            document["id"],
            document["source_dataset"],
            event={
                "event": "pipeline_selection",
                "field_path": field_path,
                "source_pipeline": source_pipeline,
                "target_pipeline": "merged",
                "old_value": old_value,
                "new_value": new_value,
                "changed": old_value != new_value,
                "note": note,
                "by": "human",
                "at": datetime.now(timezone.utc).isoformat(),
            },
        )

        conn.execute(
            text("DELETE FROM review_items WHERE extraction_id=:extraction_id"),
            {"extraction_id": target_id},
        )
        for issue in report.issues:
            conn.execute(
                text(
                    """
                    INSERT INTO review_items
                        (document_id, extraction_id, field_path, rule_id, reason,
                         original_value, suggested_value, status)
                    VALUES
                        (:document_id, :extraction_id, :field_path, :rule_id, :reason,
                         :original_value, :suggested_value, 'pending')
                    """
                ),
                {
                    "document_id": document["id"],
                    "extraction_id": target_id,
                    "field_path": issue.field_path,
                    "rule_id": issue.rule_id,
                    "reason": issue.message,
                    "original_value": _json(issue.current_value),
                    "suggested_value": _json(issue.suggested_value),
                },
            )
        conn.execute(
            text("UPDATE documents SET status=:status WHERE id=:id"),
            {"status": report.status, "id": document["id"]},
        )
        _bump_stats_version(conn)
        invalidate_stats_cache()

    detail = get_document(doc_id, pipeline="merged")
    return {"changed": old_value != new_value, "detail": detail}


def filter_audit_events(
    events: list[dict],
    pipeline: str | None = None,
    event: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    filtered = []
    for item in events:
        if pipeline and item.get("pipeline") != pipeline:
            continue
        if event and item.get("event") != event:
            continue
        at_date = str(item.get("at") or "")[:10]
        if date_from and at_date and at_date < date_from:
            continue
        if date_to and at_date and at_date > date_to:
            continue
        filtered.append(item)
    return filtered


def get_document_audit(
    doc_id: str,
    limit: int = 100,
    offset: int = 0,
    pipeline: str | None = None,
    event: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict | None:
    with get_engine().connect() as conn:
        document = conn.execute(
            text("SELECT id FROM documents WHERE doc_id=:doc_id"), {"doc_id": doc_id}
        ).mappings().first()
        if document is None:
            return None
        rows = conn.execute(
            text(
                """
                SELECT e.pipeline, e.model, v.status AS validation_status, v.audit_log
                FROM extractions e
                LEFT JOIN validations v ON v.extraction_id = e.id
                WHERE e.document_id=:document_id
                ORDER BY e.id
                """
            ),
            {"document_id": document["id"]},
        ).mappings()
        events = []
        for row in rows:
            for item in _loads(row["audit_log"]) or []:
                if not isinstance(item, dict):
                    continue
                event_item = dict(item)
                event_item["pipeline"] = row["pipeline"]
                event_item["validation_status"] = row["validation_status"]
                events.append(event_item)
    events.sort(key=lambda item: item.get("at") or "", reverse=True)
    filtered = filter_audit_events(events, pipeline, event, date_from, date_to)
    return {
        "doc_id": doc_id,
        "total": len(filtered),
        "limit": limit,
        "offset": offset,
        "events": filtered[offset : offset + limit],
    }


def get_document(doc_id: str, pipeline: str | None = None) -> dict | None:
    with get_engine().connect() as conn:
        document = conn.execute(
            text("SELECT * FROM documents WHERE doc_id=:doc_id"), {"doc_id": doc_id}
        ).mappings().first()
        if document is None:
            return None
        doc = dict(document)
        doc["created_at"] = doc["created_at"].isoformat() if doc.get("created_at") else None
        doc["updated_at"] = doc["updated_at"].isoformat() if doc.get("updated_at") else None

        pipeline_rows = conn.execute(
            text(
                """
                SELECT e.id, e.pipeline, e.model, e.latency_ms, e.cost_cny, e.is_current,
                       v.status, v.error_count, v.warn_count,
                       (SELECT COUNT(*) FROM review_items r
                        WHERE r.extraction_id=e.id AND r.status='pending') AS pending
                FROM extractions e
                LEFT JOIN validations v ON v.extraction_id = e.id
                WHERE e.document_id=:document_id
                ORDER BY e.id
                """
            ),
            {"document_id": doc["id"]},
        ).mappings()
        pipelines = []
        for row in pipeline_rows:
            item = dict(row)
            item["cost_cny"] = float(item["cost_cny"]) if item.get("cost_cny") is not None else 0.0
            item["is_current"] = bool(item["is_current"])
            item["selected"] = False
            pipelines.append(item)

        if pipeline:
            extraction = conn.execute(
                text(
                    """
                    SELECT * FROM extractions
                    WHERE document_id=:document_id AND pipeline=:pipeline
                    ORDER BY id DESC LIMIT 1
                    """
                ),
                {"document_id": doc["id"], "pipeline": pipeline},
            ).mappings().first()
        else:
            extraction = conn.execute(
                text(
                    """
                    SELECT * FROM extractions WHERE document_id=:document_id
                    ORDER BY is_current DESC, id DESC LIMIT 1
                    """
                ),
                {"document_id": doc["id"]},
            ).mappings().first()

        if extraction is None:
            return {
                "document": doc,
                "extraction": None,
                "validation": None,
                "review_items": [],
                "pipelines": pipelines,
                "selected_pipeline": pipeline,
                "selected_status": doc.get("status"),
            }

        ext = dict(extraction)
        ext["result_json"] = _loads(ext["result_json"])
        ext["cost_cny"] = float(ext["cost_cny"])
        ext["is_current"] = bool(ext.get("is_current"))
        ext["created_at"] = ext["created_at"].isoformat() if ext.get("created_at") else None

        validation = conn.execute(
            text("SELECT * FROM validations WHERE extraction_id=:id ORDER BY id DESC LIMIT 1"),
            {"id": ext["id"]},
        ).mappings().first()
        val = None
        if validation:
            val = dict(validation)
            val["rule_hits"] = _loads(val["rule_hits"])
            val["audit_log"] = _loads(val["audit_log"]) or []
            val["passed"] = bool(val["passed"])
            val["created_at"] = val["created_at"].isoformat() if val.get("created_at") else None

        items = conn.execute(
            text(
                """
                SELECT id, field_path, rule_id, reason, original_value, suggested_value,
                       status, reviewer_note, created_at, resolved_at
                FROM review_items WHERE extraction_id=:id ORDER BY id
                """
            ),
            {"id": ext["id"]},
        ).mappings()
        review_items = []
        for item in items:
            data = _review_item_dict(item)
            data.pop("doc_id", None)
            if data.get("resolved_at"):
                data["resolved_at"] = _iso(data["resolved_at"])
            review_items.append(data)

        for item in pipelines:
            item["selected"] = item["id"] == ext["id"]

    return {
        "document": doc,
        "extraction": ext,
        "validation": val,
        "review_items": review_items,
        "pipelines": pipelines,
        "selected_pipeline": ext["pipeline"],
        "selected_status": val["status"] if val else doc.get("status"),
    }


def get_document_file(doc_id: str) -> str | None:
    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT filename FROM documents WHERE doc_id=:doc_id"), {"doc_id": doc_id}
        ).first()
    return row[0] if row else None


def create_document(
    doc_id: str,
    filename: str,
    doc_type: str,
    page_count: int = 1,
    status: str = "uploaded",
) -> int:
    with get_engine().begin() as conn:
        result = conn.execute(
            text(
                """
                INSERT INTO documents
                    (doc_id, filename, doc_type, source_dataset, quality_tier, layout_tier, page_count, status)
                VALUES
                    (:doc_id, :filename, :doc_type, 'upload', 'unknown', 'single_page', :page_count, :status)
                """
            ),
            {
                "doc_id": doc_id,
                "filename": filename,
                "doc_type": doc_type,
                "page_count": page_count,
                "status": status,
            },
        )
    return int(result.lastrowid)


def load_current_extractions(exclude_doc_id: str | None = None) -> list[tuple[str, str, ExtractionResult]]:
    query = text(
        """
        SELECT d.doc_id, d.source_dataset, e.result_json
        FROM documents d
        JOIN extractions e ON e.id = (
            SELECT id FROM extractions
            WHERE document_id = d.id AND is_current = 1
            ORDER BY id DESC LIMIT 1
        )
        WHERE d.doc_id <> :exclude
        """
    )
    rows = []
    with get_engine().connect() as conn:
        for row in conn.execute(query, {"exclude": exclude_doc_id or ""}).mappings():
            rows.append(
                (row["doc_id"], row["source_dataset"], ExtractionResult.model_validate_json(row["result_json"]))
            )
    return rows


def save_extraction(
    row: dict, extraction: ExtractionResult, validation: ValidationReport
) -> tuple[int, int]:
    with get_engine().begin() as conn:
        return _persist_one(conn, row, extraction, validation)


def _document_base_filters(dataset: str | None = None, status: str | None = None):
    clauses = []
    params: dict[str, Any] = {}
    if dataset:
        clauses.append("d.source_dataset = :dataset")
        params["dataset"] = dataset
    if status:
        clauses.append("d.status = :status")
        params["status"] = status
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def _document_filters(
    dataset: str | None = None, status: str | None = None, search: str | None = None
):
    where, params = _document_base_filters(dataset, status)
    clauses = []
    if search and search.strip():
        # Two channels: indexed doc_id prefix + ngram filename phrase.
        text_q = search.strip()
        clauses.append(
            "(d.doc_id LIKE :qprefix OR MATCH(d.filename) AGAINST (:ft_q IN BOOLEAN MODE))"
        )
        params["qprefix"] = f"{text_q}%"
        params["ft_q"] = f'"{text_q.replace(chr(34), " ")}"'
        if clauses:
            where = (where + " AND " if where else " WHERE ") + " AND ".join(clauses)
    return where, params


_STATS_CACHE: dict[str, dict] = {}
STATS_TTL_SECONDS = 60


def invalidate_stats_cache() -> None:
    _STATS_CACHE.clear()


def _bump_stats_version(conn) -> None:
    conn.execute(text("UPDATE stats_version SET version = version + 1 WHERE id = 1"))


def stats_overview(dataset: str | None = None, status: str | None = None) -> dict:
    cache_key = f"{dataset or ''}|{status or ''}"
    now = time.monotonic()
    with get_engine().connect() as conn:
        version = conn.execute(
            text("SELECT version FROM stats_version WHERE id = 1")
        ).scalar_one()
        cached = _STATS_CACHE.get(cache_key)
        if (
            cached
            and cached["version"] == version
            and now - cached["at"] < STATS_TTL_SECONDS
        ):
            return cached["data"]

        where, params = _document_base_filters(dataset, status)
        connector = " AND " if where else " WHERE "
        doc_rows = conn.execute(
            text(f"SELECT d.status, COUNT(*) FROM documents d{where} GROUP BY d.status"),
            params,
        ).all()
        review_rows = conn.execute(
            text(
                f"SELECT r.status, COUNT(*) FROM review_items r "
                f"JOIN documents d ON d.id = r.document_id{where} GROUP BY r.status"
            ),
            params,
        ).all()
        dataset_rows = conn.execute(
            text(
                f"SELECT d.source_dataset, COUNT(*) FROM documents d{where} "
                "GROUP BY d.source_dataset ORDER BY d.source_dataset"
            ),
            params,
        ).all()
        resolved_today = conn.execute(
            text(
                "SELECT COUNT(*) FROM review_items r JOIN documents d ON d.id = r.document_id"
                f"{where}{connector} r.status <> 'pending' AND r.resolved_at >= CURDATE()"
            ),
            params,
        ).scalar_one()
        updated_today = conn.execute(
            text(
                f"SELECT COUNT(*) FROM documents d{where}"
                f"{connector} d.updated_at >= CURDATE()"
            ),
            params,
        ).scalar_one()
        latency, cost = conn.execute(
            text(
                "SELECT AVG(e.latency_ms), COALESCE(SUM(e.cost_cny), 0) "
                "FROM extractions e JOIN documents d ON d.id = e.document_id"
                f"{where}{connector} e.is_current = 1"
            ),
            params,
        ).one()
        created_rows = conn.execute(
            text(
                "SELECT DATE(d.created_at) AS day, COUNT(*) FROM documents d"
                f"{where}{connector} d.created_at >= CURDATE() - INTERVAL 6 DAY GROUP BY day"
            ),
            params,
        ).all()
        resolved_rows = conn.execute(
            text(
                "SELECT DATE(r.resolved_at) AS day, COUNT(*) FROM review_items r "
                "JOIN documents d ON d.id = r.document_id"
                f"{where}{connector} r.resolved_at >= CURDATE() - INTERVAL 6 DAY GROUP BY day"
            ),
            params,
        ).all()

    doc_by_status = {row[0]: int(row[1]) for row in doc_rows}
    review_by_status = {row[0]: int(row[1]) for row in review_rows}
    created_map = {row[0]: int(row[1]) for row in created_rows}
    resolved_map = {row[0]: int(row[1]) for row in resolved_rows}
    today = date.today()
    trend = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        trend.append(
            {
                "date": day.isoformat(),
                "label": day.strftime("%m-%d"),
                "created": created_map.get(day, 0),
                "resolved": resolved_map.get(day, 0),
            }
        )

    data = {
        "dataset_filter": dataset,
        "status_filter": status,
        "documents": {
            "total": sum(doc_by_status.values()),
            "by_status": doc_by_status,
            "updated_today": int(updated_today),
        },
        "review": {
            "pending": review_by_status.get("pending", 0),
            "by_status": review_by_status,
            "resolved_today": int(resolved_today),
        },
        "datasets": [{"value": row[0], "count": int(row[1])} for row in dataset_rows],
        "pipelines": {
            "avg_latency_ms": round(float(latency), 1) if latency is not None else None,
            "total_cost_cny": round(float(cost), 4),
        },
        "trend": trend,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _STATS_CACHE[cache_key] = {"at": now, "version": version, "data": data}
    return data


def document_facets(dataset: str | None = None, status: str | None = None) -> dict:
    """Faceted counts: dataset counts honor status, status counts honor dataset."""
    dataset_where = " WHERE status = :status" if status else ""
    status_where = " WHERE source_dataset = :dataset" if dataset else ""
    with get_engine().connect() as conn:
        datasets = [
            {"value": row[0], "count": int(row[1])}
            for row in conn.execute(
                text(
                    f"SELECT source_dataset, COUNT(*) FROM documents{dataset_where} "
                    "GROUP BY source_dataset ORDER BY source_dataset"
                ),
                {"status": status} if status else {},
            )
        ]
        statuses = [
            {"value": row[0], "count": int(row[1])}
            for row in conn.execute(
                text(
                    f"SELECT status, COUNT(*) FROM documents{status_where} "
                    "GROUP BY status ORDER BY status"
                ),
                {"dataset": dataset} if dataset else {},
            )
        ]
    return {"datasets": datasets, "statuses": statuses}


def _document_search_ids_sql(
    dataset: str | None, status: str | None, search: str
) -> tuple[str, dict]:
    where, params = _document_base_filters(dataset, status)
    connector = " AND " if where else " WHERE "
    text_q = search.strip()
    params["qprefix"] = f"{text_q}%"
    params["ft_q"] = f'"{text_q.replace(chr(34), " ")}"'
    sql = f"""
        SELECT d.id FROM documents d{where}{connector}d.doc_id LIKE :qprefix
        UNION
        SELECT d.id FROM documents d{where}{connector}MATCH(d.filename) AGAINST (:ft_q IN BOOLEAN MODE)
    """
    return sql, params


def count_documents(
    dataset: str | None = None, status: str | None = None, search: str | None = None
) -> int:
    if search and search.strip():
        ids_sql, params = _document_search_ids_sql(dataset, status, search)
        query = text(f"SELECT COUNT(*) FROM ({ids_sql}) AS matched")
    else:
        where, params = _document_base_filters(dataset, status)
        query = text(f"SELECT COUNT(*) FROM documents d{where}")
    with get_engine().connect() as conn:
        return int(conn.execute(query, params).scalar_one())


def list_documents(
    limit: int = 100,
    offset: int = 0,
    dataset: str | None = None,
    status: str | None = None,
    search: str | None = None,
) -> list[dict]:
    fields = """
        SELECT d.id, d.doc_id, d.filename, d.doc_type, d.source_dataset, d.quality_tier,
               d.layout_tier, d.page_count, d.status, d.created_at, d.updated_at,
               e.pipeline, e.model, e.latency_ms, e.cost_cny, v.status AS current_status,
               (SELECT GROUP_CONCAT(e2.pipeline ORDER BY e2.pipeline)
                FROM extractions e2 WHERE e2.document_id = d.id) AS pipelines
    """
    joins = """
        LEFT JOIN extractions e ON e.id = (
            SELECT id FROM extractions
            WHERE document_id = d.id AND is_current = 1
            ORDER BY id DESC LIMIT 1
        )
        LEFT JOIN validations v ON v.extraction_id = e.id
    """
    if search and search.strip():
        ids_sql, params = _document_search_ids_sql(dataset, status, search)
        params["qexact"] = search.strip()
        ranked_fields = fields.replace(
            "SELECT d.id,",
            "SELECT d.id, CASE WHEN d.doc_id = :qexact THEN 0 "
            "WHEN d.doc_id LIKE :qprefix THEN 1 ELSE 2 END AS result_rank,",
        )
        query = text(
            f"{ranked_fields} FROM ({ids_sql}) ids JOIN documents d ON d.id = ids.id {joins} "
            "ORDER BY result_rank, d.updated_at DESC, d.id DESC "
            "LIMIT :limit OFFSET :offset"
        )
    else:
        where, params = _document_base_filters(dataset, status)
        query = text(
            f"{fields} FROM documents d {joins} {where} "
            "ORDER BY d.updated_at DESC, d.id DESC LIMIT :limit OFFSET :offset"
        )
    with get_engine().connect() as conn:
        rows = conn.execute(query, {**params, "limit": limit, "offset": offset}).mappings()
        documents = []
        for row in rows:
            data = dict(row)
            data["created_at"] = data["created_at"].isoformat() if data.get("created_at") else None
            data["updated_at"] = data["updated_at"].isoformat() if data.get("updated_at") else None
            if data.get("cost_cny") is not None:
                data["cost_cny"] = float(data["cost_cny"])
            documents.append(data)
    return documents
