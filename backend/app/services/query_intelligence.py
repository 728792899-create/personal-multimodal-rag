from __future__ import annotations

from app.services.text_utils import tokenize


INTENT_RULES = [
    ("resume", "简历表达", {"简历", "bullet", "经历", "亮点", "岗位", "jd", "求职"}),
    ("interview", "面试回答", {"面试", "追问", "回答", "讲", "技术故事", "难点"}),
    ("summary", "总结归纳", {"总结", "概括", "梳理", "归纳", "核心", "一句话"}),
    ("comparison", "对比分析", {"对比", "比较", "区别", "差异", "优劣", "哪个"}),
    ("gap", "资料缺口", {"缺", "没有", "不足", "风险", "优化", "补充"}),
    ("fact", "事实定位", {"有没有", "是否", "哪里", "哪一页", "提到"}),
]


def analyze_query(query: str) -> dict:
    lowered = query.lower()
    tokens = set(tokenize(query))
    scored = []
    for intent_id, label, keywords in INTENT_RULES:
        hit_terms = sorted([term for term in keywords if term in lowered or term in tokens])
        if hit_terms:
            scored.append((len(hit_terms), intent_id, label, hit_terms))
    if scored:
        scored.sort(reverse=True)
        _, intent_id, label, hit_terms = scored[0]
    else:
        intent_id, label, hit_terms = "qa", "知识问答", []

    profile = _recommended_profile(intent_id, len(tokens))
    return {
        "intent": intent_id,
        "label": label,
        "matched_terms": hit_terms,
        "query_terms": sorted(tokens)[:16],
        "recommended": profile,
    }


def _recommended_profile(intent_id: str, token_count: int) -> dict:
    if intent_id in {"fact", "resume"}:
        return {
            "search_profile": "precision",
            "search_mode": "hybrid",
            "candidate_k": 24,
            "reason": "事实定位和简历表达更依赖精准证据，优先减少弱相关片段。",
        }
    if intent_id in {"summary", "comparison", "gap"}:
        return {
            "search_profile": "recall",
            "search_mode": "hybrid",
            "candidate_k": 48,
            "reason": "总结、对比和缺口分析需要覆盖更多资料，优先扩大召回。",
        }
    if token_count <= 2:
        return {
            "search_profile": "precision",
            "search_mode": "keyword",
            "candidate_k": 16,
            "reason": "短问题容易语义漂移，先用关键词锁定证据。",
        }
    return {
        "search_profile": "balanced",
        "search_mode": "hybrid",
        "candidate_k": 24,
        "reason": "默认使用混合检索，在召回和准确性之间保持平衡。",
    }
