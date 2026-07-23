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
        raise ValueError("RAG_RUNTIME_MODE must be demo, local-production, or production")
    if mode == "demo":
        return

    errors: list[str] = []
    if settings.embedding_provider.lower() not in _REAL_EMBEDDINGS:
        errors.append("EMBEDDING_PROVIDER must select a real embedding provider")
    if settings.answer_provider.lower() not in _REAL_ANSWERS:
        errors.append("ANSWER_PROVIDER must select a real answer provider")
    if settings.provider_fallback_allowed:
        errors.append("PROVIDER_FALLBACK_ALLOWED=0 is required outside demo mode")
    if settings.auth_mode.lower() == "session":
        if not settings.admin_password_hash.startswith("$argon2"):
            errors.append("ADMIN_PASSWORD_HASH must contain an Argon2id hash")
        if len(settings.session_secret) < 32:
            errors.append("SESSION_SECRET must be at least 32 characters")

    if mode == "local-production":
        if settings.vector_store.lower() not in {"chroma", "pgvector"}:
            errors.append("VECTOR_STORE must be chroma or pgvector in local-production")
    else:
        if settings.metadata_backend.lower() != "postgres" or not settings.metadata_dsn:
            errors.append("METADATA_BACKEND=postgres and METADATA_DSN are required")
        if settings.vector_store.lower() != "pgvector" or not settings.pgvector_dsn:
            errors.append("VECTOR_STORE=pgvector and PGVECTOR_DSN are required")
        if settings.object_store_backend.lower() != "s3":
            errors.append("OBJECT_STORE_BACKEND=s3 is required")
        if not all(
            [
                settings.s3_endpoint_url,
                settings.s3_bucket,
                settings.s3_access_key,
                settings.s3_secret_key,
            ]
        ):
            errors.append("S3 endpoint, bucket, access key, and secret key are required")
        if settings.job_queue_backend.lower() != "redis" or not settings.redis_url:
            errors.append("JOB_QUEUE_BACKEND=redis and REDIS_URL are required")
        if settings.auth_mode.lower() != "session":
            errors.append("AUTH_MODE=session is required")
        if not settings.fetch_worker_url:
            errors.append("FETCH_WORKER_URL is required to isolate production URL fetching")

    if errors:
        raise ValueError("; ".join(errors))


def build_readiness_report(settings: Settings, *, checks: dict | None = None) -> dict:
    configured = True
    errors: list[str] = []
    try:
        validate_runtime_settings(settings)
    except ValueError as exc:
        configured = False
        errors = [item.strip() for item in str(exc).split(";") if item.strip()]

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
        "answer": {
            "provider": settings.answer_provider.lower(),
            "configured": settings.answer_provider.lower() in {"template", "local", "none"}
            or bool(settings.answer_api_key or settings.answer_base_url or settings.ollama_base_url),
        },
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
        "components": components,
        "errors": errors,
    }


def probe_provider_health(settings: Settings, *, timeout_seconds: float = 2.0) -> dict[str, bool]:
    """Perform non-generating provider probes for production readiness.

    The probes never submit prompts or embedding inputs, so readiness checks
    cannot create billable model requests.
    """

    results = {"answer": True, "embedding": True}
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

    register(
        "answer",
        settings.answer_provider,
        settings.ollama_base_url if settings.answer_provider.lower() == "ollama" else settings.answer_base_url,
        settings.answer_api_key,
        settings.ollama_chat_model if settings.answer_provider.lower() == "ollama" else settings.answer_model,
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
        checks.update(probe_provider_health(settings))
    return checks
