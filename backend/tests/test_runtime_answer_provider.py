from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers import providers as providers_router_module
from app.middleware.request_guards import RequestGuardMiddleware
from app.services.answer_generator import TemplateAnswerGenerator
from app.services.auth import WorkspaceContext
from app.services.document_registry import DocumentRegistry
from app.models.domain import Chunk
from app.services.rag_engine import RagEngine
from app.services.runtime_answer_provider import (
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    RuntimeAnswerProviderConfigurationError,
    RuntimeAnswerProviderManager,
    RuntimeAnswerProviderValidationError,
)


class FakeDeepSeekClient:
    def __init__(self, *, result: str = "好", error: Exception | None = None, **kwargs):
        self.model = kwargs["model"]
        self.api_key = kwargs["api_key"]
        self.max_tokens = kwargs["max_tokens"]
        self.thinking_mode = kwargs["thinking_mode"]
        self.result = result
        self.error = error
        self.prompts: list[str] = []

    def create_text(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return self.result

    def stream_text(self, _prompt: str):
        yield "已连接"


def _successful_probe_client(
    requests: list[httpx.Request] | None = None,
) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [{"id": DEEPSEEK_MODEL, "object": "model"}],
            },
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_runtime_deepseek_connection_validates_before_atomic_swap_and_redacts_status():
    startup = TemplateAnswerGenerator()
    engine = SimpleNamespace(answer_generator=startup)
    clients: list[FakeDeepSeekClient] = []
    probe_requests: list[httpx.Request] = []

    def client_factory(**kwargs):
        client = FakeDeepSeekClient(**kwargs)
        clients.append(client)
        return client

    manager = RuntimeAnswerProviderManager(
        engine,
        timeout_seconds=45,
        max_tokens=512,
        client_factory=client_factory,
        probe_client=_successful_probe_client(probe_requests),
    )
    secret = "test-runtime-credential-value"

    status = manager.connect_deepseek(
        api_key=secret,
        base_url=DEEPSEEK_BASE_URL,
        model=DEEPSEEK_MODEL,
    )

    assert len(probe_requests) == 1
    assert probe_requests[0].method == "GET"
    assert probe_requests[0].url == f"{DEEPSEEK_BASE_URL}/models"
    assert probe_requests[0].headers["authorization"] == f"Bearer {secret}"
    assert len(clients) == 1
    assert clients[0].max_tokens == 512
    assert clients[0].thinking_mode == "disabled"
    assert engine.answer_generator is not startup
    assert engine.answer_generator.name == "deepseek_official"
    assert status == manager.status()
    assert status == {
        "provider": "deepseek_official",
        "configured": True,
        "health": "ready",
        "mode": "external",
        "capabilities": ["answer", "stream"],
        "model": DEEPSEEK_MODEL,
        "base_url": DEEPSEEK_BASE_URL,
        "runtime_override": True,
        "credential_state": "configured",
        "connected": True,
        "active": True,
        "temporary": True,
        "status": "ready",
        "health_basis": "validated_on_connect",
        "live_probe": "not_run_by_readiness",
    }
    assert secret not in repr(status)


def test_failed_deepseek_validation_keeps_the_previous_provider_and_hides_upstream_error():
    previous = TemplateAnswerGenerator()
    engine = SimpleNamespace(answer_generator=previous)
    secret = "test-runtime-credential-value"

    def rejecting_probe(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": f"provider rejected api_key={secret}"},
        )

    manager = RuntimeAnswerProviderManager(
        engine,
        client_factory=lambda **_kwargs: pytest.fail(
            "failed probes must not construct the active client"
        ),
        probe_client=httpx.Client(
            transport=httpx.MockTransport(rejecting_probe)
        ),
    )

    with pytest.raises(
        RuntimeAnswerProviderValidationError,
        match="无法验证 DeepSeek 凭据或服务可用性",
    ) as error:
        manager.connect_deepseek(
            api_key=secret,
            base_url=DEEPSEEK_BASE_URL,
            model=DEEPSEEK_MODEL,
        )

    assert engine.answer_generator is previous
    assert manager.status() is None
    assert secret not in str(error.value)
    assert error.value.__cause__ is None


