from __future__ import annotations

import re
from datetime import datetime
from statistics import mean
from typing import Iterable

from app.models.domain import Chunk, Document
from app.services.text_utils import tokenize


def lifecycle_event(
    stage: str,
    status: str,
    started_at: datetime,
    ended_at: datetime | None = None,
    error: str = "",
    retry_count: int = 0,
) -> dict:
    ended = ended_at or started_at
    return {
        "stage": stage,
        "status": status,
        "started_at": started_at.isoformat(),
        "ended_at": ended.isoformat(),
        "duration_ms": max(0, round((ended - started_at).total_seconds() * 1000, 2)),
        "error": error,
        "retry_count": retry_count,
    }


def assess_document_quality(document: Document, chunks: Iterable[Chunk]) -> dict:
    chunk_list = list(chunks)
    text = document.text
    signals: list[dict] = []
    suggestions: list[str] = []
    score = 100

    char_count = len(text)
    page_count = len(document.pages)
    chunk_count = len(chunk_list)
    chunk_lengths = [len(chunk.text.strip()) for chunk in chunk_list]
    avg_chunk_length = round(mean(chunk_lengths), 1) if chunk_lengths else 0
    min_chunk_length = min(chunk_lengths) if chunk_lengths else 0
    max_chunk_length = max(chunk_lengths) if chunk_lengths else 0
    weird_ratio = _weird_char_ratio(text)
    duplicated_ratio = _duplicate_chunk_ratio(chunk_list)
    index_status = str(document.metadata.get("index_status") or "unknown")
    ocr_status = str(document.metadata.get("ocr_status") or "")

    if char_count == 0:
        score -= 45
        signals.append(_signal("error", "文档没有可读文本", -45))
        suggestions.append("重新导入可复制文本版 PDF，或先完成 OCR。")
    elif char_count < 200:
        score -= 10
        signals.append(_signal("warning", "可读文本偏少", -10))
        suggestions.append("确认文件是否只解析到封面、目录或少量图片文字。")

    if chunk_count == 0:
        score -= 35
        signals.append(_signal("error", "未生成 chunk", -35))
        suggestions.append("重建索引，或调整文档切分配置。")
    elif avg_chunk_length < 120:
        score -= 8
        signals.append(_signal("warning", "chunk 平均长度偏短", -8))
        suggestions.append("适当增大 chunk size，降低碎片化召回。")
    elif avg_chunk_length > 900:
        score -= 8
        signals.append(_signal("warning", "chunk 平均长度偏长", -8))
        suggestions.append("适当减小 chunk size，提高命中位置精度。")

    if page_count == 0:
        score -= 8
        signals.append(_signal("warning", "页信息为空", -8))

    if weird_ratio > 0.08:
        score -= 14
        signals.append(_signal("warning", "疑似乱码比例偏高", -14))
        suggestions.append("检查 PDF 解析结果，必要时改用 OCR 或重新导出文档。")

    if duplicated_ratio > 0.25:
        score -= 10
        signals.append(_signal("warning", "重复 chunk 偏多", -10))
        suggestions.append("检查是否导入了重复版本，或切分 overlap 是否过大。")

    if ocr_status and ocr_status not in {"success", "ok"}:
        score -= 12
        signals.append(_signal("warning", f"OCR 状态为 {ocr_status}", -12))
        suggestions.append("安装并配置 OCR 依赖后重新索引图片类资料。")

    if index_status != "indexed":
        score -= 22
        signals.append(_signal("error", f"索引状态为 {index_status}", -22))
        suggestions.append("先完成索引或使用诊断按钮重建索引。")

    if not suggestions:
        suggestions.append("当前文档质量良好，可继续用于问答和检索评测。")

    final_score = max(0, min(100, score))
    return {
        "score": final_score,
        "level": _quality_level(final_score),
        "char_count": char_count,
        "page_count": page_count,
        "chunk_count": chunk_count,
        "avg_chunk_length": avg_chunk_length,
        "min_chunk_length": min_chunk_length,
        "max_chunk_length": max_chunk_length,
        "weird_char_ratio": round(weird_ratio, 4),
        "duplicate_chunk_ratio": round(duplicated_ratio, 4),
        "signals": signals,
        "suggestions": suggestions[:4],
        "updated_at": datetime.utcnow().isoformat(),
    }


