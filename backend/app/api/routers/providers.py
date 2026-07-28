from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, SecretStr

from app.config import settings
from app.services.runtime_answer_provider import (
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    RuntimeAnswerProviderConfigurationError,
    RuntimeAnswerProviderValidationError,
)
from app.services.safe_logging import sanitize_url_for_log


router = APIRouter(prefix="/providers", tags=["providers"])


class RuntimeAnswerProviderConnect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: SecretStr


def get_runtime_answer_provider():
    """Resolve lazily so the API composition root can finish importing."""

    from app.core.store import runtime_answer_provider

    return runtime_answer_provider


def _answer_status() -> dict:
    runtime_status = get_runtime_answer_provider().status()
    if runtime_status is not None:
        return runtime_status
    provider = settings.answer_provider.lower().replace("-", "_")
    aliases = {"responses": "openai_responses", "openai_responses": "openai_responses"}
    normalized = aliases.get(provider, provider)
    if normalized in {"template", "local", "none"}:
        return {"provider": "template", "configured": True, "health": "ready", "mode": "offline", "capabilities": ["answer", "deterministic"]}
    if normalized == "openai_responses":
        return {
            "provider": normalized,
            "configured": bool(settings.answer_api_key),
            "health": "not_checked",
            "mode": "external",
            "capabilities": ["answer", "stream"],
            "model": settings.answer_model,
            "base_url": _public_base_url(settings.answer_base_url),
        }
    if normalized == "openai_compatible_chat":
        official_deepseek = (
            str(settings.answer_base_url).strip().rstrip("/")
            == DEEPSEEK_BASE_URL
            and settings.answer_model == DEEPSEEK_MODEL
        )
        return {
            "provider": (
                "deepseek_official"
                if official_deepseek
                else normalized
            ),
            "configured": bool(settings.answer_base_url)
            and (
                bool(settings.answer_api_key)
                if official_deepseek
                else True
            ),
            "health": "not_checked",
            "mode": "external",
            "capabilities": ["answer", "stream"],
            "model": settings.answer_model,
            "base_url": _public_base_url(settings.answer_base_url),
        }
    if normalized == "ollama":
        return {"provider": normalized, "configured": bool(settings.ollama_base_url), "health": "not_checked", "mode": "local", "capabilities": ["answer", "stream"]}
    return {"provider": normalized, "configured": False, "health": "unavailable", "mode": "unknown", "capabilities": []}


def _deepseek_runtime_status() -> dict:
    active = get_runtime_answer_provider().status()
    if active is not None:
        return active
    startup = _answer_status()
    if (
        startup.get("provider") == "deepseek_official"
        and startup.get("configured") is True
    ):
        return {
            **startup,
            "runtime_override": False,
            "credential_state": "startup_configured",
            "connected": True,
            "active": True,
            "temporary": False,
            "status": "ready",
        }
    return {
        "provider": "deepseek_official",
        "configured": False,
        "health": "not_configured",
        "mode": "external",
        "capabilities": ["answer", "stream"],
        "model": DEEPSEEK_MODEL,
        "base_url": DEEPSEEK_BASE_URL,
        "runtime_override": False,
        "credential_state": "not_configured",
        "connected": False,
        "active": False,
        "temporary": True,
        "status": "not_configured",
    }


def _public_base_url(value: str) -> str:
    normalized = str(value or "").strip().rstrip("/")
    if not normalized:
        return ""
    if normalized == DEEPSEEK_BASE_URL:
        return DEEPSEEK_BASE_URL
    return sanitize_url_for_log(normalized).rstrip("/")


def _embedding_status() -> dict:
    provider = settings.embedding_provider.lower().replace("-", "_")
    aliases = {"local": "sentence_transformers", "huggingface": "sentence_transformers"}
    normalized = aliases.get(provider, provider)
    configured = True
    mode = "offline"
    if normalized in {"openai", "openai_compatible"}:
        configured = bool(settings.openai_api_key)
        mode = "external"
    elif normalized == "ollama":
        configured = bool(settings.ollama_base_url)
        mode = "local"
    return {"provider": normalized, "configured": configured, "health": "ready" if mode == "offline" else "not_checked", "mode": mode, "capabilities": ["embeddings"]}


def _enrichment_status() -> dict:
    provider = settings.enrichment_provider.lower().replace("-", "_")
    aliases = {"responses": "openai_responses", "openai_responses": "openai_responses", "ollama": "ollama_vision"}
    normalized = aliases.get(provider, provider)
    if normalized in {"template", "local", "none"}:
        return {"provider": "template", "configured": True, "health": "ready", "mode": "offline", "capabilities": ["image", "table", "equation", "deterministic"]}
    if normalized == "openai_responses":
        return {"provider": normalized, "configured": bool(settings.enrichment_api_key), "health": "not_checked", "mode": "external", "capabilities": ["image", "structured_output"]}
    if normalized == "openai_compatible_vision":
        return {"provider": normalized, "configured": bool(settings.enrichment_base_url), "health": "not_checked", "mode": "external", "capabilities": ["image", "structured_output"]}
    if normalized == "ollama_vision":
        return {"provider": normalized, "configured": bool(settings.ollama_base_url), "health": "not_checked", "mode": "local", "capabilities": ["image", "structured_output"]}
    return {"provider": normalized, "configured": False, "health": "unavailable", "mode": "unknown", "capabilities": []}


@router.get("/status")
def provider_status():
    answer = _answer_status()
    embedding = _embedding_status()
    enrichment = _enrichment_status()
    deepseek = _deepseek_runtime_status()
    degraded = not answer["configured"] or not embedding["configured"] or not enrichment["configured"]
    return {
        "status": "degraded" if degraded else "ready",
        "environment": settings.app_environment,
        "fallback_allowed": settings.provider_fallback_allowed,
        "runtime": {"deepseek": deepseek},
        "providers": {
            "answer": answer,
            "embedding": embedding,
            "enrichment": enrichment,
            "vector_store": {"provider": settings.vector_store, "configured": True, "health": "ready"},
            "deepseek_runtime": deepseek,
        },
    }


@router.post("/deepseek/runtime")
def connect_runtime_answer_provider(
    payload: RuntimeAnswerProviderConnect,
    request: Request,
):
    _require_owner_session(request)
    try:
        provider = get_runtime_answer_provider().connect_deepseek(
            api_key=payload.api_key.get_secret_value(),
            base_url=DEEPSEEK_BASE_URL,
            model=DEEPSEEK_MODEL,
        )
    except RuntimeAnswerProviderConfigurationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except RuntimeAnswerProviderValidationError:
        raise HTTPException(
            status_code=502,
            detail="DeepSeek 连接验证失败，请检查凭据或服务状态后重试。",
        ) from None
    return {
        "status": "ready",
        "runtime": {"deepseek": provider},
        "connection": provider,
    }


@router.delete("/deepseek/runtime")
def clear_runtime_answer_provider(request: Request):
    _require_owner_session(request)
    cleared = get_runtime_answer_provider().clear()
    provider = _deepseek_runtime_status()
    return {
        "status": "cleared" if cleared else "not_configured",
        "runtime": {"deepseek": provider},
        "connection": provider,
    }


def _require_owner_session(request: Request) -> None:
    identity = request.scope.get("state", {}).get("identity")
    if identity is None or getattr(identity, "role", "") not in {
        "owner",
        "admin",
    }:
        raise HTTPException(
            status_code=403,
            detail="必须使用管理员会话才能修改回答 Provider，匿名或只读会话无权执行此操作。",
        )
