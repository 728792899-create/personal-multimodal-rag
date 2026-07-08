from __future__ import annotations

from statistics import mean

from app.models.domain import Document


def build_system_metrics(
    documents: list[Document],
    history: list[dict],
    feedback_stats: dict,
    operations: list[dict],
    chunk_count: int,
) -> dict:
    quality_scores = []
    for document in documents:
        quality = document.metadata.get("quality")
        if isinstance(quality, dict) and isinstance(quality.get("score"), (int, float)):
            quality_scores.append(float(quality["score"]))

    confidences = [
        float(item["confidence"])
        for item in history
        if isinstance(item.get("confidence"), (int, float))
    ]
    fallbacks = [
        item
        for item in history
        if item.get("retrieval_trace", {}).get("fallbacks")
    ]
    operation_types: dict[str, int] = {}
    operation_levels: dict[str, int] = {}
    for operation in operations:
        event_type = operation.get("event_type") or "unknown"
        level = operation.get("level") or "info"
        operation_types[event_type] = operation_types.get(event_type, 0) + 1
        operation_levels[level] = operation_levels.get(level, 0) + 1

    return {
        "knowledge": {
            "document_count": len(documents),
            "chunk_count": chunk_count,
            "avg_quality_score": round(mean(quality_scores), 2) if quality_scores else 0,
            "low_quality_count": sum(1 for score in quality_scores if score < 70),
        },
        "answering": {
            "history_count": len(history),
            "avg_confidence": round(mean(confidences), 4) if confidences else 0,
            "fallback_count": len(fallbacks),
            "no_answer_count": sum(1 for item in history if not item.get("citations")),
        },
        "feedback": feedback_stats,
        "operations": {
            "total": len(operations),
            "by_type": operation_types,
            "by_level": operation_levels,
            "recent": operations[:8],
        },
        "recommendations": _recommendations(
            document_count=len(documents),
            chunk_count=chunk_count,
            low_quality_count=sum(1 for score in quality_scores if score < 70),
            feedback_stats=feedback_stats,
            fallback_count=len(fallbacks),
        ),
    }


def _recommendations(
    document_count: int,
    chunk_count: int,
    low_quality_count: int,
    feedback_stats: dict,
    fallback_count: int,
) -> list[str]:
    items = []
    if document_count < 3:
        items.append("补充更多真实项目文档、JD、面试复盘和技术方案，提升知识库覆盖面。")
    if chunk_count < 20:
        items.append("当前 chunk 数偏少，建议导入更完整资料以体现复杂检索能力。")
    if low_quality_count:
        items.append("优先处理低质量文档，避免 OCR/乱码/过短 chunk 干扰答案。")
    if feedback_stats.get("negative", 0) > 0:
        items.append("将负反馈草稿跑成评测集，比较 precision/recall/rerank 策略。")
    if fallback_count:
        items.append("检查 fallback 发生环节，补齐 provider、向量库或 reranker 稳定性。")
    if not items:
        items.append("系统健康度良好，可以继续扩展多模态解析和外部资料导入。")
    return items[:6]
