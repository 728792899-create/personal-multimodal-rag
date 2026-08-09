from app.models.domain import Chunk
from app.services.retrieval_planner import RetrievalPlanner
from app.services.retriever import weighted_reciprocal_rank_fusion
from app.services.query_rewriter import DeepSeekQueryRewriter
from app.services.sparse_index import SparseBM25Index


def test_deterministic_routes_cover_the_five_public_route_types():
    planner = RetrievalPlanner()
    cases = {
        "第 12 页的编号是什么？": "exact",
        "RAG 怎样改善检索质量？": "semantic",
        "比较方案 A 和方案 B": "composite",
        "Alpha 与 Gamma 有什么关系？": "multihop",
        "总结这份文档": "summary",
    }

    for query, expected_route in cases.items():
        assert planner.plan(query).plan.route == expected_route


def test_ambiguous_query_uses_strict_structured_planner_and_invalid_output_falls_back():
    class ValidClient:
        def create_json(self, prompt: str):
            return {
                "route": "composite",
                "confidence": 0.82,
                "decision_factors": ["structured_planner", "multi_part_question"],
                "subqueries": ["问题一", "问题二"],
            }

    class InvalidClient:
        def create_json(self, prompt: str):
            return {
                "route": "unknown",
                "confidence": 9,
                "decision_factors": ["private_chain_of_thought"],
                "subqueries": [],
            }

    valid = RetrievalPlanner(ValidClient()).plan("请帮我分析这个问题")
    fallback = RetrievalPlanner(InvalidClient()).plan("请帮我分析这个问题")

    assert valid.plan.route == "composite"
    assert valid.plan.source == "structured"
    assert valid.plan.subqueries == ("问题一", "问题二")
    assert fallback.plan.route == "semantic"
    assert fallback.plan.source == "planner_fallback"
    assert fallback.plan.confidence == 0.0
    assert fallback.plan.subqueries == ()
    assert fallback.plan.modifiers["search_profile"] == "balanced"
    assert fallback.plan.modifiers["query_rewrite"] is False
    assert fallback.plan.modifiers["graph"] is False
    assert fallback.plan.modifiers["rerank_policy"] == "never"
    assert fallback.fallback["action"] == "use_original_balanced_hybrid"
    assert fallback.degraded is True
    assert "private_chain_of_thought" not in str(fallback)


def test_failed_low_confidence_planning_never_reuses_composite_modifiers():
    class InvalidClient:
        def create_text(self, prompt: str):
            return "not-json"

    outcome = RetrievalPlanner(
        InvalidClient(), deterministic_threshold=0.99
    ).plan("比较方案 Alpha 和方案 Beta")

    assert outcome.plan.route == "semantic"
    assert outcome.plan.source == "planner_fallback"
    assert outcome.plan.subqueries == ()
    assert outcome.plan.modifiers == {
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


def test_sparse_bm25_visits_only_matching_postings():
    index = SparseBM25Index()
    chunks = [
        Chunk(
            chunk_id=f"doc:{number}",
            document_id="doc",
            chunk_index=number,
            text="needle" if number == 17 else f"haystack{number}",
            file_name="data.md",
        )
        for number in range(50)
    ]
    index.add_chunks(chunks)

    hits = index.search(["needle"], top_k=10)

    assert [hit.chunk_id for hit in hits] == ["doc:17"]
    assert index.last_search_stats["evaluated_chunks"] == 1
    assert index.last_search_stats["total_chunks"] == 50


def test_weighted_rrf_uses_rank_and_channel_weight_not_raw_scores():
    scores, contributions = weighted_reciprocal_rank_fusion(
        [
            ("bm25:0", ["a", "b"], 0.7),
            ("dense:0", ["b", "a"], 0.3),
        ]
    )

    assert scores["a"] > scores["b"]
    assert contributions["a"]["bm25:0"]["rank"] == 1
    assert contributions["a"]["dense:0"]["rank"] == 2


def test_deepseek_query_rewriter_keeps_original_and_at_most_two_variants():
    class FakeClient:
        def create_text(self, prompt: str):
            assert "不得新增事实" in prompt
            return '```json\n{"queries":["检索变体一","检索变体二"]}\n```'

    rewritten = DeepSeekQueryRewriter(FakeClient()).rewrite("原始问题")

    assert rewritten == ["原始问题", "检索变体一", "检索变体二"]