def summarize_document(document: Document, chunks: Iterable[Chunk]) -> dict:
    chunk_list = list(chunks)
    text = " ".join(document.text.split())
    keywords = _keywords(text)
    first_sentence = _first_sentence(text)
    if not first_sentence:
        first_sentence = f"{document.file_name} 已导入知识库。"

    key_points = []
    for chunk in chunk_list[:4]:
        snippet = " ".join(chunk.text.split())
        if snippet:
            key_points.append(_truncate(snippet, 90))

    suggested_questions = [
        f"请总结《{document.title or document.file_name}》的核心内容。",
        f"这份资料有哪些可以写进简历或项目复盘的亮点？",
        f"这份资料中有哪些风险、缺口或需要补充的地方？",
    ]
    if keywords:
        suggested_questions.insert(1, f"这份资料里关于“{keywords[0]}”的内容是什么？")

    return {
        "one_sentence": _truncate(first_sentence, 120),
        "key_points": key_points[:5],
        "key_concepts": keywords[:10],
        "suggested_questions": suggested_questions[:5],
        "updated_at": datetime.utcnow().isoformat(),
    }


def build_knowledge_overview(documents: list[Document], chunks_by_document: dict[str, list[Chunk]], history: list[dict]) -> dict:
    quality_reports = [
        _quality_from_metadata(doc, chunks_by_document.get(doc.document_id, []))
        for doc in documents
    ]
    avg_quality = round(mean([item["score"] for item in quality_reports]), 1) if quality_reports else 0
    low_quality = [
        {"id": doc.document_id, "filename": doc.file_name, "score": report["score"]}
        for doc, report in zip(documents, quality_reports)
        if report["score"] < 70
    ]
    themes = _overview_themes(documents)
    recent_questions = [item.get("question", "") for item in history[:6] if item.get("question")]
    total_chunks = sum(len(chunks_by_document.get(doc.document_id, [])) for doc in documents)
    total_chars = sum(len(doc.text) for doc in documents)

    suggestions = []
    if not documents:
        suggestions.append("先导入 2-3 份项目文档、简历或学习笔记，建立可问答资料源。")
    if low_quality:
        suggestions.append("优先重建或替换质量分低于 70 的文档，减少低质量证据干扰。")
    if total_chunks and total_chunks < 8:
        suggestions.append("当前 chunk 数较少，适合问答演示，但还不足以体现大规模知识库能力。")
    if not history:
        suggestions.append("运行几次真实问答后，可用历史问题反推知识库缺口。")
    if not suggestions:
        suggestions.append("知识库结构健康，可继续补评测集、反馈闭环和作品集演示材料。")

    return {
        "document_count": len(documents),
        "chunk_count": total_chunks,
        "char_count": total_chars,
        "avg_quality_score": avg_quality,
        "quality_distribution": {
            "excellent": sum(1 for item in quality_reports if item["score"] >= 85),
            "usable": sum(1 for item in quality_reports if 70 <= item["score"] < 85),
            "needs_work": sum(1 for item in quality_reports if item["score"] < 70),
        },
        "themes": themes[:12],
        "recent_questions": recent_questions,
        "low_quality_documents": low_quality[:5],
        "suggestions": suggestions[:5],
        "updated_at": datetime.utcnow().isoformat(),
    }


def _quality_from_metadata(document: Document, chunks: list[Chunk]) -> dict:
    quality = document.metadata.get("quality")
    if isinstance(quality, dict) and "score" in quality:
        return quality
    return assess_document_quality(document, chunks)


def _quality_level(score: int) -> str:
    if score >= 85:
        return "excellent"
    if score >= 70:
        return "usable"
    if score >= 50:
        return "needs_review"
    return "poor"


def _signal(level: str, message: str, delta: int) -> dict:
    return {"level": level, "message": message, "delta": delta}


def _weird_char_ratio(text: str) -> float:
    if not text:
        return 0.0
    weird = sum(1 for char in text if char == "\ufffd" or (ord(char) < 32 and char not in "\n\t\r"))
    return weird / max(len(text), 1)


def _duplicate_chunk_ratio(chunks: list[Chunk]) -> float:
    if not chunks:
        return 0.0
    normalized = [" ".join(chunk.text.split()).lower() for chunk in chunks]
    unique = len(set(normalized))
    return 1 - unique / max(len(chunks), 1)


def _keywords(text: str) -> list[str]:
    tokens = [token for token in tokenize(text) if len(token) >= 2]
    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    return [item for item, _ in sorted(counts.items(), key=lambda row: (-row[1], row[0]))[:16]]


def _overview_themes(documents: list[Document]) -> list[str]:
    parts = []
    for doc in documents:
        summary = doc.metadata.get("summary")
        concepts = summary.get("key_concepts", []) if isinstance(summary, dict) else []
        parts.append(" ".join([doc.title or "", doc.file_name, " ".join(str(item) for item in concepts)]))
    joined = "\n".join(
        parts
    )
    return _keywords(joined)


def _first_sentence(text: str) -> str:
    parts = re.split(r"(?<=[。.!?？])\s+|\n+", text.strip())
    for part in parts:
        cleaned = part.strip(" #*-")
        if len(cleaned) >= 12:
            return cleaned
    return text[:120].strip()


def _truncate(text: str, limit: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[:limit].rstrip()}..."
