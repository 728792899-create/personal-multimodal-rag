from __future__ import annotations

from fastapi import APIRouter

from app.config import settings


router = APIRouter(prefix="/providers", tags=["providers"])


def _answer_status() -> dict:
    provider = settings.answer_provider.lower().replace("-", "_")
    aliases = {"responses": "openai_responses", "openai_responses": "openai_responses"}
    normalized = aliases.get(provider, provider)
    if normalized in {"template", "local", "none"}:
        return {"provider": "template", "configured": True, "mode": "offline", "capabilities": ["answer", "deterministic"]}
    if normalized == "openai_responses":
        return {"provider": normalized, "configured": bool(settings.answer_api_key), "mode": "external", "capabilities": ["answer", "stream"]}
    if normalized == "openai_compatible_chat":
        return {"provider": normalized, "configured": bool(settings.answer_base_url), "mode": "external", "capabilities": ["answer", "stream"]}
    if normalized == "ollama":
        return {"provider": normalized, "configured": bool(settings.ollama_base_url), "mode": "local", "capabilities": ["answer", "stream"]}
    return {"provider": normalized, "configured": False, "mode": "unknown", "capabilities": []}


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
    return {"provider": normalized, "configured": configured, "mode": mode, "capabilities": ["embeddings"]}


@router.get("/status")
def provider_status():
    answer = _answer_status()
    embedding = _embedding_status()
    degraded = not answer["configured"] or not embedding["configured"]
    return {
        "status": "degraded" if degraded else "ready",
        "environment": settings.app_environment,
        "fallback_allowed": settings.provider_fallback_allowed,
        "providers": {"answer": answer, "embedding": embedding, "vector_store": {"provider": settings.vector_store, "configured": True}},
    }
