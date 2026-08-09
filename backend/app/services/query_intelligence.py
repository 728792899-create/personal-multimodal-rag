from __future__ import annotations

import re

from app.services.text_utils import tokenize


SUMMARY_TERMS = {"总结", "概括", "梳理", "归纳", "摘要", "全文要点", "核心内容"}
COMPARISON_TERMS = {"对比", "比较", "区别", "差异", "优劣", "分别", "各自", "哪个更"}
MULTIHOP_TERMS = {"什么关系", "如何影响", "为什么导致", "导致", "因此", "依赖", "关系", "链路", "经过"}
EXACT_TERMS = {"多少", "什么时间", "哪一页", "哪页", "是否", "有没有", "谁", "哪里", "提到", "编号"}
MULTI_PART_CONNECTORS = ("分别", "同时", "以及", "并且")


def analyze_query(query: str) -> dict:
    """Return a safe, deterministic routing summary.

    Only predefined factors are returned. This object is suitable for a public
    retrieval trace and intentionally contains no free-form model reasoning.
    """

    cleaned = " ".join(query.strip().split())
    lowered = cleaned.lower()
    tokens = set(tokenize(cleaned))

    summary_hits = _hits(lowered, tokens, SUMMARY_TERMS)
    comparison_hits = _hits(lowered, tokens, COMPARISON_TERMS)
    multihop_hits = _hits(lowered, tokens, MULTIHOP_TERMS)
    exact_hits = _hits(lowered, tokens, EXACT_TERMS)

    quoted_or_identifier = bool(
        re.search(r"[“”\"《》][^\"“”《》]{1,80}[“”\"《》]", cleaned)
        or re.search(r"\b[A-Z]{2,}[\-_]?\d{1,}\b", cleaned)
        or re.search(r"\b\d{4}[-/.年]\d{1,2}(?:[-/.月]\d{1,2})?", cleaned)
        or re.search(r"第\s*\d+\s*(?:页|章|节|条)", cleaned)
    )
    multi_part = (
        cleaned.count("？") + cleaned.count("?") >= 2
        or _has_connector_before_question_mark(cleaned)
    )
    multi_entity_relation = bool(
        multihop_hits
        and re.search(r"\S{2,}\s*(?:与|和|到|对)\s*\S{2,}", cleaned)
    )

    if summary_hits:
        route, confidence = "summary", 0.94
        factors = ["explicit_summary"]
    elif comparison_hits or multi_part:
        route, confidence = "composite", 0.91 if comparison_hits else 0.86
        factors = ["comparison_operator" if comparison_hits else "multi_part_question"]
    elif multi_entity_relation or multihop_hits:
        route, confidence = "multihop", 0.9 if multi_entity_relation else 0.86
        factors = ["multi_entity_relation" if multi_entity_relation else "causal_chain"]
    elif quoted_or_identifier or exact_hits:
        route, confidence = "exact", 0.92 if quoted_or_identifier else 0.88
        factors = ["exact_identifier" if quoted_or_identifier else "exact_fact_request"]
    else:
        route, confidence = "semantic", 0.65
        factors = ["semantic_default"]

    legacy_intent, label = {
        "exact": ("fact", "事实定位"),
        "semantic": ("qa", "语义问答"),
        "composite": ("comparison", "对比与复合问题"),
        "multihop": ("implementation", "多跳关系推理"),
        "summary": ("summary", "总结归纳"),
    }[route]
    matched_terms = list(dict.fromkeys(summary_hits + comparison_hits + multihop_hits + exact_hits))
    return {
        "intent": legacy_intent,
        "label": label,
        "route": route,
        "confidence": confidence,
        "decision_factors": factors,
        "matched_terms": matched_terms[:12],
        "query_terms": sorted(tokens)[:16],
        "recommended": _recommended_profile(route),
    }


def _hits(lowered: str, tokens: set[str], terms: set[str]) -> list[str]:
    return sorted(term for term in terms if term in lowered or term in tokens)


def _has_connector_before_question_mark(text: str) -> bool:
    """Detect a multi-part connector followed by a question mark in linear time."""

    last_question_mark = max(text.rfind("?"), text.rfind("？"))
    if last_question_mark < 0:
        return False
    return any(
        text.find(connector, 0, last_question_mark) >= 0
        for connector in MULTI_PART_CONNECTORS
    )


def _recommended_profile(route: str) -> dict:
    if route == "exact":
        return {
            "search_profile": "precision",
            "search_mode": "hybrid",
            "candidate_k": 40,
            "reason_code": "exact_evidence",
        }
    if route in {"composite", "multihop", "summary"}:
        return {
            "search_profile": "recall",
            "search_mode": "hybrid",
            "candidate_k": 40,
            "reason_code": "coverage_required",
        }
    return {
        "search_profile": "balanced",
        "search_mode": "hybrid",
        "candidate_k": 40,
        "reason_code": "balanced_default",
    }
