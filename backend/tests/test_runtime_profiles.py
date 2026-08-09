from __future__ import annotations

from dataclasses import replace
import importlib.util
from pathlib import Path

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
        app_environment="production",
        provider_fallback_allowed=False,
        embedding_provider="openai",
        embedding_model="text-embedding-3-large",
        embedding_dimension=1536,
        openai_api_key="openai-contract-key",
        answer_provider="openai_compatible_chat",
        answer_base_url="https://api.deepseek.com",
        answer_api_key="deepseek-contract-key",
        reranker="deepseek",
        retrieval_aux_provider="deepseek",
        retrieval_aux_base_url="https://api.deepseek.com",
        retrieval_aux_model="deepseek-v4-flash",
        retrieval_aux_api_key="deepseek-contract-key",
        query_rewrite_provider="deepseek",
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


@pytest.mark.parametrize(
    "base_url",
    [
        "http://127.0.0.1:8000/v1",
        "https://openai.example/v1",
        "https://api.openai.com.evil.example/v1",
        "https://api.openai.com/v1?proxy=1",
    ],
)
def test_production_rejects_non_official_openai_embedding_endpoint(base_url):
    settings = replace(
        Settings(),
        runtime_mode="production",
        app_environment="production",
        provider_fallback_allowed=False,
        embedding_provider="openai",
        embedding_model="text-embedding-3-large",
        embedding_dimension=1536,
        openai_base_url=base_url,
    )

    with pytest.raises(ValueError, match="api.openai.com"):
        validate_runtime_settings(settings)


@pytest.mark.parametrize(
    "base_url",
    ["", "https://api.openai.com", "https://api.openai.com/v1/", "https://api.openai.com:443/v1"],
)
def test_production_accepts_only_default_or_official_openai_embedding_endpoint(base_url):
    settings = replace(
        Settings(),
        runtime_mode="production",
        app_environment="production",
        provider_fallback_allowed=False,
        embedding_provider="openai",
        embedding_model="text-embedding-3-large",
        embedding_dimension=1536,
        openai_base_url=base_url,
        answer_provider="openai_compatible_chat",
        answer_base_url="https://api.deepseek.com",
        reranker="deepseek",
        retrieval_aux_provider="deepseek",
        retrieval_aux_base_url="https://api.deepseek.com",
        retrieval_aux_api_key="deepseek-contract-key",
        query_rewrite_provider="deepseek",
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


def test_index_worker_validates_the_production_contract_before_starting():
    worker_path = Path(__file__).resolve().parents[2] / "scripts" / "run_index_worker.py"
    spec = importlib.util.spec_from_file_location("rag_index_worker_contract_test", worker_path)
    assert spec is not None and spec.loader is not None
    worker_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker_module)
    worker_module.settings = replace(
        Settings(),
        runtime_mode="production",
        app_environment="production",
        provider_fallback_allowed=False,
        embedding_provider="openai",
        embedding_model="text-embedding-3-large",
        embedding_dimension=1536,
        openai_base_url="http://127.0.0.1:8000/v1",
    )

    with pytest.raises(ValueError, match="api.openai.com"):
        worker_module.main()


def test_production_profile_requires_production_app_environment():
    settings = replace(
        Settings(),
        runtime_mode="production",
        app_environment="staging",
        provider_fallback_allowed=False,
    )

    with pytest.raises(ValueError, match="APP_ENVIRONMENT=production"):
        validate_runtime_settings(settings)


def test_session_auth_rejects_legacy_bearer_bypass_in_every_runtime_mode():
    settings = replace(
        Settings(),
        runtime_mode="demo",
        auth_mode="session",
        api_auth_token="legacy-break-glass-token",
    )

    with pytest.raises(ValueError, match="API_AUTH_TOKEN"):
        validate_runtime_settings(settings)


def test_production_image_installs_the_openai_embedding_sdk():
    requirements = (
        Path(__file__).resolve().parents[1] / "requirements-production.txt"
    ).read_text(encoding="utf-8")

    assert any(
        line.strip().startswith("openai==")
        for line in requirements.splitlines()
    )
    local_requirements = (
        Path(__file__).resolve().parents[1]
        / "requirements-local-production.txt"
    ).read_text(encoding="utf-8")
    assert "openai==" in local_requirements
    assert "sentence-transformers" not in local_requirements


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
