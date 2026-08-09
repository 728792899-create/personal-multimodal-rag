from __future__ import annotations

import re

from app.services.text_utils import tokenize


GROUNDING_OVERLAP_THRESHOLD = 0.34
_CITATION_GROUP_RE = re.compile(r"\[\s*(\d+(?:\s*,\s*\d+)*)\s*\]")
_STRUCTURAL_HEADING_RE = re.compile(
    r"^(?:#{1,6}\s*)?(?:答案|依据|不确定性|后续建议)\s*[:：]?$"
)


def _citation_indexes(text: str) -> list[int]:
    indexes: list[int] = []
    for match in _CITATION_GROUP_RE.finditer(text):
        indexes.extend(int(value.strip()) for value in match.group(1).split(","))
    return indexes


def audit_answer(
    answer: str,
    citations: list[dict],
    confidence: float,
    threshold: float,
    overlap_threshold: float = GROUNDING_OVERLAP_THRESHOLD,
) -> dict:
    sentences = _answer_sentences(answer)
    citation_names = [str(item.get("filename", "")) for item in citations]
    supported = []
    unsupported = []
    grounded = []
    weakly_grounded_claims = []

    for sentence in sentences:
        citation_indexes, evidence_texts = _referenced_evidence(sentence, citations, citation_names)
        has_valid_reference = _has_valid_reference(
            sentence,
            citation_indexes,
            citation_count=len(citations),
        )
        if has_valid_reference:
            supported.append(sentence)
        else:
            unsupported.append(sentence)

        overlap = _best_token_overlap(sentence, evidence_texts) if has_valid_reference else 0.0
        if has_valid_reference and overlap >= overlap_threshold:
            grounded.append(sentence)
        elif has_valid_reference:
            weakly_grounded_claims.append(
                {
                    "sentence": sentence,
                    "claim": sentence,
                    "overlap": round(overlap, 4),
                    "citation_indexes": citation_indexes,
                    "reason": "cited_but_low_overlap",
                }
            )

    coverage = len(supported) / len(sentences) if sentences else 0.0
    grounding = len(grounded) / len(supported) if supported else 0.0
    top_score = max((float(item.get("rerank_score") or item.get("score") or 0) for item in citations), default=0.0)
    source_count = len({item.get("document_id") or item.get("filename") for item in citations})
    label, reason = _trust_label(
        confidence=confidence,
        threshold=threshold,
        evidence_count=len(citations),
        source_count=source_count,
        coverage=coverage,
        grounding=grounding,
    )

    recommendations = []
    if not citations:
        recommendations.append("补充相关资料或扩大文档范围后再提问。")
    if coverage < 0.6 and answer:
        recommendations.append("要求模型重新生成，并强制每个关键结论标注引用编号。")
    if weakly_grounded_claims:
        recommendations.append("检查引用编号是否指向了真正支持该结论的证据，并删除无法核实的表述。")
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
            "grounding": round(grounding, 4),
            "grounded_sentence_count": len(grounded),
            "weakly_grounded_claims": weakly_grounded_claims[:6],
            "grounding_overlap_threshold": round(overlap_threshold, 4),
            "checked": True,
        },
    }


def _trust_label(
    confidence: float,
    threshold: float,
    evidence_count: int,
    source_count: int,
    coverage: float,
    grounding: float,
) -> tuple[dict, str]:
    if evidence_count == 0 or confidence < threshold:
        return (
            {"level": "unknown", "text": "无法确定"},
            "没有达到拒答阈值的可用证据。",
        )
    if confidence >= 0.35 and evidence_count >= 3 and coverage >= 0.65 and grounding >= 0.65:
        return (
            {"level": "strong", "text": "证据充分"},
            "检索分数、证据数量、引用覆盖率和语义支持度均较好。",
        )
    if confidence >= 0.16 and evidence_count >= 2 and coverage >= 0.45 and grounding >= 0.45:
        return (
            {"level": "medium", "text": "证据一般"},
            "已有可用且语义相关的证据，但仍建议查看引用上下文。",
        )
    return (
        {"level": "weak", "text": "证据较弱"},
        "证据数量、分数、引用覆盖率或语义支持度偏低，回答需要谨慎使用。",
    )


def _answer_sentences(answer: str) -> list[str]:
    candidates: list[str] = []
    for line in answer.splitlines():
        cleaned = line.strip()
        if not cleaned or _STRUCTURAL_HEADING_RE.fullmatch(cleaned):
            continue
        for piece in _sentence_pieces(cleaned):
            normalized = piece.strip()
            if len(normalized) >= 8:
                candidates.append(normalized)
    return candidates


def _sentence_pieces(text: str) -> list[str]:
    pieces: list[str] = []
    start = 0
    cursor = 0
    while cursor < len(text):
        character = text[cursor]
        is_boundary = character in "。！？!?"
        if character == ".":
            following = text[cursor + 1 : cursor + 2]
            is_boundary = not following or following.isspace() or following == "["
        if not is_boundary:
            cursor += 1
            continue

        end = cursor + 1
        marker_cursor = end
        while marker_cursor < len(text):
            while marker_cursor < len(text) and text[marker_cursor].isspace():
                marker_cursor += 1
            marker = _CITATION_GROUP_RE.match(text, marker_cursor)
            if not marker:
                break
            end = marker.end()
            marker_cursor = end

        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        start = end
        cursor = end

    tail = text[start:].strip()
    if tail:
        pieces.append(tail)
    return pieces


def _has_valid_reference(
    sentence: str,
    citation_indexes: list[int],
    *,
    citation_count: int,
) -> bool:
    explicit_indexes = _citation_indexes(sentence)
    if explicit_indexes:
        return bool(explicit_indexes) and all(1 <= index <= citation_count for index in explicit_indexes)
    return bool(citation_indexes)


def _referenced_evidence(
    sentence: str,
    citations: list[dict],
    citation_names: list[str],
) -> tuple[list[int], list[str]]:
    citation_indexes = _citation_indexes(sentence)
    if citation_indexes:
        selected = [citations[index - 1] for index in citation_indexes if 1 <= index <= len(citations)]
        return citation_indexes, [_citation_text(item) for item in selected]

    matching_indexes = [
        index
        for index, name in enumerate(citation_names, start=1)
        if name and name in sentence
    ]
    if matching_indexes:
        selected = [citations[index - 1] for index in matching_indexes]
        return matching_indexes, [_citation_text(item) for item in selected]

    if re.search(r"(chunk\s*\d+|第\s*\d+\s*页|片段\s*\d+)", sentence, flags=re.IGNORECASE):
        return list(range(1, len(citations) + 1)), [_citation_text(item) for item in citations]
    return [], []


def _citation_text(citation: dict) -> str:
    parent_context = citation.get("parent_context") or {}
    return "\n".join(
        str(value)
        for value in (
            citation.get("text", ""),
            citation.get("snippet", ""),
            parent_context.get("text", "") if isinstance(parent_context, dict) else "",
        )
        if value
    )


def _best_token_overlap(sentence: str, evidence_texts: list[str]) -> float:
    claim_without_markers = _CITATION_GROUP_RE.sub("", sentence)
    claim_tokens = set(tokenize(claim_without_markers))
    if not claim_tokens or not evidence_texts:
        return 0.0
    return max(
        (len(claim_tokens & set(tokenize(text))) / len(claim_tokens) for text in evidence_texts),
        default=0.0,
    )
