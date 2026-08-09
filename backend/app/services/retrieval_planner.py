from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from app.services.query_intelligence import analyze_query


RetrievalRoute = Literal["exact", "semantic", "composite", "multihop", "summary"]
ROUTES: tuple[RetrievalRoute, ...] = (
    "exact",
    "semantic",
    "composite",
    "multihop",
    "summary",
)

SAFE_DECISION_FACTORS = {
    "exact_identifier",
    "exact_fact_request",
    "explicit_summary",
    "comparison_operator",
    "multi_part_question",
    "multi_entity_relation",
    "causal_chain",
    "semantic_default",
    "structured_planner",
}


@dataclass(frozen=True)
class RetrievalPlan:
    route: RetrievalRoute
    confidence: float
    decision_factors: tuple[str, ...]
    subqueries: tuple[str, ...] = ()
    modifiers: dict[str, Any] = field(default_factory=dict)
    source: str = "rules"

    def to_trace(self) -> dict:
        return {
            "route": self.route,
            "confidence": round(float(self.confidence), 4),
            "decision_factors": list(self.decision_factors),
            "subqueries": list(self.subqueries),
            "modifiers": dict(self.modifiers),
            "source": self.source,
        }


@dataclass(frozen=True)
class PlanningOutcome:
    plan: RetrievalPlan
    degraded: bool = False
    fallback: dict | None = None


ROUTE_MODIFIERS: dict[RetrievalRoute, dict[str, Any]] = {
    "exact": {
        "search_mode": "hybrid",
        "search_profile": "precision",
        "bm25_weight": 0.7,
        "vector_weight": 0.3,
        "query_rewrite": False,
        "graph": False,
        "rerank_policy": "never",
        "derived_query_limit": 0,
        "branch_candidate_k": 40,
        "fusion_pool_k": 40,
        "final_k_cap": 8,
    },
    "semantic": {
        "search_mode": "hybrid",
        "search_profile": "balanced",
        "bm25_weight": 0.45,
        "vector_weight": 0.55,
        "query_rewrite": True,
        "graph": False,
        "rerank_policy": "low_overlap_or_conflict",
        "derived_query_limit": 2,
        "branch_candidate_k": 40,
        "fusion_pool_k": 40,
        "final_k_cap": 8,
    },
    "composite": {
        "search_mode": "hybrid",
        "search_profile": "recall",
        "bm25_weight": 0.5,
        "vector_weight": 0.5,
        "query_rewrite": True,
        "graph": False,
        "rerank_policy": "always",
        "derived_query_limit": 3,
        "branch_candidate_k": 40,
        "fusion_pool_k": 40,
        "final_k_cap": 10,
    },
    "multihop": {
        "search_mode": "hybrid",
        "search_profile": "recall",
        "bm25_weight": 0.45,
        "vector_weight": 0.55,
        "query_rewrite": True,
        "graph": True,
        "rerank_policy": "always",
        "derived_query_limit": 3,
        "branch_candidate_k": 40,
        "fusion_pool_k": 40,
        "final_k_cap": 10,
    },
    "summary": {
        "search_mode": "hybrid",
        "search_profile": "recall",
        "bm25_weight": 0.4,
        "vector_weight": 0.6,
        "query_rewrite": False,
        "graph": False,
        "rerank_policy": "never",
        "derived_query_limit": 0,
        "branch_candidate_k": 40,
        "fusion_pool_k": 40,
        "final_k_cap": 8,
        "requires_scope": True,
    },
}


# A planning outage must not inherit the tentative rule route.  In particular,
# retaining composite/multihop modifiers here could still trigger query
# expansion, graph traversal, or cloud reranking after the planner has failed.
SAFE_PLANNER_FALLBACK_MODIFIERS: dict[str, Any] = {
    "search_mode": "hybrid",
    "search_profile": "balanced",
    "bm25_weight": 0.5,
    "vector_weight": 0.5,
    "query_rewrite": False,
    "graph": False,
    "rerank_policy": "never",
    "derived_query_limit": 0,
    "branch_candidate_k": 40,
    "fusion_pool_k": 40,
    "final_k_cap": 8,
}


