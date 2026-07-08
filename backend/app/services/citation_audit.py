from __future__ import annotations

import re


def audit_answer(
    answer: str,
    citations: list[dict],
    confidence: float,
    threshold: float,
) -> dict:
    sentences = _answer_sentences(answer)
    citation_names = [str(item.get("filename", "")) for item in citations if item.get("filename")]
    supported = []
    unsupported = []

    for sentence in sentences:
        if _has_citation_marker(sentence, citation_names):
            supported.append(sentence)
        else:
            unsupported.append(sentence)

    coverage = len(supported) / len(sentences) if sentences else 0.0
    top_score = max((float(item.get("rerank_score") or item.get("score") or 0) for item in citations), default=0.0)
    source_count = len({item.get("document_id") or item.get("filename") for item in citations})
    label, reason = _trust_label(
        confidence=confidence,
        threshold=threshold,
        evidence_count=len(citations),
        source_count=source_count,
        coverage=coverage,
    )

    recommendations = []
    if not citations:
        recommendations.append("补充相关资料或扩大文档范围后再提问。")
    if coverage < 0.6 and answer:
        recommendations.append("要求模型重新生成，并强制每个关键结论标注引用编号。")
    if source_count <= 1 and len(citations) >= 2:
        recommendations.append("尝试扩大候选池，获取来自不同文档的互证证据。")
    if confidence < max(threshold, 0.12):
        recommendations.append("降低问题范围或补充更直接的资料，避免弱相关证据导致幻觉。")
    if not recommendations:
        recommendations.append("当前回答具备可追溯证据，可继续查看引用上下文。")

    return {
        "trust": {
            "level": label["level"],
            "label": label["text"],
            "reason": reason,
            "evidence_count": len(citations),
            "source_count": source_count,
            "top_score": round(top_score, 4),
            "confidence": round(confidence, 4),
            "coverage": round(coverage, 4),
            "recommendations": recommendations[:4],
        },
        "citation_audit": {
            "coverage": round(coverage, 4),
            "sentence_count": len(sentences),
            "supported_sentence_count": len(supported),
            "unsupported_sentence_count": len(unsupported),
            "unsupported_claims": unsupported[:6],
            "checked": True,
        },
    }


def _trust_label(
    confidence: float,
    threshold: float,
    evidence_count: int,
    source_count: int,
    coverage: float,
) -> tuple[dict, str]:
    if evidence_count == 0 or confidence < threshold:
        return (
            {"level": "unknown", "text": "无法确定"},
            "没有达到拒答阈值的可用证据。",
        )
    if confidence >= 0.35 and evidence_count >= 3 and coverage >= 0.65:
        return (
            {"level": "strong", "text": "证据充分"},
            "检索分数、证据数量和引用覆盖率均较好。",
        )
    if confidence >= 0.16 and evidence_count >= 2 and coverage >= 0.45:
        return (
            {"level": "medium", "text": "证据一般"},
            "已有可用证据，但仍建议查看引用上下文。",
        )
    return (
        {"level": "weak", "text": "证据较弱"},
        "证据数量、分数或引用覆盖率偏低，回答需要谨慎使用。",
    )


def _answer_sentences(answer: str) -> list[str]:
    candidates: list[str] = []
    for line in answer.splitlines():
        cleaned = line.strip()
        if not cleaned or cleaned in {"答案：", "依据：", "不确定性：", "后续建议："}:
            continue
        pieces = re.split(r"(?<=[。.!?？])\s+", cleaned)
        for piece in pieces:
            normalized = piece.strip()
            if len(normalized) >= 8:
                candidates.append(normalized)
    return candidates


def _has_citation_marker(sentence: str, citation_names: list[str]) -> bool:
    if re.search(r"\[\d+\]", sentence):
        return True
    if re.search(r"(chunk\s*\d+|第\s*\d+\s*页|片段\s*\d+)", sentence, flags=re.IGNORECASE):
        return True
    return any(name and name in sentence for name in citation_names)
