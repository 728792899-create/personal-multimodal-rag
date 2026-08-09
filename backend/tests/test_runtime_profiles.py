from __future__ import annotations

from dataclasses import replace

import pytest

from app.config import Settings
from app.services.runtime_readiness import (
    build_readiness_report,
    collect_runtime_checks,
    probe_provider_health,
    validate_runtime_settings,
)


def test_demo_profile_remains_zero_key_and_ready():
    settings = Settings()
    report = build_readiness_report(settings)

    assert report["mode"] == "demo"
    assert report["ready"] is True
    assert report["components"]["metadata"]["provider"] == "sqlite"


def test_local_production_rejects_mock_and_template():
    settings = replace(Settings(), runtime_mode="local-production")

    with pytest.raises(ValueError, match="EMBEDDING_PROVIDER"):
        validate_runtime_settings(settings)


def test_production_profile_fails_closed_without_durable_adapters():
    settings = replace(
        Settings(),
        runtime_mode="production",
        provider_fallback_allowed=False,
        embedding_provider="ollama",
        answer_provider="ollama",
    )

    with pytest.raises(ValueError) as exc:
        validate_runtime_settings(settings)

    message = str(exc.value)
    assert "METADATA_BACKEND=postgres" in message
    assert "OBJECT_STORE_BACKEND=s3" in message
    assert "JOB_QUEUE_BACKEND=redis" in message
    assert "AUTH_MODE=session" in message
    assert "FETCH_WORKER_URL" in message


def test_production_profile_accepts_complete_configuration():
    settings = replace(
        Settings(),
        runtime_mode="production",
        provider_fallback_allowed=False,
        embedding_provider="ollama",
        answer_provider="ollama",
        vector_store="pgvector",
        metadata_backend="postgres",
        metadata_dsn="postgresql://rag:secret@postgres/rag",
        pgvector_dsn="postgresql://rag:secret@postgres/rag",
        object_store_backend="s3",
        s3_endpoint_url="http://minio:9000",
        s3_bucket="rag-objects",
        s3_access_key="rag",
        s3_secret_key="secret",
        job_queue_backend="redis",
        redis_url="redis://redis:6379/0",
        auth_mode="session",
        admin_password_hash="$argon2id$valid-for-shape-check",
        session_secret="a" * 32,
        fetch_worker_url="http://fetch-worker:8091",
    )

    validate_runtime_settings(settings)
    report = build_readiness_report(settings)
    assert report["ready"] is True
    assert report["components"]["queue"]["provider"] == "redis"


def test_component_failure_makes_readiness_fail_closed():
    report = build_readiness_report(
        Settings(),
        checks={"metadata": True, "object_store": False},
    )

    assert report["ready"] is False
    assert report["components"]["object_store"]["healthy"] is False


def test_startup_answer_status_uses_the_public_provider_identity():
    settings = replace(
        Settings(),
        answer_provider="openai_compatible_chat",
        answer_base_url="https://api.deepseek.com",
        answer_model="deepseek-v4-flash",
        answer_api_key="configured-for-contract-test",
    )
    report = build_readiness_report(
        settings,
        answer_status={
            "provider": "deepseek_official",
            "configured": True,
            "runtime_override": False,
        },
    )

    assert report["answer_provider"] == {
        "current": "deepseek_official",
        "startup": "openai_compatible_chat",
        "runtime_override": False,
    }
    assert report["components"]["answer"]["provider"] == "deepseek_official"


def test_demo_runtime_checks_never_probe_external_provider(monkeypatch):
    class Healthy:
        def health(self):
            return True

    def unexpected_probe(*_args, **_kwargs):
        raise AssertionError("demo readiness must not probe external providers")

    monkeypatch.setattr(
        "app.services.runtime_readiness.probe_provider_health",
        unexpected_probe,
    )
    checks = collect_runtime_checks(
        Settings(),
        registry=Healthy(),
        object_store=Healthy(),
        queue=None,
        vector_store=Healthy(),
    )

    assert checks == {
        "metadata": True,
        "object_store": True,
        "queue": True,
        "vector": True,
    }


