from __future__ import annotations

import copy
import json
import logging
import queue
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Iterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.api.common import retrieval_options
from app.config import settings
from app.core.store import query_asset_service, rag_engine, registry
from app.models.schemas import ConversationCreate, ConversationMessageRequest, ConversationUpdate
from app.services.safe_logging import public_error_message
from app.services.production_metrics import production_metrics


router = APIRouter(prefix="/conversations", tags=["conversations"])
logger = logging.getLogger(__name__)


SSE_HEARTBEAT_SECONDS = 15.0
_STREAM_END = object()


def _stream_with_heartbeats(items: Iterator[dict]) -> Iterator[dict | None]:
    """Consume a blocking provider generator without leaving the SSE socket idle.

    Provider clients are synchronous and can spend minutes loading a local model
    before the first answer token. A small producer thread lets the response
    emit SSE comments during that wait, so reverse proxies do not mistake a
    healthy in-flight request for an abandoned connection.
    """

    output: queue.Queue[object] = queue.Queue()
    stopped = threading.Event()

    def produce() -> None:
        try:
            for item in items:
                if stopped.is_set():
                    break
                # The RAG engine intentionally reuses and enriches the same trace
                # object through generation and citation audit. Snapshot at the
                # producer boundary so an already-emitted retrieval event cannot
                # be rewritten by a later stage before the SSE consumer encodes it.
                output.put(copy.deepcopy(item))
        except Exception as exc:
            output.put(exc)
        finally:
            output.put(_STREAM_END)

    producer = threading.Thread(
        target=produce,
        name="conversation-answer-stream",
        daemon=True,
    )
    producer.start()
    try:
        while True:
            try:
                item = output.get(timeout=max(0.001, SSE_HEARTBEAT_SECONDS))
            except queue.Empty:
                yield None
                continue
            if item is _STREAM_END:
                return
            if isinstance(item, Exception):
                raise item
            yield item
    finally:
        stopped.set()


def _stream_error(exc: Exception) -> tuple[str, str]:
    error_name = type(exc).__name__.lower()
    if isinstance(exc, TimeoutError) or "timeout" in error_name:
        return (
            "ANSWER_PROVIDER_TIMEOUT",
            public_error_message(
                exc,
                "回答服务在规定时间内未返回正文，已保留检索证据，请稍后重试。",
            ),
        )
    return (
        "STREAM_FAILED",
        public_error_message(
            exc,
            "流式回答失败，请稍后重试；如问题持续，请查看服务状态。",
        ),
    )


def _incomplete_response(
    retrieval_snapshot: dict | None,
    answer: str,
    *,
    status: str,
    answer_provider: str = "unknown",
    error_code: str = "",
    error_message: str = "",
    retry: dict | None = None,
) -> dict | None:
    """Build a reloadable evidence snapshot for interrupted answer generation."""

    if retrieval_snapshot is None:
        return None
    response = copy.deepcopy(retrieval_snapshot)
    response["answer"] = answer
    generation_trace = response.get("generation_trace")
    if not isinstance(generation_trace, dict):
        generation_trace = {}
    response["generation_trace"] = {
        **generation_trace,
        "answer_provider": generation_trace.get("answer_provider")
        or answer_provider
        or "unknown",
        "streamed": bool(answer),
        "incomplete": True,
        "status": status,
    }
    if status == "failed":
        response["generation_trace"].update(
            {
                "grounded": False,
                "failure_stage": "generation",
                "error_code": error_code or "STREAM_FAILED",
                "message": error_message,
                "retryable": True,
            }
        )
        response["retryable"] = True
        response["retry"] = copy.deepcopy(
            retry
            or {
                "action": "resubmit_same_request",
                "preserve_retrieval_scope": True,
            }
        )
        retrieval_trace = response.get("retrieval_trace")
        if not isinstance(retrieval_trace, dict):
            retrieval_trace = {}
            response["retrieval_trace"] = retrieval_trace
        pipeline = retrieval_trace.get("pipeline")
        if not isinstance(pipeline, dict):
            pipeline = {}
            retrieval_trace["pipeline"] = pipeline
        pipeline["generation"] = {
            "status": "failed",
            "reason": "answer_provider_failed",
            "error_code": error_code or "STREAM_FAILED",
        }
        response["citation_audit"] = {
            "coverage": 0,
            "grounding": 0,
            "checked": False,
            "status": "skipped",
            "reason": "generation_failed",
        }
    return response


