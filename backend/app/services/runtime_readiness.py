from __future__ import annotations

from urllib.parse import urljoin

import httpx

from app.config import Settings


_REAL_EMBEDDINGS = {
    "local",
    "sentence-transformers",
    "sentence_transformers",
    "huggingface",
    "openai",
    "openai-compatible",
    "ollama",
}
_REAL_ANSWERS = {
    "responses",
    "openai-responses",
    "openai_responses",
    "openai-compatible-chat",
    "openai_compatible_chat",
    "ollama",
}


def validate_runtime_settings(settings: Settings) -> None:
    mode = settings.runtime_mode.strip().lower()
    if mode not in {"demo", "local-production", "production"}:
        raise ValueError("RAG_RUNTIME_MODE 必须是 demo、local-production 或 production")
    if mode == "demo":
        return

    errors: list[str] = []
    if settings.embedding_provider.lower() not in _REAL_EMBEDDINGS:
        errors.append("EMBEDDING_PROVIDER 必须选择真实的 embedding Provider")
    if settings.answer_provider.lower() not in _REAL_ANSWERS:
        errors.append("ANSWER_PROVIDER 必须选择真实的回答 Provider")
    if settings.provider_fallback_allowed:
        errors.append("非 demo 模式必须设置 PROVIDER_FALLBACK_ALLOWED=0")
    if settings.auth_mode.lower() == "session":
        if not settings.admin_password_hash.startswith("$argon2"):
            errors.append("ADMIN_PASSWORD_HASH 必须包含 Argon2id hash")
        if len(settings.session_secret) < 32:
            errors.append("SESSION_SECRET 至少需要 32 个字符")

    if mode == "local-production":
        if settings.vector_store.lower() not in {"chroma", "pgvector"}:
            errors.append("local-production 模式的 VECTOR_STORE 必须是 chroma 或 pgvector")
    else:
        if settings.metadata_backend.lower() != "postgres" or not settings.metadata_dsn:
            errors.append("必须配置 METADATA_BACKEND=postgres 和 METADATA_DSN")
        if settings.vector_store.lower() != "pgvector" or not settings.pgvector_dsn:
            errors.append("必须配置 VECTOR_STORE=pgvector 和 PGVECTOR_DSN")
        if settings.object_store_backend.lower() != "s3":
            errors.append("必须配置 OBJECT_STORE_BACKEND=s3")
        if not all(
            [
                settings.s3_endpoint_url,
                settings.s3_bucket,
                settings.s3_access_key,
                settings.s3_secret_key,
            ]
        ):
            errors.append("必须配置 S3 endpoint、bucket、access key 和 secret key")
        if settings.job_queue_backend.lower() != "redis" or not settings.redis_url:
            errors.append("必须配置 JOB_QUEUE_BACKEND=redis 和 REDIS_URL")
        if settings.auth_mode.lower() != "session":
            errors.append("必须配置 AUTH_MODE=session")
        if not settings.fetch_worker_url:
            errors.append("必须配置 FETCH_WORKER_URL，以隔离 production URL 抓取")

    if errors:
        raise ValueError("; ".join(errors))


def _active_runtime_answer(answer_status: dict | None) -> dict | None:
    if not isinstance(answer_status, dict):
        return None
    if (
        answer_status.get("runtime_override") is True
        and answer_status.get("active") is True
    ):
        return answer_status
    return None


def build_readiness_report(
    settings: Settings,
    *,
    checks: dict | None = None,
    answer_status: dict | None = None,
) -> dict:
    configured = True
    errors: list[str] = []
    try:
        validate_runtime_settings(settings)
    except ValueError as exc:
        configured = False
        errors = [item.strip() for item in str(exc).split(";") if item.strip()]

    startup_provider = settings.answer_provider.lower()
    reported_provider = startup_provider
    reported_configured = (
        startup_provider in {"template", "local", "none"}
        or bool(
            settings.answer_api_key
            or settings.answer_base_url
            or settings.ollama_base_url
        )
    )
    if isinstance(answer_status, dict):
        candidate_provider = str(answer_status.get("provider") or "").strip()
        if candidate_provider:
            reported_provider = candidate_provider[:80]
        if isinstance(answer_status.get("configured"), bool):
            reported_configured = answer_status["configured"]

    active_runtime_answer = _active_runtime_answer(answer_status)
    answer_component = {
        "provider": reported_provider,
        "configured": reported_configured,
        "runtime_override": False,
        "startup_provider": startup_provider,
    }
    if active_runtime_answer is not None:
        answer_component = {
            "provider": str(
                active_runtime_answer.get("provider") or "unknown"
            )[:80],
            "configured": active_runtime_answer.get("configured") is True,
            "runtime_override": True,
            "startup_provider": startup_provider,
            "active": True,
            # The runtime credential was checked once before the atomic swap.
            # Readiness reports that basis explicitly and performs no billable
            # generation or repeated credential-bearing external request.
            "health_basis": "validated_on_connect",
            "live_probe": "not_run",
        }

    components = {
        "metadata": {
            "provider": settings.metadata_backend.lower(),
            "configured": settings.metadata_backend.lower() == "sqlite" or bool(settings.metadata_dsn),
        },
        "object_store": {
            "provider": settings.object_store_backend.lower(),
            "configured": settings.object_store_backend.lower() == "local"
            or bool(settings.s3_endpoint_url and settings.s3_bucket),
        },
        "queue": {
            "provider": settings.job_queue_backend.lower(),
            "configured": settings.job_queue_backend.lower() == "sqlite" or bool(settings.redis_url),
        },
        "auth": {
            "provider": settings.auth_mode.lower(),
            "configured": settings.auth_mode.lower() == "disabled"
            or bool(settings.admin_password_hash and settings.session_secret),
        },
        "vector": {
            "provider": settings.vector_store.lower(),
            "configured": settings.vector_store.lower() != "pgvector" or bool(settings.pgvector_dsn),
        },
        "answer": answer_component,
        "embedding": {
            "provider": settings.embedding_provider.lower(),
            "configured": settings.embedding_provider.lower()
            in {"mock", "local", "sentence-transformers", "sentence_transformers", "huggingface"}
            or bool(settings.openai_api_key or settings.openai_base_url or settings.ollama_base_url),
        },
        "fetch_worker": {
            "provider": "isolated" if settings.fetch_worker_url else "in-process",
            "configured": settings.runtime_mode.lower() != "production" or bool(settings.fetch_worker_url),
        },
    }
    for name, value in (checks or {}).items():
        if name in components:
            components[name]["healthy"] = bool(value)

    health_ready = all(
        component.get("healthy", component["configured"]) for component in components.values()
    )
    return {
        "mode": settings.runtime_mode.lower(),
        "ready": configured and health_ready,
        "configured": configured,
        "answer_provider": {
            "current": answer_component["provider"],
            "startup": startup_provider,
            "runtime_override": answer_component["runtime_override"],
        },
        "components": components,
        "errors": errors,
    }