@pytest.mark.parametrize(
    "payload",
    [
        {"object": "list", "data": []},
        {"object": "unexpected", "data": [{"id": DEEPSEEK_MODEL}]},
        ["not", "an", "object"],
    ],
)
def test_deepseek_probe_rejects_malformed_or_model_missing_responses(payload):
    previous = TemplateAnswerGenerator()
    manager = RuntimeAnswerProviderManager(
        SimpleNamespace(answer_generator=previous),
        client_factory=lambda **_kwargs: pytest.fail(
            "invalid probes must not construct the active client"
        ),
        probe_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, json=payload)
            )
        ),
    )

    with pytest.raises(RuntimeAnswerProviderValidationError):
        manager.connect_deepseek(api_key="test-runtime-credential-value")

    assert manager.status() is None


def test_deepseek_probe_never_follows_redirects():
    requests: list[httpx.Request] = []

    def redirecting_probe(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            307,
            headers={"location": "https://attacker.example/models"},
        )

    manager = RuntimeAnswerProviderManager(
        SimpleNamespace(
            answer_generator=TemplateAnswerGenerator()
        ),
        client_factory=lambda **_kwargs: pytest.fail(
            "redirected probes must not construct the active client"
        ),
        probe_client=httpx.Client(
            transport=httpx.MockTransport(redirecting_probe)
        ),
    )

    with pytest.raises(RuntimeAnswerProviderValidationError):
        manager.connect_deepseek(api_key="test-runtime-credential-value")

    assert len(requests) == 1
    assert requests[0].url.host == "api.deepseek.com"


@pytest.mark.parametrize(
    ("base_url", "model"),
    [
        ("https://attacker.example", DEEPSEEK_MODEL),
        (DEEPSEEK_BASE_URL, "deepseek-chat"),
        ("http://api.deepseek.com", DEEPSEEK_MODEL),
    ],
)
def test_runtime_provider_rejects_any_non_allowlisted_endpoint_or_model(
    base_url: str,
    model: str,
):
    startup = TemplateAnswerGenerator()
    engine = SimpleNamespace(answer_generator=startup)
    manager = RuntimeAnswerProviderManager(engine)

    with pytest.raises(RuntimeAnswerProviderConfigurationError):
        manager.connect_deepseek(
            api_key="test-runtime-credential-value",
            base_url=base_url,
            model=model,
        )

    assert engine.answer_generator is startup


def test_clear_discards_runtime_override_and_restores_startup_configuration():
    startup = TemplateAnswerGenerator()
    engine = SimpleNamespace(answer_generator=startup)
    manager = RuntimeAnswerProviderManager(
        engine,
        client_factory=lambda **kwargs: FakeDeepSeekClient(**kwargs),
        probe_client=_successful_probe_client(),
    )
    manager.connect_deepseek(
        api_key="test-runtime-credential-value",
        base_url=DEEPSEEK_BASE_URL,
        model=DEEPSEEK_MODEL,
    )

    assert manager.clear() is True
    assert engine.answer_generator is startup
    assert manager.status() is None
    assert manager.clear() is False


def _authenticated_provider_client(
    tmp_path,
    monkeypatch,
    manager: RuntimeAnswerProviderManager,
    *,
    auth_token: str = "",
    role: str = "owner",
) -> tuple[TestClient, str, DocumentRegistry]:
    registry = DocumentRegistry(str(tmp_path / "runtime-provider.sqlite3"))
    identity = WorkspaceContext(
        user_id="owner",
        workspace_id="default",
        role=role,
        csrf_token="csrf-test-token",
        session_hash="session-hash",
        expires_at="2999-01-01T00:00:00.000000",
    )

    class FakeAuthService:
        def resolve_cookie_header(self, cookie_header: str):
            return identity if "rag_session=valid-session" in cookie_header else None

        def verify_csrf(self, context: WorkspaceContext, supplied: str) -> bool:
            return context is identity and supplied == identity.csrf_token

    auth = FakeAuthService()
    monkeypatch.setattr(
        providers_router_module,
        "get_runtime_answer_provider",
        lambda: manager,
        raising=False,
    )
    app = FastAPI()
    app.include_router(providers_router_module.router, prefix="/api")
    app.add_middleware(
        RequestGuardMiddleware,
        auth_service=auth,
        auth_token=auth_token,
        rate_limit_requests=50,
        rate_limit_window_seconds=60,
    )
    client = TestClient(app)
    client.cookies.set("rag_session", "valid-session")
    return client, identity.csrf_token, registry


