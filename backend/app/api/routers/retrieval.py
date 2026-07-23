from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.common import retrieval_options
from app.core.store import query_asset_service, rag_engine, registry, retriever
from app.config import settings
from app.models.schemas import AskRequest, SearchCompareRequest, SearchRequest
from app.services.knowledge_tools import analyze_knowledge_gaps, build_citation_context
from app.services.production_metrics import production_metrics
from app.services.query_assets import QueryAssetError


router = APIRouter(tags=["retrieval"])


@router.get("/search")
def search(q: str, top_k: int = 5, search_mode: str = "hybrid"):
    return rag_engine.search(q, top_k=top_k, search_mode=search_mode)


@router.get("/chunks/{chunk_id:path}/context")
def chunk_context(chunk_id: str, window: int = 1):
    result = build_citation_context(list(retriever.vector_store.chunks.values()), chunk_id, window=max(0, min(window, 3)))
    if not result.get("found"):
        raise HTTPException(status_code=404, detail="Chunk not found")
    return result


@router.post("/search")
def advanced_search(payload: SearchRequest):
    return rag_engine.search(payload.query, **retrieval_options(payload))


@router.post("/search/compare")
def compare_search(payload: SearchCompareRequest):
    return rag_engine.compare(payload.query, **retrieval_options(payload))


@router.post("/ask")
def ask(payload: AskRequest):
    try:
        active_bases = payload.knowledge_base_ids or ["default"]
        retrieval_query, query_attachments = query_asset_service.enrich_query(
            payload.question,
            payload.attachments,
            active_bases,
        )
        response = rag_engine.ask(
            payload.question,
            retrieval_query=retrieval_query,
            **retrieval_options(payload),
        )
        response["retrieval_trace"]["query_attachments"] = query_attachments
    except QueryAssetError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except Exception as exc:
        production_metrics.record_provider_error(
            provider=settings.answer_provider,
            operation="ask",
        )
        if not settings.provider_fallback_allowed and settings.answer_provider.lower() not in {"template", "local", "none"}:
            raise HTTPException(
                status_code=503,
                detail="Configured answer provider is unavailable; inspect provider status and request logs.",
            ) from exc
        raise
    response["gap_report"] = analyze_knowledge_gaps(
        payload.question,
        response.get("answer", ""),
        response.get("citations", []),
        registry.load_documents(),
        registry.list_feedback(limit=100),
    )
    history = registry.save_history(
        payload.question,
        response,
        payload.knowledge_base_ids[0] if payload.knowledge_base_ids else "default",
    )
    response["history_id"] = history["id"]
    response["created_at"] = history["created_at"]
    production_metrics.record_answer(response, provider=settings.answer_provider)
    registry.log_operation(
        "ask",
        f"完成问答：{payload.question[:40]}",
        {"history_id": history["id"], "confidence": response.get("confidence"), "trust": response.get("trust", {}).get("label"), "citation_count": len(response.get("citations", []))},
    )
    return response


@router.get("/history")
def list_history(limit: int = 30):
    return {"history": registry.list_history(limit=limit)}


@router.delete("/history")
def clear_history():
    registry.clear_history()
    registry.log_operation("history_cleared", "清空问答历史", {}, level="warning")
    return {"deleted": True}
