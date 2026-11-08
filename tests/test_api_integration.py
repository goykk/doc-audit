import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.main import app
from app.db import repository


def _require_db():
    try:
        with repository.get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        if os.getenv("REQUIRE_DB_TESTS") == "1":
            raise
        pytest.skip(f"MySQL not available: {exc.__class__.__name__}")


@pytest.fixture()
def seeded_document():
    _require_db()
    repository.invalidate_stats_cache()
    with repository.get_engine().begin() as conn:
        conn.execute(text("DELETE FROM documents WHERE doc_id='ci_smoke_doc'"))
        conn.execute(
            text(
                """
                INSERT INTO documents
                    (doc_id, filename, doc_type, source_dataset, quality_tier,
                     layout_tier, page_count, status)
                VALUES
                    ('ci_smoke_doc', 'ci_smoke.png', 'cn_invoice', 'ci_smoke',
                     'clear', 'single_column', 1, 'review')
                """
            )
        )
        document_id = conn.execute(
            text("SELECT id FROM documents WHERE doc_id='ci_smoke_doc'")
        ).scalar_one()
        result = {
            "doc_id": "ci_smoke_doc",
            "doc_type": "cn_invoice",
            "pipeline": "vlm_e2e",
            "model": "ci",
            "fields": {
                "invoice_no": {"value": "CI-001", "confidence": 1.0, "source": "vlm"},
                "amount_total": {"value": "100.00", "confidence": 1.0, "source": "vlm"},
            },
            "line_items": [],
        }
        conn.execute(
            text(
                """
                INSERT INTO extractions
                    (document_id, pipeline, is_current, model, result_json, latency_ms, cost_cny)
                VALUES
                    (:document_id, 'vlm_e2e', 1, 'ci', :result_json, 10, 0.001)
                """
            ),
            {"document_id": document_id, "result_json": repository._json(result)},
        )
        extraction_id = conn.execute(
            text("SELECT id FROM extractions WHERE document_id=:document_id"),
            {"document_id": document_id},
        ).scalar_one()
        audit = [
            {
                "event": "review_action",
                "field_path": "amount_total",
                "old_value": "90.00",
                "new_value": "100.00",
                "action": "modify",
                "by": "human",
                "at": "2026-11-08T10:00:00+00:00",
            }
        ]
        conn.execute(
            text(
                """
                INSERT INTO validations
                    (extraction_id, rule_hits, passed, warn_count, error_count, status, audit_log)
                VALUES
                    (:extraction_id, '[]', 0, 0, 1, 'review', :audit)
                """
            ),
            {"extraction_id": extraction_id, "audit": repository._json(audit)},
        )
        conn.execute(
            text(
                """
                INSERT INTO review_items
                    (document_id, extraction_id, field_path, rule_id, reason,
                     original_value, suggested_value, status)
                VALUES
                    (:document_id, :extraction_id, 'amount_total', 'R003',
                     'CI 校验项', '"90.00"', '"100.00"', 'pending')
                """
            ),
            {"document_id": document_id, "extraction_id": extraction_id},
        )
    try:
        yield "ci_smoke_doc"
    finally:
        with repository.get_engine().begin() as conn:
            conn.execute(text("DELETE FROM documents WHERE doc_id='ci_smoke_doc'"))
        repository.invalidate_stats_cache()


def test_stats_endpoint_filters_dataset(seeded_document):
    response = TestClient(app).get("/api/v1/stats?dataset=ci_smoke")
    assert response.status_code == 200
    data = response.json()
    assert data["dataset_filter"] == "ci_smoke"
    assert data["documents"]["total"] == 1
    assert data["review"]["pending"] == 1
    assert data["datasets"] == [{"value": "ci_smoke", "count": 1}]


def test_audit_endpoint_filters_and_returns_old_new(seeded_document):
    response = TestClient(app).get(
        "/api/v1/documents/ci_smoke_doc/audit?event=review_action"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    event = data["events"][0]
    assert event["pipeline"] == "vlm_e2e"
    assert event["field_path"] == "amount_total"
    assert event["old_value"] == "90.00"
    assert event["new_value"] == "100.00"


def test_audit_csv_has_bom_and_safe_header(seeded_document):
    response = TestClient(app).get("/api/v1/documents/ci_smoke_doc/audit.csv")
    assert response.status_code == 200
    assert response.content.startswith(b"\xef\xbb\xbf")
    text_body = response.content.decode("utf-8-sig")
    assert text_body.splitlines()[0].startswith("at,pipeline,event,field_path")
    assert "review_action" in text_body


def test_revalidate_updates_status_and_audit(seeded_document):
    client = TestClient(app)
    response = client.post("/api/v1/documents/ci_smoke_doc/revalidate")
    assert response.status_code == 200
    data = response.json()
    assert data["pipeline"] == "vlm_e2e"
    assert data["status"] in {"accepted", "review", "rejected"}

    audit = client.get(
        "/api/v1/documents/ci_smoke_doc/audit?event=manual_revalidate"
    ).json()
    assert audit["total"] >= 1
