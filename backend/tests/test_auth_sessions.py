from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers.auth import build_auth_router
from app.middleware.request_guards import RequestGuardMiddleware
from app.services.auth import AuthService
from app.services.document_registry import DocumentRegistry


def _client() -> tuple[TestClient, AuthService]:
    registry = DocumentRegistry(":memory:")
    auth = AuthService(
        registry,
        password_hash=AuthService.hash_password("correct horse battery staple"),
        session_ttl_seconds=3600,
        cookie_secure=False,
    )
    app = FastAPI()
    app.include_router(build_auth_router(auth), prefix="/api")

    @app.post("/api/private")
    def private():
        return {"ok": True}

    app.add_middleware(
        RequestGuardMiddleware,
        auth_service=auth,
        rate_limit_requests=20,
        rate_limit_window_seconds=60,
    )
    return TestClient(app), auth


def test_login_uses_http_only_cookie_and_csrf_for_mutations():
    client, _ = _client()

    failed = client.post("/api/auth/login", json={"password": "wrong"})
    assert failed.status_code == 401

    response = client.post("/api/auth/login", json={"password": "correct horse battery staple"})
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    csrf = response.json()["session"]["csrf_token"]

    assert client.get("/api/auth/session").json()["session"]["authenticated"] is True
    assert client.post("/api/private").status_code == 403
    assert client.post("/api/private", headers={"X-CSRF-Token": csrf}).json() == {"ok": True}


def test_logout_revokes_server_side_session():
    client, _ = _client()
    login = client.post("/api/auth/login", json={"password": "correct horse battery staple"})
    csrf = login.json()["session"]["csrf_token"]

    logout = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
    assert logout.status_code == 200
    assert client.get("/api/auth/session").json()["session"]["authenticated"] is False
    assert client.post("/api/private", headers={"X-CSRF-Token": csrf}).status_code == 401


def test_registry_bootstraps_default_workspace_and_hashes_session_tokens():
    registry = DocumentRegistry(":memory:")
    workspace = registry.get_workspace("default")
    assert workspace and workspace["is_default"] is True

    stored = registry.create_session(
        token_hash="hash-only",
        csrf_token="csrf",
        user_id="owner",
        workspace_id="default",
        expires_at="2999-01-01T00:00:00.000000",
    )
    assert stored["token_hash"] == "hash-only"
    assert registry.get_session("raw-token") is None
    assert registry.get_session("hash-only")["workspace_id"] == "default"


def test_login_attempts_have_a_stricter_rate_limit():
    client, _ = _client()

    for _ in range(8):
        assert client.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
    blocked = client.post("/api/auth/login", json={"password": "wrong"})

    assert blocked.status_code == 429
    assert blocked.headers["retry-after"]
