from __future__ import annotations

import math
from statistics import mean

from app.models.domain import Document


def build_system_metrics(
    documents: list[Document],
    history: list[dict],
    feedback_stats: dict,
    operations: list[dict],
    chunk_count: int,
    index_jobs: list[dict] | None = None,
    conversation_metrics: dict | None = None,
    conversation_retrieval_traces: list[dict] | None = None,
) -> dict:
    index_jobs = index_jobs or []
    conversation_metrics = conversation_metrics or {}
    conversation_retrieval_traces = conversation_retrieval_traces or []
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
    modality_counts: dict[str, int] = {}
    enrichment_fallback_count = 0
    graph_node_count = 0
    graph_edge_count = 0
    for document in documents:
        for element in document.elements:
            modality_counts[element.type] = modality_counts.get(element.type, 0) + 1
            enrichment = element.metadata.get("enrichment")
            if isinstance(enrichment, dict) and enrichment.get("fallback"):
                enrichment_fallback_count += 1
        graph = document.metadata.get("graph")
        if isinstance(graph, dict):
            graph_node_count += int(graph.get("node_count") or 0)
            graph_edge_count += int(graph.get("edge_count") or 0)
    graph_hit_count = sum(
        1
        for item in history
        if item.get("retrieval_trace", {}).get("pipeline", {}).get("graph", {}).get("status") == "success"
    )
    retrieval_health = _retrieval_health_summary(
        history
        + [
            {"retrieval_trace": trace}
            for trace in conversation_retrieval_traces
            if isinstance(trace, dict)
        ]
    )

    return {
        "knowledge": {
            "document_count": len(documents),
            "chunk_count": chunk_count,
            "avg_quality_score": round(mean(quality_scores), 2) if quality_scores else 0,
            "low_quality_count": sum(1 for score in quality_scores if score < 70),
            "modality_counts": modality_counts,
        },
        "answering": {
            "history_count": len(history),
            "avg_confidence": round(mean(confidences), 4) if confidences else 0,
            "fallback_count": len(fallbacks),
            "no_answer_count": sum(1 for item in history if not item.get("citations")),
            "retrieval_health": retrieval_health,
            **conversation_metrics,
        },
        "ingestion": {
            "queue_depth": sum(1 for item in index_jobs if item.get("status") in {"queued", "running", "cancelling"}),
            "failed_count": sum(1 for item in index_jobs if item.get("status") == "failed"),
            "cancelled_count": sum(1 for item in index_jobs if item.get("status") == "cancelled"),
            "retry_count": sum(max(0, int(item.get("attempts", 0)) - 1) for item in index_jobs),
            "by_status": {
                status: sum(1 for item in index_jobs if item.get("status") == status)
                for status in ["queued", "running", "succeeded", "failed", "cancelling", "cancelled"]
            },
            "index_version_mismatch_count": sum(
                1 for document in documents if document.metadata.get("index_status") == "needs_rebuild"
            ),
            "parser_fallback_count": sum(
                1 for document in documents if document.metadata.get("parser_fallback_from")
            ),
            "enrichment_fallback_count": enrichment_fallback_count,
        },
        "graph": {
            "indexed_document_count": sum(1 for document in documents if isinstance(document.metadata.get("graph"), dict)),
            "node_count": graph_node_count,
            "edge_count": graph_edge_count,
            "retrieval_hit_count": graph_hit_count,
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
            retrieval_health=retrieval_health,
        ),
    }


def _retrieval_health_summary(history: list[dict]) -> dict:
    rows = [
        health
        for item in history
        if (
            health := (
                item.get("retrieval_trace", {})
                .get("pipeline", {})
                .get("retrieval_health")
            )
        )
    ]
    status_counts: dict[str, int] = {}
    alert_counts: dict[str, int] = {}
    cross_query_jaccards: list[float] = []
    channel_jaccards: list[float] = []
    for health in rows:
        status = str(health.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        if health.get("eligible") is not True:
            continue
        for alert in health.get("alerts") or []:
            code = str(alert.get("code") or "unknown")
            alert_counts[code] = alert_counts.get(code, 0) + 1
        _append_finite_ratio(
            cross_query_jaccards,
            (health.get("cross_query") or {}).get("mean_jaccard"),
        )
        _append_finite_ratio(
            channel_jaccards,
            (health.get("sparse_dense_top10") or {}).get("jaccard"),
        )
    eligible_statuses = [
        str(health.get("status") or "unknown")
        for health in rows
        if health.get("eligible") is True
    ]
    eligible_count = len(eligible_statuses)
    warning_count = status_counts.get("warning", 0)
    return {
        "status": (
            "no_data"
            if not rows
            else "warning"
            if warning_count
            else "insufficient_history"
            if eligible_count == 0
            or any(status != "healthy" for status in eligible_statuses)
            else "healthy"
        ),
        "observed_count": len(rows),
        "eligible_count": eligible_count,
        "warning_count": warning_count,
        "warning_rate": (
            round(warning_count / eligible_count, 4) if eligible_count else None
        ),
        "by_status": dict(sorted(status_counts.items())),
        "by_alert": dict(sorted(alert_counts.items())),
        "avg_cross_query_topk_jaccard": (
            round(mean(cross_query_jaccards), 4) if cross_query_jaccards else None
        ),
        "avg_sparse_dense_jaccard": (
            round(mean(channel_jaccards), 4) if channel_jaccards else None
        ),
    }


def _append_finite_ratio(target: list[float], value) -> None:
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and 0.0 <= float(value) <= 1.0
    ):
        target.append(float(value))


def _recommendations(
    document_count: int,
    chunk_count: int,
    low_quality_count: int,
    feedback_stats: dict,
    fallback_count: int,
    retrieval_health: dict,
) -> list[str]:
    items = []
    if document_count < 3:
        items.append("补充更多真实项目文档、技术方案、运维记录和复盘材料，提升知识库覆盖面。")
    if chunk_count < 20:
        items.append("当前 chunk 数偏少，建议导入更完整资料以体现复杂检索能力。")
    if low_quality_count:
        items.append("优先处理低质量文档，避免 OCR/乱码/过短 chunk 干扰答案。")
    if feedback_stats.get("negative", 0) > 0:
        items.append("将负反馈草稿跑成评测集，比较 precision/recall/rerank 策略。")
    if fallback_count:
        items.append("检查 fallback 发生环节，补齐 provider、向量库或 reranker 稳定性。")
    if retrieval_health.get("warning_count", 0):
        items.append("检查检索健康告警，重点排查万能块、跨问题高重合和通道失效。")
    elif retrieval_health.get("status") in {"no_data", "insufficient_history"}:
        items.append("继续积累代表性查询，样本充足后再判定检索健康度。")
    if not items:
        items.append("系统健康度良好，可以继续扩展多模态解析和外部资料导入。")
    return items[:6]
