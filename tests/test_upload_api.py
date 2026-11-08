import io

from fastapi.testclient import TestClient

from app.api.main import app
from app.services.upload_service import _detect


def test_detect_supported_magic_bytes():
    assert _detect(b"%PDF-1.7") == "pdf"
    assert _detect(b"\x89PNG\r\n\x1a\nrest") == "png"
    assert _detect(b"\xff\xd8\xffrest") == "jpg"


def test_upload_rejects_unknown_file_type():
    response = TestClient(app).post(
        "/api/v1/documents",
        files={"file": ("note.txt", io.BytesIO(b"hello"), "text/plain")},
        data={"doc_type": "cn_invoice"},
    )
    assert response.status_code == 400
    assert "仅支持" in response.json()["detail"]


def test_upload_rejects_empty_file():
    response = TestClient(app).post(
        "/api/v1/documents",
        files={"file": ("empty.png", io.BytesIO(b""), "image/png")},
        data={"doc_type": "cn_invoice"},
    )
    assert response.status_code == 400
    assert "为空" in response.json()["detail"]


def test_batch_review_requires_items():
    response = TestClient(app).post(
        "/api/v1/review/batch", json={"item_ids": [], "action": "reject"}
    )
    assert response.status_code == 422
