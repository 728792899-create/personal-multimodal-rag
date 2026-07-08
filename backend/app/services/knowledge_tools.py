from __future__ import annotations

from datetime import datetime

from app.models.domain import Chunk, Document
from app.services.query_intelligence import analyze_query
from app.services.text_utils import tokenize


GAP_PATTERNS = {
    "部署资料": {"部署", "docker", "kubernetes", "k8s", "上线", "nginx", "服务器"},
    "数据库设计": {"数据库", "schema", "表", "索引", "sqlite", "postgres", "mysql"},
    "接口文档": {"api", "接口", "路由", "请求", "响应", "鉴权"},
    "性能数据": {"性能", "耗时", "latency", "qps", "并发", "缓存", "成本"},
    "测试报告": {"测试", "评测", "pytest", "coverage", "recall", "mrr", "precision"},
    "安全与隐私": {"安全", "隐私", "密钥", "权限", "脱敏", "token"},
    "多模态解析": {"图片", "ocr", "pdf", "表格", "视频", "音频", "vlm"},
}


REWRITE_TEMPLATES = {
    "short": ("更短", "请用 3 条以内要点表达，保留证据编号。"),
    "detailed": ("更详细", "请展开为背景、方法、结果、限制四段。"),
    "interview": ("面试回答", "请改写成 1 分钟面试口播，突出问题、方案、结果和反思。"),
    "resume": ("简历 Bullet", "请改写成 2-3 条简历 bullet，突出动词、技术栈和结果。"),
    "study": ("学习笔记", "请改写成学习笔记，包含概念、步骤、易错点。"),
    "faq": ("FAQ", "请改写成 3 个常见问答。"),
}


def build_citation_context(chunks: list[Chunk], chunk_id: str, window: int = 1) -> dict:
    selected = next((chunk for chunk in chunks if chunk.chunk_id == chunk_id), None)
    if not selected:
        return {"found": False, "chunk_id": chunk_id, "context": []}
    siblings = sorted(
        [chunk for chunk in chunks if chunk.document_id == selected.document_id],
        key=lambda item: item.chunk_index,
    )
    index = next((idx for idx, chunk in enumerate(siblings) if chunk.chunk_id == chunk_id), -1)
    start = max(0, index - window)
    end = min(len(siblings), index + window + 1)
    return {
        "found": True,
        "chunk_id": chunk_id,
        "document_id": selected.document_id,
        "filename": selected.file_name,
        "page_number": selected.page_number,
        "heading_path": selected.heading_path,
        "context": [
            {
                "id": chunk.chunk_id,
                "index": chunk.chunk_index,
                "text": chunk.text,
                "page_number": chunk.page_number,
                "heading_path": chunk.heading_path,
                "is_current": chunk.chunk_id == chunk_id,
            }
            for chunk in siblings[start:end]
        ],
    }


def rewrite_answer(answer: str, style: str, question: str = "", citations: list[dict] | None = None) -> dict:
    style = style if style in REWRITE_TEMPLATES else "short"
    label, instruction = REWRITE_TEMPLATES[style]
    citations = citations or []
    rewritten = _rule_based_rewrite(answer, style, question, citations)
    return {
        "style": style,
        "label": label,
        "instruction": instruction,
        "rewritten": rewritten,
        "created_at": datetime.utcnow().isoformat(),
    }


def build_knowledge_card(question: str, answer: str, citations: list[dict], tags: list[str] | None = None) -> dict:
    title = question.strip()[:42] or "知识卡片"
    source_docs = sorted({item.get("filename", "") for item in citations if item.get("filename")})
    auto_tags = sorted(set(tags or []) | set(_auto_tags(question, answer)))
    return {
        "title": title,
        "question": question,
        "answer": answer,
        "citations": citations[:8],
        "tags": auto_tags[:8],
        "source_documents": source_docs,
        "created_at": datetime.utcnow().isoformat(),
    }


