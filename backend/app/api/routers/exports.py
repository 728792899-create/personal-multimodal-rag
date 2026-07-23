from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.core.store import registry
from app.services.markdown_export import (
    export_answer_markdown,
    export_card_markdown,
    export_conversation_markdown,
)


router = APIRouter(prefix="/exports", tags=["exports"])


def _markdown_response(content: str, filename: str) -> Response:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", filename).strip("-")[:80] or "rag-export"
    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe}.md"'},
    )


@router.get("/history/{history_id}.md")
def export_history(history_id: str):
    history = registry.get_history(history_id)
    if not history:
        raise HTTPException(status_code=404, detail="History item not found")
    return _markdown_response(
        export_answer_markdown(history, title=history.get("question") or "RAG answer"),
        f"answer-{history_id}",
    )


@router.get("/conversations/{conversation_id}.md")
def export_conversation(conversation_id: str):
    conversation = registry.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return _markdown_response(
        export_conversation_markdown(
            conversation,
            registry.list_conversation_messages(conversation_id),
        ),
        f"conversation-{conversation_id}",
    )


@router.get("/knowledge-cards/{card_id}.md")
def export_knowledge_card(card_id: str):
    card = registry.get_knowledge_card(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Knowledge card not found")
    return _markdown_response(
        export_card_markdown(card),
        f"knowledge-card-{card_id}",
    )
