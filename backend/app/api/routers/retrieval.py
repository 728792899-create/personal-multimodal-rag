from __future__ import annotations

from contextlib import nullcontext

from fastapi import APIRouter, HTTPException, Request

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
    active_window = max(0, min(window, 3))
    pin = getattr(retriever.vector_store, "pin_index", None)
    context = pin() if callable(pin) else nullcontext()
    with context:
        chunks = retriever.vector_store.context_chunks(chunk_id, active_window)
        result = build_citation_context(chunks, chunk_id, window=active_window)
    if not result.get("found"):
        raise HTTPException(status_code=404, detail="证据片段不存在或已被删除。")
    return result


@router.post("/search")
def advanced_search(payload: SearchRequest):
    return rag_engine.search(payload.query, **retrieval_options(payload))


@router.post("/search/compare")
def compare_search(payload: SearchCompareRequest):
    return rag_engine.compare(payload.query, **retrieval_options(payload))


@router.post("/ask")
def ask(payload: AskRequest, request: Request):
    answer_generator_snapshot = rag_engine.snapshot_answer_generator()
    answer_provider = str(
        getattr(answer_generator_snapshot, "name", "") or "unknown"
    )
    try:
        identity = request.scope.get("state", {}).get("identity")
        user_id = identity.user_id if identity is not None else "owner"
        workspace_id = identity.workspace_id if identity is not None else "default"
        active_bases = payload.knowledge_base_ids or ["default"]
        retrieval_query, query_attachments = query_asset_service.enrich_query(
            payload.question,
            payload.attachments,
            active_bases,
            user_id=user_id,
            workspace_id=workspace_id,
        )
        response = rag_engine.ask(
            payload.question,
            retrieval_query=retrieval_query,
            answer_generator_snapshot=answer_generator_snapshot,
            **retrieval_options(payload),
        )
        response["retrieval_trace"]["query_attachments"] = query_attachments
        generation_failed = (
            response.get("generation_trace", {}).get("status") == "failed"
        )
        if generation_failed:
            response.setdefault("retry", {}).update(
                {
                    "action": "resubmit_same_request",
                    "method": "POST",
                    "endpoint": "/api/ask",
                    "preserve_retrieval_scope": True,
                }
            )
    except QueryAssetError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except Exception as exc:
        production_metrics.record_provider_error(
            provider=answer_provider,
            operation="ask",
        )
        if (
            not settings.provider_fallback_allowed
            and answer_provider.lower() not in {"template", "local", "none"}
        ):
            raise HTTPException(
                status_code=503,
                detail="当前配置的回答 Provider 暂时不可用，请检查 Provider 状态后重试。",
            ) from exc
        raise
    response["gap_report"] = analyze_knowledge_gaps(
        payload.question,
        response.get("answer", ""),
        response.get("citations", []),
        registry.load_documents(),
        registry.list_feedback(
            limit=100, user_id=user_id, workspace_id=workspace_id
        ),
    )
    history = registry.save_history(
        payload.question,
        response,
        payload.knowledge_base_ids[0] if payload.knowledge_base_ids else "default",
        user_id=user_id,
        workspace_id=workspace_id,
    )
    response["history_id"] = history["id"]
    response["created_at"] = history["created_at"]
    if generation_failed:
        production_metrics.record_provider_error(
            provider=answer_provider,
            operation="ask",
        )
    else:
        production_metrics.record_answer(response, provider=answer_provider)
    registry.log_operation(
        "ask_generation_failed" if generation_failed else "ask",
        (
            f"检索完成但回答生成失败：{payload.question[:40]}"
            if generation_failed
            else f"完成问答：{payload.question[:40]}"
        ),
        {"history_id": history["id"], "confidence": response.get("confidence"), "trust": response.get("trust", {}).get("label"), "citation_count": len(response.get("citations", []))},
        **({"level": "warning"} if generation_failed else {}),
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