def test_ollama_readiness_probe_is_non_generating_and_deduplicated(monkeypatch):
    calls: list[str] = []

    class Response:
        status_code = 200

        def json(self):
            return {
                "models": [
                    {"name": "qwen3:8b"},
                    {"name": "nomic-embed-text:latest"},
                ]
            }

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, url, headers):
            calls.append(url)
            assert headers == {}
            return Response()

    monkeypatch.setattr("app.services.runtime_readiness.httpx.Client", Client)
    settings = replace(
        Settings(),
        runtime_mode="local-production",
        answer_provider="ollama",
        embedding_provider="ollama",
        ollama_base_url="http://ollama:11434",
    )

    assert probe_provider_health(settings) == {"answer": True, "embedding": True}
    assert calls == ["http://ollama:11434/api/tags"]


def test_runtime_answer_override_is_current_provider_and_skips_startup_probe(
    monkeypatch,
):
    class Healthy:
        def health(self):
            return True

    probe_calls: list[bool] = []

    def embedding_only_probe(_settings, *, probe_answer=True, **_kwargs):
        probe_calls.append(probe_answer)
        return {"embedding": True}

    monkeypatch.setattr(
        "app.services.runtime_readiness.probe_provider_health",
        embedding_only_probe,
    )
    settings = replace(
        Settings(),
        runtime_mode="local-production",
        answer_provider="ollama",
        embedding_provider="ollama",
        vector_store="chroma",
        provider_fallback_allowed=False,
    )
    active = {
        "provider": "deepseek_official",
        "configured": True,
        "health": "ready",
        "connected": True,
        "active": True,
        "runtime_override": True,
        "credential": "must-not-be-exported",
    }

    checks = collect_runtime_checks(
        settings,
        registry=Healthy(),
        object_store=Healthy(),
        queue=None,
        vector_store=Healthy(),
        answer_status=active,
    )
    report = build_readiness_report(
        settings,
        checks=checks,
        answer_status=active,
    )

    assert probe_calls == [False]
    assert checks["answer"] is True
    assert report["ready"] is True
    assert report["answer_provider"] == {
        "current": "deepseek_official",
        "startup": "ollama",
        "runtime_override": True,
    }
    assert report["components"]["answer"] == {
        "provider": "deepseek_official",
        "configured": True,
        "runtime_override": True,
        "startup_provider": "ollama",
        "active": True,
        "health_basis": "validated_on_connect",
        "live_probe": "not_run",
        "healthy": True,
    }
    assert "must-not-be-exported" not in repr(report)


def test_unhealthy_runtime_answer_override_fails_readiness_without_fallback_probe(
    monkeypatch,
):
    class Healthy:
        def health(self):
            return True

    monkeypatch.setattr(
        "app.services.runtime_readiness.probe_provider_health",
        lambda *_args, **_kwargs: {"embedding": True},
    )
    settings = replace(
        Settings(),
        runtime_mode="local-production",
        answer_provider="ollama",
        embedding_provider="ollama",
        vector_store="chroma",
        provider_fallback_allowed=False,
    )
    active = {
        "provider": "deepseek_official",
        "configured": True,
        "health": "unavailable",
        "connected": True,
        "active": True,
        "runtime_override": True,
    }

    checks = collect_runtime_checks(
        settings,
        registry=Healthy(),
        object_store=Healthy(),
        queue=None,
        vector_store=Healthy(),
        answer_status=active,
    )
    report = build_readiness_report(
        settings,
        checks=checks,
        answer_status=active,
    )

    assert checks["answer"] is False
    assert report["ready"] is False
    assert report["components"]["answer"]["provider"] == "deepseek_official"
    assert report["components"]["answer"]["healthy"] is False