CONTEXT_DEPENDENT_QUESTION = re.compile(
    r"(?:\b(?:it|its|they|them|those|these|the former|the latter|above|previous)\b"
    r"|它|它的|其(?!实)|上述|前述|前面|刚才|这个(?!\s*(?:RAG|系统|项目))"
    r"|该(?:流程|机制|方法|方案|指标|任务|文档|回答|功能)|这种|这些|那些|其中|继续)",
    re.IGNORECASE,
)


def _conversation_retrieval_query(question: str, context: list[dict]) -> tuple[str, int]:
    if not CONTEXT_DEPENDENT_QUESTION.search(question.strip()):
        return question, 0
    previous_questions = [
        str(message.get("content") or "").strip()
        for message in context
        if message.get("role") == "user"
        and str(message.get("content") or "").strip()
        and str(message.get("content") or "").strip() != question.strip()
    ]
    previous_questions = previous_questions[-1:]
    if not previous_questions:
        return question, 0
    history = "\n".join(f"- {item[:1_000]}" for item in previous_questions)
    return f"{question}\n\n最近会话中的相关问题：\n{history}"[:4_000], len(previous_questions)


def _conversation_owner(request: Request) -> tuple[str, str]:
    identity = request.scope.get("state", {}).get("identity")
    if identity is None:
        # Authentication-disabled developer/test instances retain the legacy
        # single-owner namespace. Session-authenticated requests never use it.
        return "owner", "default"
    return identity.user_id, identity.workspace_id


@router.get("")
def list_conversations(request: Request, limit: int = 50):
    user_id, workspace_id = _conversation_owner(request)
    return {
        "conversations": registry.list_conversations(
            limit,
            user_id=user_id,
            workspace_id=workspace_id,
        )
    }


@router.post("", status_code=201)
def create_conversation(payload: ConversationCreate, request: Request):
    user_id, workspace_id = _conversation_owner(request)
    try:
        conversation = registry.create_conversation(
            payload.title,
            payload.knowledge_base_ids,
            user_id=user_id,
            workspace_id=workspace_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"conversation": conversation}


