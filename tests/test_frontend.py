from fastapi.testclient import TestClient

from app.api.main import app


def test_frontend_is_served():
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "DocAudit" in response.text
    assert "/api/v1/documents" in response.text
    assert "bbox" in response.text
    assert "pipe-btn" in response.text
    assert "pipeline=" in response.text
    assert "A/B 并排对比" in response.text
    assert "compareModal" in response.text
    assert "choose-btn" in response.text
    assert "colHeadC" in response.text
    assert "queueModal" in response.text
    assert "datasetFilter" in response.text
    assert "statusFilter" in response.text
    assert "docPickerModal" in response.text
    assert "docPickerSearch" in response.text
    assert "statsModal" in response.text
    assert "statsBtn" in response.text
    assert "auditModal" in response.text
    assert "auditBtn" in response.text
    assert "revalidateBtn" in response.text
    assert "batchReject" in response.text
    assert "batchAccept" in response.text