def test_runtime_provider_routes_require_owner_session_csrf_and_never_persist_secret(
    tmp_path,
    monkeypatch,
    caplog,
):
    startup = TemplateAnswerGenerator()
    engine = SimpleNamespace(answer_generator=startup)
    manager = RuntimeAnswerProviderManager(
        engine,
        max_tokens=256,
        client_factory=lambda **kwargs: FakeDeepSeekClient(**kwargs),
        probe_client=_successful_probe_client(),
    )
    client, csrf, registry = _authenticated_provider_client(
        tmp_path,
        monkeypatch,
        manager,
        auth_token="break-glass-token",
    )
    client.cookies.clear()
    payload = {
        "api_key": "test-runtime-credential-value",
    }

    bearer_only = client.post(
        "/api/providers/deepseek/runtime",
        headers={"Authorization": "Bearer break-glass-token"},
        json=payload,
    )
    assert bearer_only.status_code == 401

    client.cookies.set("rag_session", "valid-session")
    assert client.post(
        "/api/providers/deepseek/runtime",
        json=payload,
    ).status_code == 403

    response = client.post(
        "/api/providers/deepseek/runtime",
        headers={"X-CSRF-Token": csrf},
        json=payload,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["connection"]["connected"] is True
    assert response.json()["connection"]["model"] == DEEPSEEK_MODEL
    assert "test-runtime-credential-value" not in response.text
    assert "api_key" not in response.text.lower()

    status = client.get("/api/providers/status")
    assert status.status_code == 200
    assert status.json()["providers"]["answer"]["runtime_override"] is True
    assert "test-runtime-credential-value" not in status.text

    deleted = client.delete(
        "/api/providers/deepseek/runtime",
        headers={"X-CSRF-Token": csrf},
    )
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "cleared"
    assert deleted.json()["connection"]["connected"] is False
    assert engine.answer_generator is startup

    registry.close()
    database_bytes = (tmp_path / "runtime-provider.sqlite3").read_bytes()
    assert b"test-runtime-credential-value" not in database_bytes
    assert "test-runtime-credential-value" not in caplog.text


def test_runtime_provider_route_rejects_failed_validation_without_replacing_current_provider(
    tmp_path,
    monkeypatch,
):
    previous = TemplateAnswerGenerator()
    engine = SimpleNamespace(answer_generator=previous)
    secret = "test-runtime-credential-value"

    def rejecting_probe(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={
                "error": (
                    f"upstream rejected Authorization: Bearer {secret}"
                )
            },
        )

    manager = RuntimeAnswerProviderManager(
        engine,
        client_factory=lambda **_kwargs: pytest.fail(
            "failed probes must not construct the active client"
        ),
        probe_client=httpx.Client(
            transport=httpx.MockTransport(rejecting_probe)
        ),
    )
    client, csrf, registry = _authenticated_provider_client(
        tmp_path,
        monkeypatch,
        manager,
    )

    response = client.post(
        "/api/providers/deepseek/runtime",
        headers={"X-CSRF-Token": csrf},
        json={
            "api_key": secret,
        },
    )

    assert response.status_code == 502
    assert response.json() == {
        "detail": "DeepSeek 连接验证失败，请检查凭据或服务状态后重试。"
    }
    assert secret not in response.text
    assert "Authorization" not in response.text
    assert engine.answer_generator is previous
    assert manager.status() is None
    registry.close()


def test_provider_status_recognizes_startup_deepseek_without_exposing_credential(
    monkeypatch,
):
    from app.config import settings

    manager = RuntimeAnswerProviderManager(
        SimpleNamespace(
            answer_generator=TemplateAnswerGenerator()
        )
    )
    monkeypatch.setattr(
        providers_router_module,
        "get_runtime_answer_provider",
        lambda: manager,
    )
    monkeypatch.setattr(
        settings,
        "answer_provider",
        "openai_compatible_chat",
    )
    monkeypatch.setattr(
        settings,
        "answer_base_url",
        DEEPSEEK_BASE_URL,
    )
    monkeypatch.setattr(settings, "answer_model", DEEPSEEK_MODEL)
    monkeypatch.setattr(
        settings,
        "answer_api_key",
        "test-startup-credential-value",
    )

    status = providers_router_module.provider_status()

    answer = status["providers"]["answer"]
    assert answer["provider"] == "deepseek_official"
    assert answer["configured"] is True
    assert answer["model"] == DEEPSEEK_MODEL
    assert answer["base_url"] == DEEPSEEK_BASE_URL
    assert status["runtime"]["deepseek"]["connected"] is True
    assert status["runtime"]["deepseek"]["temporary"] is False
    assert "test-startup-credential-value" not in repr(status)
    assert "api_key" not in repr(status).lower()


def test_production_provider_status_is_read_only_and_runtime_credentials_are_rejected(
    tmp_path,
    monkeypatch,
):
    from app.config import settings

    manager = RuntimeAnswerProviderManager(
        SimpleNamespace(answer_generator=TemplateAnswerGenerator()),
        client_factory=lambda **kwargs: FakeDeepSeekClient(**kwargs),
        probe_client=_successful_probe_client(),
    )
    client, csrf, registry = _authenticated_provider_client(
        tmp_path,
        monkeypatch,
        manager,
    )
    monkeypatch.setattr(settings, "app_environment", "production")

    status = client.get("/api/providers/status")
    assert status.status_code == 200
    assert status.json()["runtime_configuration_allowed"] is False

    response = client.post(
        "/api/providers/deepseek/runtime",
        headers={"X-CSRF-Token": csrf},
        json={"api_key": "test-runtime-credential-value"},
    )
    assert response.status_code == 403
    assert "Docker secrets" in response.json()["detail"]
    assert manager.status() is None
    registry.close()


def test_startup_deepseek_is_not_configured_without_a_key(
    monkeypatch,
):
    from app.config import settings

    manager = RuntimeAnswerProviderManager(
        SimpleNamespace(
            answer_generator=TemplateAnswerGenerator()
        )
    )
    monkeypatch.setattr(
        providers_router_module,
        "get_runtime_answer_provider",
        lambda: manager,
    )
    monkeypatch.setattr(
        settings,
        "answer_provider",
        "openai_compatible_chat",
    )
    monkeypatch.setattr(
        settings,
        "answer_base_url",
        DEEPSEEK_BASE_URL,
    )
    monkeypatch.setattr(settings, "answer_model", DEEPSEEK_MODEL)
    monkeypatch.setattr(settings, "answer_api_key", "")

    status = providers_router_module.provider_status()

    assert status["providers"]["answer"]["configured"] is False
    assert status["runtime"]["deepseek"]["connected"] is False


def test_provider_status_strips_credentials_and_query_from_external_base_url(
    monkeypatch,
):
    from app.config import settings

    manager = RuntimeAnswerProviderManager(
        SimpleNamespace(
            answer_generator=TemplateAnswerGenerator()
        )
    )
    monkeypatch.setattr(
        providers_router_module,
        "get_runtime_answer_provider",
        lambda: manager,
    )
    monkeypatch.setattr(
        settings,
        "answer_provider",
        "openai_compatible_chat",
    )
    monkeypatch.setattr(
        settings,
        "answer_base_url",
        "https://user:password@provider.example/v1?token=secret",
    )
    monkeypatch.setattr(settings, "answer_model", "private-model")

    status = providers_router_module.provider_status()

    answer = status["providers"]["answer"]
    assert answer["base_url"] == "https://provider.example/v1"
    assert "password" not in repr(status)
    assert "token=secret" not in repr(status)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "api_key": "test-runtime-credential-value",
            "base_url": "https://attacker.example",
            "model": DEEPSEEK_MODEL,
        },
        {
            "api_key": "test-runtime-credential-value",
            "base_url": DEEPSEEK_BASE_URL,
            "model": "deepseek-chat",
        },
        {
            "api_key": "tiny",
        },
    ],
)
def test_runtime_provider_route_schema_only_accepts_the_official_target(
    payload,
    tmp_path,
    monkeypatch,
):
    engine = SimpleNamespace(
        answer_generator=TemplateAnswerGenerator()
    )
    manager = RuntimeAnswerProviderManager(
        engine,
        client_factory=lambda **kwargs: FakeDeepSeekClient(**kwargs),
        probe_client=_successful_probe_client(),
    )
    client, csrf, registry = _authenticated_provider_client(
        tmp_path,
        monkeypatch,
        manager,
    )

    response = client.post(
        "/api/providers/deepseek/runtime",
        headers={"X-CSRF-Token": csrf},
        json=payload,
    )

    assert response.status_code == 422
    assert str(payload["api_key"]) not in response.text
    assert manager.status() is None
    registry.close()