def analyze_knowledge_gaps(
    question: str,
    answer: str,
    citations: list[dict],
    documents: list[Document],
    feedback: list[dict],
) -> dict:
    corpus = "\n".join([doc.file_name + "\n" + doc.text[:3000] for doc in documents]).lower()
    query_terms = set(tokenize(question))
    missing_topics = []
    for topic, keywords in GAP_PATTERNS.items():
        topic_hits = [keyword for keyword in keywords if keyword.lower() in question.lower() or keyword.lower() in query_terms]
        corpus_hits = [keyword for keyword in keywords if keyword.lower() in corpus]
        if topic_hits and not corpus_hits:
            missing_topics.append(
                {
                    "topic": topic,
                    "matched_query_terms": topic_hits,
                    "reason": "用户问题提到该方向，但当前资料库没有明显覆盖。",
                    "suggestion": f"补充 {topic} 相关说明、截图、配置或测试记录。",
                }
            )

    if not citations:
        missing_topics.append(
            {
                "topic": "直接证据",
                "matched_query_terms": sorted(query_terms)[:8],
                "reason": "当前问题没有召回可用证据。",
                "suggestion": "导入更直接的原始资料，或把问题拆成更具体的事实点。",
            }
        )

    negative_feedback = [item for item in feedback if item.get("rating") == "down"]
    failure_types: dict[str, int] = {}
    for item in negative_feedback:
        key = item.get("failure_type") or "unclassified"
        failure_types[key] = failure_types.get(key, 0) + 1

    return {
        "query_intent": analyze_query(question),
        "missing_topics": missing_topics[:8],
        "failure_types": failure_types,
        "needs_action": bool(missing_topics or failure_types),
        "suggestions": _gap_suggestions(missing_topics, failure_types),
        "created_at": datetime.utcnow().isoformat(),
    }


def _rule_based_rewrite(answer: str, style: str, question: str, citations: list[dict]) -> str:
    cleaned = answer.strip()
    evidence = citations[:3]
    if style == "resume":
        bullets = []
        for item in evidence:
            source = item.get("filename", "资料")
            snippet = _shorten(item.get("snippet") or item.get("text") or "", 86)
            bullets.append(f"- 基于 {source} 梳理知识证据：{snippet}")
        return "\n".join(bullets or [f"- 围绕“{question}”完成资料检索、证据引用和可信度判断。"])
    if style == "interview":
        return (
            f"我会这样讲：这个问题是“{question}”。我先通过混合检索定位资料，再用重排和引用审计筛掉弱证据。"
            f"从当前证据看，核心结论是：{_shorten(cleaned, 180)}"
            "如果证据不足，我会明确拒答并把失败样本沉淀到评测集。"
        )
    if style == "study":
        return f"学习笔记\n\n概念：{_shorten(question, 60)}\n\n要点：\n{_bulletize(cleaned, 4)}\n\n易错点：注意区分检索证据和模型推断。"
    if style == "faq":
        return (
            f"Q1：这个问题问什么？\nA：{question}\n\n"
            f"Q2：当前答案是什么？\nA：{_shorten(cleaned, 160)}\n\n"
            "Q3：如何确认答案可信？\nA：查看引用片段、覆盖率和未支持句子。"
        )
    if style == "detailed":
        return f"背景：{question}\n\n方法：系统基于混合检索、重排和引用审计生成回答。\n\n结果：{cleaned}\n\n限制：仍需检查引用上下文和资料覆盖范围。"
    return _bulletize(cleaned, 3)


def _bulletize(text: str, limit: int) -> str:
    lines = [line.strip(" -0123456789.、") for line in text.splitlines() if len(line.strip()) >= 8]
    if not lines:
        lines = [text]
    return "\n".join(f"- {_shorten(line, 120)}" for line in lines[:limit])


def _gap_suggestions(missing_topics: list[dict], failure_types: dict[str, int]) -> list[str]:
    suggestions = [item["suggestion"] for item in missing_topics[:4]]
    if failure_types.get("retrieval_miss"):
        suggestions.append("将 retrieval_miss 样本加入评测集，对比 recall profile 和 rerank 开关。")
    if failure_types.get("wrong_citation"):
        suggestions.append("增加引用上下文检查，避免片段命中但语义不支持。")
    if not suggestions:
        suggestions.append("当前没有明显资料缺口，可继续积累真实问答反馈。")
    return suggestions[:6]


def _auto_tags(question: str, answer: str) -> list[str]:
    tokens = tokenize(f"{question}\n{answer}")
    counts: dict[str, int] = {}
    for token in tokens:
        if len(token) >= 2:
            counts[token] = counts.get(token, 0) + 1
    return [item for item, _ in sorted(counts.items(), key=lambda row: (-row[1], row[0]))[:8]]


def _shorten(text: str, limit: int) -> str:
    cleaned = " ".join(str(text).split())
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[:limit].rstrip()}..."