class RetrievalPlanner:
    """Deterministic-first planner with an optional strict JSON cloud adapter."""

    name = "deterministic-first"

    def __init__(self, client: Any | None = None, *, deterministic_threshold: float = 0.85):
        self.client = client
        self.deterministic_threshold = max(0.0, min(float(deterministic_threshold), 1.0))

    def plan(self, query: str, *, routing_mode: str = "auto") -> PlanningOutcome:
        rule_plan = self._rule_plan(query)
        if routing_mode != "auto":
            return PlanningOutcome(replace(rule_plan, source="manual"))
        if rule_plan.confidence >= self.deterministic_threshold:
            return PlanningOutcome(rule_plan)
        if self.client is None:
            return self._safe_fallback(
                "云端查询规划器未配置，已使用原问进行平衡混合检索。"
            )
        try:
            return PlanningOutcome(self._structured_plan(query))
        except Exception:
            return self._safe_fallback(
                "查询规划暂时不可用，已使用原问进行平衡混合检索。"
            )

    @staticmethod
    def _safe_fallback(reason: str) -> PlanningOutcome:
        return PlanningOutcome(
            RetrievalPlan(
                route="semantic",
                confidence=0.0,
                decision_factors=("semantic_default",),
                subqueries=(),
                modifiers=dict(SAFE_PLANNER_FALLBACK_MODIFIERS),
                source="planner_fallback",
            ),
            degraded=True,
            fallback={
                "stage": "query_planning",
                "reason": reason,
                "action": "use_original_balanced_hybrid",
            },
        )

    def _rule_plan(self, query: str) -> RetrievalPlan:
        analysis = analyze_query(query)
        route = analysis.get("route", "semantic")
        if route not in ROUTES:
            route = "semantic"
        factors = tuple(
            factor
            for factor in analysis.get("decision_factors", ["semantic_default"])
            if factor in SAFE_DECISION_FACTORS
        ) or ("semantic_default",)
        return RetrievalPlan(
            route=route,
            confidence=float(analysis.get("confidence", 0.65)),
            decision_factors=factors,
            subqueries=tuple(self._rule_subqueries(query, route)),
            modifiers=dict(ROUTE_MODIFIERS[route]),
            source="rules",
        )

    def _structured_plan(self, query: str) -> RetrievalPlan:
        prompt = (
            "你是知识库检索路由器。只输出 JSON 对象，不要解释。\n"
            "route 只能是 exact, semantic, composite, multihop, summary 之一。\n"
            "decision_factors 只能使用以下枚举："
            + ", ".join(sorted(SAFE_DECISION_FACTORS))
            + "。\n"
            "subqueries 最多 3 条，只用于拆解原问题，不得增加文档或知识库范围。\n"
            '格式：{"route":"semantic","confidence":0.8,'
            '"decision_factors":["semantic_default"],"subqueries":[]}\n'
            f"用户问题：{query}"
        )
        if hasattr(self.client, "create_json"):
            payload = self.client.create_json(prompt)
        elif hasattr(self.client, "create_text"):
            payload = self._parse_json(self.client.create_text(prompt))
        else:
            raise TypeError("planner client must provide create_json or create_text")
        if not isinstance(payload, dict):
            raise ValueError("planner output must be an object")
        route = payload.get("route")
        if route not in ROUTES:
            raise ValueError("planner returned an unsupported route")
        confidence = payload.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise ValueError("planner confidence must be numeric")
        if not 0 <= float(confidence) <= 1:
            raise ValueError("planner confidence is out of range")
        raw_factors = payload.get("decision_factors")
        if not isinstance(raw_factors, list) or not raw_factors:
            raise ValueError("planner decision factors are required")
        factors = tuple(dict.fromkeys(str(item) for item in raw_factors))
        if len(factors) > 8 or any(item not in SAFE_DECISION_FACTORS for item in factors):
            raise ValueError("planner returned unsafe decision factors")
        raw_subqueries = payload.get("subqueries", [])
        if not isinstance(raw_subqueries, list) or len(raw_subqueries) > 3:
            raise ValueError("planner subqueries are invalid")
        subqueries: list[str] = []
        for item in raw_subqueries:
            if not isinstance(item, str):
                raise ValueError("planner subquery must be text")
            cleaned = item.strip()
            if not cleaned or len(cleaned) > 500:
                raise ValueError("planner subquery length is invalid")
            if cleaned != query.strip() and cleaned not in subqueries:
                subqueries.append(cleaned)
        limit = int(ROUTE_MODIFIERS[route]["derived_query_limit"])
        return RetrievalPlan(
            route=route,
            confidence=float(confidence),
            decision_factors=factors,
            subqueries=tuple(subqueries[:limit]),
            modifiers=dict(ROUTE_MODIFIERS[route]),
            source="structured",
        )

    @staticmethod
    def _parse_json(text: str) -> dict:
        cleaned = str(text).strip()
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("planner returned invalid JSON")
            payload = json.loads(cleaned[start : end + 1])
        if not isinstance(payload, dict):
            raise ValueError("planner returned a non-object")
        return payload

    @staticmethod
    def _rule_subqueries(query: str, route: str) -> list[str]:
        if route not in {"composite", "multihop"}:
            return []
        parts = [
            item.strip(" ，,;；。?？")
            for item in re.split(r"(?:以及|并且|同时|分别|对比|比较|[;；]|与|和)", query)
        ]
        return list(dict.fromkeys(item for item in parts if len(item) >= 2 and item != query.strip()))[:3]