def test_runtime_provider_write_is_forbidden_when_session_auth_is_disabled(
    monkeypatch,
):
    manager = RuntimeAnswerProviderManager(
        SimpleNamespace(
            answer_generator=TemplateAnswerGenerator()
        ),
        client_factory=lambda **kwargs: FakeDeepSeekClient(**kwargs),
        probe_client=_successful_probe_client(),
    )
    monkeypatch.setattr(
        providers_router_module,
        "get_runtime_answer_provider",
        lambda: manager,
    )
    app = FastAPI()
    app.include_router(providers_router_module.router, prefix="/api")
    app.add_middleware(
        RequestGuardMiddleware,
        auth_service=None,
        auth_token="",
        rate_limit_requests=50,
    )

    response = TestClient(app).post(
        "/api/providers/deepseek/runtime",
        json={"api_key": "test-runtime-credential-value"},
    )

    assert response.status_code == 403
    assert response.json() == {
        "detail": (
            "必须使用管理员会话才能修改回答 Provider，"
            "匿名或只读会话无权执行此操作。"
        )
    }
    assert manager.status() is None


def test_application_validation_errors_never_echo_malformed_key_input():
    from app.main import app

    secret = "test-malformed-credential-value"
    with TestClient(app) as client:
        response = client.post(
            "/api/providers/deepseek/runtime",
            json={"api_key": [secret]},
        )

    assert response.status_code == 422
    assert secret not in response.text
    assert all(
        "input" not in issue
        for issue in response.json()["detail"]
    )