@router.get("/{conversation_id}")
def get_conversation(conversation_id: str, request: Request):
    user_id, workspace_id = _conversation_owner(request)
    conversation = registry.get_conversation(
        conversation_id,
        user_id=user_id,
        workspace_id=workspace_id,
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在或已被删除。")
    return {"conversation": conversation}


@router.patch("/{conversation_id}")
def update_conversation(
    conversation_id: str,
    payload: ConversationUpdate,
    request: Request,
):
    user_id, workspace_id = _conversation_owner(request)
    try:
        conversation = registry.update_conversation(
            conversation_id,
            title=payload.title,
            knowledge_base_ids=payload.knowledge_base_ids,
            user_id=user_id,
            workspace_id=workspace_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在或已被删除。")
    return {"conversation": conversation}


@router.delete("/{conversation_id}")
def delete_conversation(conversation_id: str, request: Request):
    user_id, workspace_id = _conversation_owner(request)
    if not registry.delete_conversation(
        conversation_id,
        user_id=user_id,
        workspace_id=workspace_id,
    ):
        raise HTTPException(status_code=404, detail="会话不存在或已被删除。")
    return {"deleted": True}


@router.get("/{conversation_id}/messages")
def list_conversation_messages(
    conversation_id: str,
    request: Request,
    limit: int = 200,
):
    user_id, workspace_id = _conversation_owner(request)
    if not registry.get_conversation(
        conversation_id,
        user_id=user_id,
        workspace_id=workspace_id,
    ):
        raise HTTPException(status_code=404, detail="会话不存在或已被删除。")
    return {
        "messages": registry.list_conversation_messages(
            conversation_id,
            limit,
            user_id=user_id,
            workspace_id=workspace_id,
        )
    }


@router.post("/{conversation_id}/messages:stream")
def stream_conversation_message(
    conversation_id: str,
    payload: ConversationMessageRequest,
    request: Request,
):
    user_id, workspace_id = _conversation_owner(request)
    conversation = registry.get_conversation(
        conversation_id,
        user_id=user_id,
        workspace_id=workspace_id,
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在或已被删除。")
    identity = request.scope.get("state", {}).get("identity")
    usage_evidence: dict = {}
    if payload.record_as_real_usage:
        if settings.runtime_mode.lower() != "production":
            raise HTTPException(
                status_code=409,
                detail="只有 production 模式可以记录真实使用证据。",
            )
        if identity is None:
            raise HTTPException(
                status_code=401,
                detail="记录真实使用证据前，需要已登录的管理员明确确认。",
            )
        if identity.role not in {"admin", "owner"}:
            raise HTTPException(
                status_code=403,
                detail="只有管理员可以确认并记录真实使用证据。",
            )
        usage_evidence = {
            "attestation": "human-originated",
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "user_id": identity.user_id,
            "workspace_id": identity.workspace_id,
        }

    request_id = str(uuid.uuid4())
    assistant_message_id = str(uuid.uuid4())
    answer_generator_snapshot = rag_engine.snapshot_answer_generator()
    answer_provider = str(
        getattr(answer_generator_snapshot, "name", "") or "unknown"
    )

    def events():
        sequence = 0
        message_finalized = False
        answer_fragments: list[str] = []
        retrieval_snapshot: dict | None = None

        def encode(event_type: str, data: dict) -> str:
            nonlocal sequence
            sequence += 1
            event_payload = {
                "type": event_type,
                "request_id": request_id,
                "conversation_id": conversation_id,
                "message_id": assistant_message_id,
                "sequence": sequence,
                **data,
            }
            return f"event: {event_type}\ndata: {json.dumps(event_payload, ensure_ascii=False)}\n\n"

        registry.save_conversation_message(
            conversation_id,
            "user",
            payload.question,
            metadata={
                "attachments": [item.model_dump() for item in payload.attachments],
                **({"usage_evidence": usage_evidence} if usage_evidence else {}),
            },
        )
        registry.save_conversation_message(
            conversation_id,
            "assistant",
            "",
            status="streaming",
            message_id=assistant_message_id,
        )
        try:
            context = registry.conversation_context(conversation_id, max_turns=6, max_chars=12_000)
            retrieval_query, context_question_count = _conversation_retrieval_query(payload.question, context)
            query_attachments = []
            if payload.attachments:
                yield encode("query.enrichment.started", {"attachment_count": len(payload.attachments)})
                retrieval_query, query_attachments = query_asset_service.enrich_query(
                    retrieval_query,
                    payload.attachments,
                    conversation["knowledge_base_ids"],
                    user_id=user_id,
                    workspace_id=workspace_id,
                )
                yield encode(
                    "query.enrichment.completed",
                    {"attachments": query_attachments, "provider": query_attachments[0]["provider"] if query_attachments else "template"},
                )
            yield encode("retrieval.started", {"context_message_count": context_question_count})
            options = retrieval_options(payload)
            options["knowledge_base_ids"] = conversation["knowledge_base_ids"]
            terminal_event_received = False
            stream = rag_engine.stream(
                payload.question,
                retrieval_query=retrieval_query,
                answer_generator_snapshot=answer_generator_snapshot,
                **options,
            )
            for item in _stream_with_heartbeats(stream):
                if item is None:
                    yield ": keep-alive\n\n"
                    continue
                event_type = item["type"]
                if event_type == "retrieval.completed":
                    item["response"].setdefault("retrieval_trace", {})["query_attachments"] = query_attachments
                    retrieval_snapshot = copy.deepcopy(item["response"])
                    yield encode(event_type, item["response"])
                elif event_type == "answer.delta":
                    delta = str(item.get("delta") or "")
                    if delta:
                        answer_fragments.append(delta)
                        yield encode(event_type, {"delta": delta})
                elif event_type == "refusal":
                    terminal_event_received = True
                    response = item["response"]
                    production_metrics.record_answer(
                        response,
                        provider=answer_provider,
                    )
                    response.setdefault("retrieval_trace", {})["query_attachments"] = query_attachments
                    registry.save_conversation_message(
                        conversation_id,
                        "assistant",
                        response["answer"],
                        status="completed",
                        metadata={"response": response, "refused": True},
                        message_id=assistant_message_id,
                    )
                    message_finalized = True
                    yield encode(event_type, {"response": response})
                elif event_type == "answer.completed":
                    terminal_event_received = True
                    response = item["response"]
                    production_metrics.record_answer(
                        response,
                        provider=answer_provider,
                    )
                    response.setdefault("retrieval_trace", {})["query_attachments"] = query_attachments
                    registry.save_conversation_message(
                        conversation_id,
                        "assistant",
                        response["answer"],
                        status="completed",
                        metadata={"response": response, "refused": False},
                        message_id=assistant_message_id,
                    )
                    message_finalized = True
                    yield encode(event_type, {"response": response})
            if not terminal_event_received:
                raise RuntimeError("Answer stream ended without a terminal event")
            yield encode(
                "done",
                {
                    "status": "completed",
                    "real_usage_recorded": bool(usage_evidence),
                },
            )
        except GeneratorExit:
            raise
        except Exception as exc:
            production_metrics.record_provider_error(
                provider=answer_provider,
                operation="stream",
            )
            code, message = _stream_error(exc)
            partial_answer = "".join(answer_fragments)
            retry = {
                "action": "resubmit_same_request",
                "method": "POST",
                "endpoint": (
                    f"/api/conversations/{conversation_id}/messages:stream"
                ),
                "preserve_retrieval_scope": True,
            }
            failed_response = _incomplete_response(
                retrieval_snapshot,
                partial_answer,
                status="failed",
                answer_provider=answer_provider,
                error_code=code,
                error_message=message,
                retry=retry,
            )
            failed_metadata = {
                "error": message,
                "error_code": code,
                "request_id": request_id,
                "partial": bool(partial_answer),
                "retryable": True,
                "retry": retry,
            }
            if failed_response is not None:
                failed_metadata["response"] = failed_response
            logger.warning(
                "conversation stream failed request_id=%s provider=%s error_type=%s partial=%s",
                request_id,
                answer_provider,
                type(exc).__name__,
                bool(partial_answer),
            )
            registry.save_conversation_message(
                conversation_id,
                "assistant",
                partial_answer,
                status="failed",
                metadata=failed_metadata,
                message_id=assistant_message_id,
            )
            message_finalized = True
            yield encode(
                "error",
                {
                    "code": code,
                    "message": message,
                    "retryable": True,
                    "retry": retry,
                    **(
                        {"response": failed_response}
                        if failed_response is not None
                        else {}
                    ),
                },
            )
            yield encode(
                "done",
                {
                    "status": "failed",
                    "retryable": True,
                    "retry": retry,
                },
            )
        finally:
            if not message_finalized:
                partial_answer = "".join(answer_fragments)
                cancelled_response = _incomplete_response(
                    retrieval_snapshot,
                    partial_answer,
                    status="cancelled",
                    answer_provider=answer_provider,
                )
                cancelled_metadata = {
                    "cancelled": True,
                    "request_id": request_id,
                    "partial": bool(partial_answer),
                }
                if cancelled_response is not None:
                    cancelled_metadata["response"] = cancelled_response
                registry.save_conversation_message(
                    conversation_id,
                    "assistant",
                    partial_answer,
                    status="cancelled",
                    metadata=cancelled_metadata,
                    message_id=assistant_message_id,
                )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
