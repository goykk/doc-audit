from fastapi.testclient import TestClient

from app import auth
from app.api.main import app
from app.config import settings


def test_role_levels():
    assert auth.allowed(auth.Principal("viewer", "viewer"), "GET")
    assert not auth.allowed(auth.Principal("viewer", "viewer"), "POST")
    assert auth.allowed(auth.Principal("reviewer", "reviewer"), "POST")
    assert auth.allowed(auth.Principal("admin", "admin"), "DELETE")


def test_api_key_guard():
    old_required = settings.auth_required
    old_keys = settings.api_keys
    object.__setattr__(settings, "auth_required", True)
    object.__setattr__(
        settings,
        "api_keys",
        '{"viewer-key":"viewer","reviewer-key":"reviewer","admin-key":"admin"}',
    )
    try:
        client = TestClient(app)
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/v1/stats").status_code == 401
        assert (
            client.get("/api/v1/stats", headers={"Authorization": "Bearer nope"}).status_code
            == 401
        )
        viewer = {"Authorization": "Bearer viewer-key"}
        assert client.get("/api/v1/stats", headers=viewer).status_code not in {401, 403}
        assert (
            client.post(
                "/api/v1/review/batch",
                headers=viewer,
                json={"item_ids": [], "action": "reject"},
            ).status_code
            == 403
        )
        reviewer = {"X-API-Key": "reviewer-key"}
        assert (
            client.post(
                "/api/v1/review/batch",
                headers=reviewer,
                json={"item_ids": [], "action": "reject"},
            ).status_code
            == 422
        )
    finally:
        object.__setattr__(settings, "auth_required", old_required)
        object.__setattr__(settings, "api_keys", old_keys)