@pytest.mark.parametrize(
    ("role", "expected_status"),
    [("admin", 200), ("viewer", 403)],
)
def test_runtime_provider_write_is_limited_to_owner_or_admin_roles(
    role,
    expected_status,
    tmp_path,
    monkeypatch,
):
    manager = RuntimeAnswerProviderManager(
        SimpleNamespace(
            answer_generator=TemplateAnswerGenerator()
        ),
        client_factory=lambda **kwargs: FakeDeepSeekClient(**kwargs),
        probe_client=_successful_probe_client(),
    )
    client, csrf, registry = _authenticated_provider_client(
        tmp_path,
        monkeypatch,
        manager,
        role=role,
    )

    response = client.post(
        "/api/providers/deepseek/runtime",
        headers={"X-CSRF-Token": csrf},
        json={"api_key": "test-runtime-credential-value"},
    )

    assert response.status_code == expected_status
    assert (manager.status() is not None) is (expected_status == 200)
    registry.close()


def test_inflight_stream_keeps_the_provider_snapshot_during_runtime_switch():
    chunk = Chunk(
        chunk_id="chunk-1",
        document_id="doc-1",
        chunk_index=0,
        text="可核验证据",
        file_name="evidence.md",
    )

    class FakeRetriever:
        embedding_provider = object()
        vector_store = SimpleNamespace(chunks={chunk.id: chunk})

        def search(self, *_args, **_kwargs):
            return (
                [
                    {
                        "chunk": chunk,
                        "score": 0.9,
                        "bm25_score": 0.9,
                        "vector_score": 0.8,
                        "rerank_score": 0.9,
                        "matched_terms": ["证据"],
                    }
                ],
                {
                    "available_chunks": 1,
                    "pipeline": {},
                    "fallbacks": [],
                },
            )

    replacement = FakeDeepSeekClient(
        model=DEEPSEEK_MODEL,
        api_key="replacement",
        max_tokens=16,
        thinking_mode="disabled",
    )

    class ReplacementGenerator(TemplateAnswerGenerator):
        name = "replacement"

        def __init__(self):
            self.client = replacement

    class SwitchingGenerator(TemplateAnswerGenerator):
        name = "snapshot"

        def __init__(self):
            self.client = SimpleNamespace(model="snapshot-model")
            self.engine = None

        def stream(self, _question, _citations, _trace):
            yield "答案[1]"
            self.engine.answer_generator = ReplacementGenerator()
            yield "仍由原连接完成"

    original = SwitchingGenerator()
    engine = RagEngine(
        FakeRetriever(),
        answer_generator=original,
        allow_generation_fallback=False,
    )
    original.engine = engine

    events = list(engine.stream("请回答", query_rewrite=False))
    completed = next(
        event for event in events if event["type"] == "answer.completed"
    )

    assert completed["response"]["generation_trace"]["answer_provider"] == "snapshot"
    assert completed["response"]["generation_trace"]["answer_model"] == "snapshot-model"
    assert engine.answer_generator.name == "replacement"
