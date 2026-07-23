from __future__ import annotations


def export_answer_markdown(payload: dict, *, title: str = "RAG answer") -> str:
    lines = [
        f"# {_heading(title)}",
        "",
        f"> Exported from Personal Multimodal RAG · {payload.get('created_at', '')}",
        "",
    ]
    question = str(payload.get("question") or "")
    if question:
        lines.extend(["## Question", "", question.strip(), ""])
    lines.extend(["## Answer", "", str(payload.get("answer") or "").strip(), ""])
    lines.extend(_citation_section(payload.get("citations") or []))
    confidence = payload.get("confidence")
    if confidence is not None:
        lines.extend(["## Audit", "", f"- Confidence: {confidence}", ""])
    return "\n".join(lines).rstrip() + "\n"


def export_conversation_markdown(conversation: dict, messages: list[dict]) -> str:
    lines = [
        f"# {_heading(conversation.get('title') or 'Conversation')}",
        "",
        f"> Conversation {conversation.get('id', '')} · {conversation.get('updated_at', '')}",
        "",
    ]
    for message in messages:
        role = {
            "user": "User",
            "assistant": "Assistant",
            "system": "System",
        }.get(message.get("role"), "Message")
        lines.extend([f"## {role}", "", str(message.get("content") or "").strip(), ""])
        response = (message.get("metadata") or {}).get("response")
        if isinstance(response, dict):
            lines.extend(_citation_section(response.get("citations") or [], heading="Citations"))
    return "\n".join(lines).rstrip() + "\n"


def export_card_markdown(card: dict) -> str:
    lines = [
        f"# {_heading(card.get('title') or 'Knowledge card')}",
        "",
        f"> Knowledge card · {card.get('created_at', '')}",
        "",
        "## Question",
        "",
        str(card.get("question") or "").strip(),
        "",
        "## Answer",
        "",
        str(card.get("answer") or "").strip(),
        "",
    ]
    tags = [str(item) for item in card.get("tags") or [] if str(item)]
    if tags:
        lines.extend(["## Tags", "", " ".join(f"`{item.replace('`', '')}`" for item in tags), ""])
    lines.extend(_citation_section(card.get("citations") or []))
    return "\n".join(lines).rstrip() + "\n"


def _citation_section(citations: list[dict], heading: str = "Sources") -> list[str]:
    if not citations:
        return []
    lines = [f"## {heading}", ""]
    for index, citation in enumerate(citations, start=1):
        filename = str(citation.get("filename") or citation.get("file_name") or "source")
        page = citation.get("page_number")
        location = f", page {page}" if page else ""
        snippet = str(citation.get("snippet") or citation.get("text") or "").strip()
        lines.append(f"{index}. **{filename}**{location}")
        if snippet:
            lines.append(f"   > {snippet.replace(chr(10), ' ')[:600]}")
    lines.append("")
    return lines


def _heading(value: str) -> str:
    return " ".join(str(value).replace("#", "").split())[:160] or "Export"