def probe_provider_health(
    settings: Settings,
    *,
    timeout_seconds: float = 2.0,
    probe_answer: bool = True,
) -> dict[str, bool]:
    """Perform non-generating provider probes for production readiness.

    The probes never submit prompts or embedding inputs, so readiness checks
    cannot create billable model requests.
    """

    results = {"embedding": True}
    if probe_answer:
        results["answer"] = True
    endpoints: dict[str, tuple[str, dict[str, str], str]] = {}

    def register(
        name: str,
        provider: str,
        base_url: str,
        api_key: str = "",
        model: str = "",
    ) -> None:
        normalized = provider.lower().replace("_", "-")
        if normalized in {"template", "local", "none", "mock", "sentence-transformers", "huggingface"}:
            return
        if normalized == "ollama":
            endpoints[name] = (
                urljoin(base_url.rstrip("/") + "/", "api/tags"),
                {},
                model,
            )
            return
        if normalized in {
            "responses",
            "openai-responses",
            "openai",
            "openai-compatible",
            "openai-compatible-chat",
        }:
            root = base_url or "https://api.openai.com/v1"
            endpoints[name] = (
                urljoin(root.rstrip("/") + "/", "models"),
                {"Authorization": f"Bearer {api_key}"} if api_key else {},
                "",
            )

    if probe_answer:
        register(
            "answer",
            settings.answer_provider,
            settings.ollama_base_url
            if settings.answer_provider.lower() == "ollama"
            else settings.answer_base_url,
            settings.answer_api_key,
            settings.ollama_chat_model
            if settings.answer_provider.lower() == "ollama"
            else settings.answer_model,
        )
    register(
        "embedding",
        settings.embedding_provider,
        settings.ollama_base_url if settings.embedding_provider.lower() == "ollama" else settings.openai_base_url,
        settings.openai_api_key,
        settings.ollama_embedding_model if settings.embedding_provider.lower() == "ollama" else settings.embedding_model,
    )

    with httpx.Client(timeout=timeout_seconds, follow_redirects=False) as client:
        cache: dict[tuple[str, tuple[tuple[str, str], ...]], httpx.Response | None] = {}
        for name, (url, headers, required_model) in endpoints.items():
            cache_key = (url, tuple(sorted(headers.items())))
            if cache_key not in cache:
                try:
                    cache[cache_key] = client.get(url, headers=headers)
                except httpx.HTTPError:
                    cache[cache_key] = None
            response = cache[cache_key]
            healthy = bool(
                response
                and response.status_code < 500
                and response.status_code not in {401, 403}
            )
            if healthy and url.endswith("/api/tags") and required_model:
                try:
                    models = response.json().get("models", [])
                    available = {
                        str(item.get("name") or item.get("model") or "")
                        for item in models
                        if isinstance(item, dict)
                    }
                    healthy = required_model in available or any(
                        item.split(":", 1)[0] == required_model.split(":", 1)[0]
                        for item in available
                    )
                except (TypeError, ValueError, AttributeError):
                    healthy = False
            results[name] = healthy
    return results


def collect_runtime_checks(
    settings: Settings,
    *,
    registry,
    object_store,
    queue,
    vector_store,
    fetch_worker=None,
    answer_status: dict | None = None,
) -> dict[str, bool]:
    def safe(callable_) -> bool:
        try:
            return bool(callable_())
        except Exception:
            return False

    checks = {
        "metadata": safe(registry.health),
        "object_store": safe(object_store.health),
        "queue": safe(queue.health) if queue is not None else settings.job_queue_backend.lower() == "sqlite",
        "vector": safe(vector_store.health),
    }
    if settings.runtime_mode.lower() == "production":
        checks["fetch_worker"] = safe(fetch_worker.health) if fetch_worker is not None else False
    if settings.runtime_mode.lower() != "demo":
        active_runtime_answer = _active_runtime_answer(answer_status)
        if active_runtime_answer is not None:
            checks["answer"] = bool(
                active_runtime_answer.get("configured") is True
                and active_runtime_answer.get("connected") is True
                and active_runtime_answer.get("health") == "ready"
            )
        checks.update(
            probe_provider_health(
                settings,
                probe_answer=active_runtime_answer is None,
            )
        )
    return checks
