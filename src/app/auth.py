"""Optional API-key authentication and coarse role enforcement."""
from __future__ import annotations

import hmac
import json
from dataclasses import dataclass

from app.config import settings

ROLE_LEVEL = {"viewer": 1, "reviewer": 2, "admin": 3}
PUBLIC_PATHS = {"/", "/api/health", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json", "/favicon.ico"}


@dataclass(frozen=True)
class Principal:
    name: str
    role: str


def _parse_keys() -> dict[str, str]:
    raw = settings.api_keys.strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): str(role) for key, role in data.items() if str(role) in ROLE_LEVEL}


def authenticate(token: str | None) -> Principal | None:
    if not token:
        return None
    for key, role in _parse_keys().items():
        if hmac.compare_digest(token, key):
            return Principal(name=key[:8], role=role)
    return None


def required_role(method: str) -> str:
    return "viewer" if method in {"GET", "HEAD", "OPTIONS"} else "reviewer"


def allowed(principal: Principal, method: str) -> bool:
    return ROLE_LEVEL.get(principal.role, 0) >= ROLE_LEVEL[required_role(method)]
