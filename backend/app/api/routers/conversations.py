from __future__ import annotations

import json
import re
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.api.common import retrieval_options
from app.core.store import rag_engine, registry
from app.models.schemas import ConversationCreate, ConversationMessageRequest, ConversationUpdate
from app.services.safe_logging import redact_sensitive_text


router = APIRouter(prefix="/conversations", tags=["conversations"])


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


@router.get("")
def list_conversations(limit: int = 50):
    return {"conversations": registry.list_conversations(limit)}


@router.post("", status_code=201)
def create_conversation(payload: ConversationCreate):
    try:
        conversation = registry.create_conversation(payload.title, payload.knowledge_base_ids)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"conversation": conversation}


@router.get("/{conversation_id}")
def get_conversation(conversation_id: str):
    conversation = registry.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"conversation": conversation}


@router.patch("/{conversation_id}")
def update_conversation(conversation_id: str, payload: ConversationUpdate):
    try:
        conversation = registry.update_conversation(
            conversation_id,
            title=payload.title,
            knowledge_base_ids=payload.knowledge_base_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"conversation": conversation}


@router.delete("/{conversation_id}")
def delete_conversation(conversation_id: str):
    if not registry.delete_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"deleted": True}


@router.get("/{conversation_id}/messages")
def list_conversation_messages(conversation_id: str, limit: int = 200):
    if not registry.get_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"messages": registry.list_conversation_messages(conversation_id, limit)}


@router.post("/{conversation_id}/messages:stream")
def stream_conversation_message(conversation_id: str, payload: ConversationMessageRequest):
    conversation = registry.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    request_id = str(uuid.uuid4())
    assistant_message_id = str(uuid.uuid4())

    def events():
        sequence = 0
        finalized = False

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

        registry.save_conversation_message(conversation_id, "user", payload.question)
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
            yield encode("retrieval.started", {"context_message_count": context_question_count})
            options = retrieval_options(payload)
            options["knowledge_base_ids"] = conversation["knowledge_base_ids"]
            for item in rag_engine.stream(payload.question, retrieval_query=retrieval_query, **options):
                event_type = item["type"]
                if event_type == "retrieval.completed":
                    yield encode(event_type, item["response"])
                elif event_type == "answer.delta":
                    yield encode(event_type, {"delta": item["delta"]})
                elif event_type == "refusal":
                    response = item["response"]
                    registry.save_conversation_message(
                        conversation_id,
                        "assistant",
                        response["answer"],
                        status="completed",
                        metadata={"response": response, "refused": True},
                        message_id=assistant_message_id,
                    )
                    yield encode(event_type, {"response": response})
                elif event_type == "answer.completed":
                    response = item["response"]
                    registry.save_conversation_message(
                        conversation_id,
                        "assistant",
                        response["answer"],
                        status="completed",
                        metadata={"response": response, "refused": False},
                        message_id=assistant_message_id,
                    )
                    yield encode(event_type, {"response": response})
            finalized = True
            yield encode("done", {"status": "completed"})
        except GeneratorExit:
            raise
        except Exception as exc:
            message = redact_sensitive_text(exc)
            registry.save_conversation_message(
                conversation_id,
                "assistant",
                "",
                status="failed",
                metadata={"error": message},
                message_id=assistant_message_id,
            )
            finalized = True
            yield encode("error", {"code": "STREAM_FAILED", "message": message})
            yield encode("done", {"status": "failed"})
        finally:
            if not finalized:
                registry.save_conversation_message(
                    conversation_id,
                    "assistant",
                    "",
                    status="cancelled",
                    metadata={"cancelled": True},
                    message_id=assistant_message_id,
                )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
