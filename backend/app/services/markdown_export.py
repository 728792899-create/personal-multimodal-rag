from __future__ import annotations


def export_answer_markdown(payload: dict, *, title: str = "RAG 回答") -> str:
    lines = [
        f"# {_heading(title)}",
        "",
        f"> 由 Personal Multimodal RAG 导出 · {payload.get('created_at', '')}",
        "",
    ]
    question = str(payload.get("question") or "")
    if question:
        lines.extend(["## 问题", "", question.strip(), ""])
    lines.extend(["## 回答", "", str(payload.get("answer") or "").strip(), ""])
    lines.extend(_citation_section(payload.get("citations") or []))
    confidence = payload.get("confidence")
    if confidence is not None:
        lines.extend(["## 审计", "", f"- 置信度：{confidence}", ""])
    return "\n".join(lines).rstrip() + "\n"


def export_conversation_markdown(conversation: dict, messages: list[dict]) -> str:
    lines = [
        f"# {_heading(conversation.get('title') or '会话')}",
        "",
        f"> 会话 {conversation.get('id', '')} · {conversation.get('updated_at', '')}",
        "",
    ]
    for message in messages:
        role = {
            "user": "用户",
            "assistant": "助手",
            "system": "系统",
        }.get(message.get("role"), "消息")
        lines.extend([f"## {role}", "", str(message.get("content") or "").strip(), ""])
        response = (message.get("metadata") or {}).get("response")
        if isinstance(response, dict):
            lines.extend(_citation_section(response.get("citations") or [], heading="引用"))
    return "\n".join(lines).rstrip() + "\n"


def export_card_markdown(card: dict) -> str:
    lines = [
        f"# {_heading(card.get('title') or '知识卡片')}",
        "",
        f"> 知识卡片 · {card.get('created_at', '')}",
        "",
        "## 问题",
        "",
        str(card.get("question") or "").strip(),
        "",
        "## 回答",
        "",
        str(card.get("answer") or "").strip(),
        "",
    ]
    tags = [str(item) for item in card.get("tags") or [] if str(item)]
    if tags:
        lines.extend(["## 标签", "", " ".join(f"`{item.replace('`', '')}`" for item in tags), ""])
    lines.extend(_citation_section(card.get("citations") or []))
    return "\n".join(lines).rstrip() + "\n"


def _citation_section(citations: list[dict], heading: str = "来源") -> list[str]:
    if not citations:
        return []
    lines = [f"## {heading}", ""]
    for index, citation in enumerate(citations, start=1):
        filename = str(citation.get("filename") or citation.get("file_name") or "来源")
        page = citation.get("page_number")
        location = f"，第 {page} 页" if page else ""
        snippet = str(citation.get("snippet") or citation.get("text") or "").strip()
        lines.append(f"{index}. **{filename}**{location}")
        if snippet:
            lines.append(f"   > {snippet.replace(chr(10), ' ')[:600]}")
    lines.append("")
    return lines


def _heading(value: str) -> str:
    return " ".join(str(value).replace("#", "").split())[:160] or "导出"
