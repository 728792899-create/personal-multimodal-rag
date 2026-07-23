from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.request_guards import RequestGuardMiddleware


def guarded_app(**kwargs) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestGuardMiddleware, **kwargs)

    @app.get("/api/value")
    def value():
        return {"ok": True}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


def test_optional_bearer_auth_protects_api_but_not_health():
    client = TestClient(guarded_app(auth_token="secret", rate_limit_requests=20, rate_limit_window_seconds=60))

    assert client.get("/health").status_code == 200
    assert client.get("/api/value").status_code == 401
    assert client.get("/api/value", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/value", headers={"Authorization": "Bearer secret"}).status_code == 200


def test_rate_limit_returns_retry_after_and_request_id():
    client = TestClient(guarded_app(auth_token="", rate_limit_requests=2, rate_limit_window_seconds=60))

    first = client.get("/api/value")
    second = client.get("/api/value")
    limited = client.get("/api/value")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.headers["x-request-id"]
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) >= 1
    assert limited.json()["detail"] == "Rate limit exceeded"
