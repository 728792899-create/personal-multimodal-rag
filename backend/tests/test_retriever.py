from pathlib import Path
from contextlib import contextmanager

import pytest
from pydantic import ValidationError

from app.services.document_processor import DocumentProcessor
from app.services.embeddings import BaseEmbeddingProvider
from app.services.embeddings import MockEmbeddingProvider
from app.models.domain import Chunk
from app.models.schemas import SearchRequest
from app.services.retrieval_planner import RetrievalPlanner
from app.services.retriever import HybridRetriever
from app.services.vectorstore import MemoryVectorStore


def test_mock_embedding_is_stable():
    provider = MockEmbeddingProvider(vector_dim=32)

    assert provider.embed_text("RAG 检索") == provider.embed_text("RAG 检索")
    assert len(provider.embed_text("RAG 检索")) == 32


def test_hybrid_retriever_search_and_delete(tmp_path: Path):
    file_path = tmp_path / "rag.md"
    file_path.write_text("RAG 召回优化需要结合 BM25、向量检索和 Rerank。", encoding="utf-8")
    processor = DocumentProcessor()
    document = processor.parse_file(file_path)
    chunks = processor.split(document)

    retriever = HybridRetriever()
    retriever.add_document(document, chunks)
    results, trace = retriever.search("BM25 向量检索", top_k=3)

    assert trace["total_chunks"] == len(chunks)
    assert trace["reranker"] == "keyword"
    assert trace["bm25_candidates"] >= 1
    assert trace["vector_candidates"] >= 1
    assert trace["pipeline"]["mmr"]["selected"] == trace["mmr_selected"]
    assert trace["pipeline"]["retrieval_health"]["status"] == "skipped"
    assert (
        trace["pipeline"]["retrieval_health"]["exclude_reason"]
        == "fewer_than_three_candidates"
    )
    assert trace["plan"]["routing_mode"] == "manual"
    assert trace["plan"]["applied"] is False
    assert {"index_version", "degraded", "fallbacks"} <= set(trace["plan"])
    assert results
    assert "rerank_score" in results[0]
    assert results[0]["chunk"].document_id == document.document_id

    assert retriever.delete_document(document.document_id) is True
    results_after_delete, trace_after_delete = retriever.search("BM25", top_k=3)
    assert results_after_delete == []
    assert trace_after_delete["total_chunks"] == 0


def test_retriever_emits_bounded_leaf_retrieval_health_trace():
    processor = DocumentProcessor()
    retriever = HybridRetriever(index_version="test-index")
    for index in range(3):
        document = processor.parse_text_source(
            f"Common retrieval evidence with distinct source {index}.",
            f"source-{index}.md",
        )
        retriever.add_document(document, processor.split(document))

    results, trace = retriever.search(
        "common retrieval evidence",
        top_k=3,
        query_rewrite=False,
        rerank_enabled=False,
    )

    health = trace["pipeline"]["retrieval_health"]
    assert len(results) == 3
    assert health["version"] == "retrieval-health-v1"
    assert health["eligible"] is True
    assert health["status"] in {"healthy", "insufficient_history", "warning"}
    assert health["cross_query"]["current_top_ids"] == [
        item["chunk"].chunk_id for item in results
    ]
    assert health["history"]["capacity"] == 128


def test_single_document_scope_does_not_raise_document_diversity_warning():
    processor = DocumentProcessor()
    document = processor.parse_text_source("single scoped source", "single.md")
    chunks = [
        Chunk(
            chunk_id=f"{document.document_id}:{index}",
            document_id=document.document_id,
            chunk_index=index,
            text=f"scoped retrieval evidence section {index}",
            file_name=document.file_name,
        )
        for index in range(3)
    ]
    retriever = HybridRetriever()
    retriever.add_document(document, chunks)

    results, trace = retriever.search(
        "scoped retrieval evidence",
        top_k=3,
        document_ids=[document.document_id],
        query_rewrite=False,
        rerank_enabled=False,
    )

    assert len(results) == 3
    alert_codes = {
        alert["code"]
        for alert in trace["pipeline"]["retrieval_health"]["alerts"]
    }
    assert "low_document_diversity" not in alert_codes


def test_retrieval_health_scope_separates_manual_retrieval_configurations():
    class RecordingMonitor:
        def __init__(self):
            self.scope_keys = []

        def diagnose(self, *_args, scope_key, **_kwargs):
            self.scope_keys.append(scope_key)
            return {
                "version": "retrieval-health-v1",
                "status": "insufficient_history",
                "eligible": True,
                "alerts": [],
            }

    monitor = RecordingMonitor()
    retriever = HybridRetriever(retrieval_health_monitor=monitor)

    retriever.search("configuration", search_mode="keyword", rerank_enabled=False)
    retriever.search("configuration", search_mode="semantic", rerank_enabled=False)

    assert len(monitor.scope_keys) == 2
    assert monitor.scope_keys[0] != monitor.scope_keys[1]


def test_retriever_supports_modes_and_document_filter(tmp_path: Path):
    processor = DocumentProcessor()
    first_path = tmp_path / "rag.md"
    second_path = tmp_path / "frontend.md"
    first_path.write_text("RAG 使用 BM25、向量检索和引用证据降低幻觉。", encoding="utf-8")
    second_path.write_text("Vue 前端工作台关注组件状态、交互反馈和响应式布局。", encoding="utf-8")

    first_doc = processor.parse_file(first_path)
    second_doc = processor.parse_file(second_path)
    retriever = HybridRetriever()
    retriever.add_document(first_doc, processor.split(first_doc))
    retriever.add_document(second_doc, processor.split(second_doc))

    keyword_results, keyword_trace = retriever.search("Vue 组件状态", top_k=3, search_mode="keyword")
    assert keyword_results
    assert keyword_trace["search_mode"] == "keyword"
    assert keyword_trace["bm25_weight"] == 1.0
    assert keyword_trace["vector_weight"] == 0.0

    filtered_results, filtered_trace = retriever.search(
        "Vue 组件状态",
        top_k=3,
        document_ids=[first_doc.document_id],
        search_profile="precision",
        query_rewrite=False,
    )
    assert filtered_trace["document_ids"] == [first_doc.document_id]
    assert filtered_trace["query_rewriter"] == "off"
    assert all(item["chunk"].document_id == first_doc.document_id for item in filtered_results)


def test_retriever_falls_back_when_reranker_fails(tmp_path: Path):
    class BrokenReranker:
        name = "broken"

        def rerank(self, question: str, candidates: list[dict], top_k: int) -> list[dict]:
            raise RuntimeError("reranker unavailable")

    file_path = tmp_path / "rag.md"
    file_path.write_text("RAG 召回优化需要稳定的 fallback 机制。", encoding="utf-8")
    processor = DocumentProcessor()
    document = processor.parse_file(file_path)
    retriever = HybridRetriever(reranker=BrokenReranker())
    retriever.add_document(document, processor.split(document))

    results, trace = retriever.search("RAG fallback", top_k=3)

    assert results
    assert trace["rerank_status"] == "fallback"
    assert trace["fallbacks"][0]["stage"] == "rerank"
    assert trace["fallbacks"][0]["reason"] == "Rerank 暂时不可用，已使用基础相关性排序。"
    assert "reranker unavailable" not in str(trace)
    assert "rerank_score" in results[0]


def test_embedding_failure_blocks_legacy_semantic_but_allows_manual_exact(tmp_path: Path):
    class BrokenEmbeddingProvider(BaseEmbeddingProvider):
        def embed_text(self, text: str) -> list[float]:
            raise RuntimeError("embedding unavailable")

        def embed_batch(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("embedding unavailable")

    file_path = tmp_path / "rag.md"
    file_path.write_text(
        "RAG 召回优化需要结合关键词检索和向量检索。文档编号是 ZX-42。",
        encoding="utf-8",
    )
    processor = DocumentProcessor()
    document = processor.parse_file(file_path)
    retriever = HybridRetriever()
    retriever.add_document(document, processor.split(document))
    retriever.embedding_provider = BrokenEmbeddingProvider()

    # routing_mode omitted models an old client and therefore exercises the
    # legacy/manual path.  Semantic intent must still fail closed.
    blocked_results, blocked_trace = retriever.search(
        "如何改善 RAG 召回质量？", top_k=3, search_mode="semantic"
    )
    exact_results, exact_trace = retriever.search(
        "ZX-42 的编号是什么？",
        top_k=3,
        search_mode="semantic",
        routing_mode="manual",
    )

    assert blocked_results == []
    assert blocked_trace["plan"]["routing_mode"] == "manual"
    assert blocked_trace["vector_status"] == "blocked"
    assert blocked_trace["block"]["code"] == "embedding_unavailable"
    assert exact_results
    assert exact_trace["query_analysis"]["route"] == "exact"
    assert exact_trace["vector_status"] == "fallback"
    assert exact_trace["bm25_weight"] == 1.0
    assert exact_trace["vector_weight"] == 0.0
    assert exact_trace["fallbacks"][0]["reason"] == "向量检索暂时不可用，已回退到 BM25 关键词检索。"
    assert "embedding unavailable" not in str(blocked_trace)
    assert "embedding unavailable" not in str(exact_trace)


def test_retrieval_options_keep_legacy_manual_default():
    legacy = SearchRequest(query="RAG 检索")
    automatic = SearchRequest(query="RAG 检索", routing_mode="auto")

    assert legacy.routing_mode == "manual"
    assert automatic.routing_mode == "auto"


def test_retrieval_scope_filters_are_size_bounded():
    with pytest.raises(ValidationError):
        SearchRequest(query="RAG", document_ids=[str(index) for index in range(201)])
    with pytest.raises(ValidationError):
        SearchRequest(query="RAG", knowledge_base_ids=["x" * 161])


def test_auto_exact_can_degrade_to_bm25_but_semantic_is_blocked(tmp_path: Path):
    class BrokenEmbeddingProvider(BaseEmbeddingProvider):
        def embed_text(self, text: str) -> list[float]:
            raise RuntimeError("embedding secret must not leak")

        def embed_batch(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("embedding secret must not leak")

    file_path = tmp_path / "policy.md"
    file_path.write_text("第 12 页的编号是 ZX-42，用于高置信事实定位。", encoding="utf-8")
    processor = DocumentProcessor()
    document = processor.parse_file(file_path)
    retriever = HybridRetriever()
    retriever.add_document(document, processor.split(document))
    retriever.embedding_provider = BrokenEmbeddingProvider()

    exact_results, exact_trace = retriever.search(
        "ZX-42 的编号是什么？",
        routing_mode="auto",
    )
    semantic_results, semantic_trace = retriever.search(
        "如何改善这套检索体验？",
        routing_mode="auto",
    )

    assert exact_results
    assert exact_trace["plan"]["route"] == "exact"
    assert exact_trace["blocked"] is False
    assert exact_trace["vector_status"] == "fallback"
    assert exact_trace["bm25_weight"] == 1.0
    assert semantic_results == []
    assert semantic_trace["plan"]["route"] == "semantic"
    assert semantic_trace["blocked"] is True
    assert semantic_trace["block"]["code"] == "embedding_unavailable"
    assert "secret" not in str(semantic_trace)


def test_structured_planner_cannot_promote_semantic_intent_to_exact_bm25_fallback(
    tmp_path: Path,
):
    class BrokenEmbeddingProvider(BaseEmbeddingProvider):
        def embed_text(self, text: str) -> list[float]:
            raise RuntimeError("embedding unavailable")

        def embed_batch(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("embedding unavailable")

    class UnsafeExactPlannerClient:
        def create_json(self, prompt: str):
            return {
                "route": "exact",
                "confidence": 0.99,
                "decision_factors": ["structured_planner", "exact_fact_request"],
                "subqueries": [],
            }

    processor = DocumentProcessor()
    document = processor.parse_text_source("检索质量优化建议", "semantic.md")
    retriever = HybridRetriever(
        retrieval_planner=RetrievalPlanner(
            UnsafeExactPlannerClient(), deterministic_threshold=0.99
        )
    )
    retriever.add_document(document, processor.split(document))
    retriever.embedding_provider = BrokenEmbeddingProvider()

    results, trace = retriever.search("如何改善检索质量？", routing_mode="auto")

    assert trace["plan"]["route"] == "exact"
    assert trace["query_analysis"]["route"] == "semantic"
    assert results == []
    assert trace["blocked"] is True
    assert trace["block"]["code"] == "embedding_unavailable"


def test_planner_failure_executes_only_original_balanced_hybrid_query(tmp_path: Path):
    class InvalidPlannerClient:
        def create_text(self, prompt: str):
            return "not-json"

    class ForbiddenQueryRewriter:
        name = "forbidden"

        def rewrite(self, query: str):
            raise AssertionError("planner fallback must not rewrite")

    class ForbiddenReranker:
        name = "forbidden"

        def rerank(self, question: str, candidates: list[dict], top_k: int):
            raise AssertionError("planner fallback must not rerank")

    class ForbiddenGraphStore:
        def search(self, *args, **kwargs):
            raise AssertionError("planner fallback must not query graph")

    processor = DocumentProcessor()
    document = processor.parse_text_source(
        "方案 Alpha 和方案 Beta 的对比证据。", "compare.md"
    )
    retriever = HybridRetriever(
        retrieval_planner=RetrievalPlanner(
            InvalidPlannerClient(), deterministic_threshold=0.99
        ),
        query_rewriter=ForbiddenQueryRewriter(),
        reranker=ForbiddenReranker(),
        graph_store=ForbiddenGraphStore(),
    )
    retriever.add_document(document, processor.split(document))
    query = "比较方案 Alpha 和方案 Beta"

    results, trace = retriever.search(query, routing_mode="auto")

    assert results
    assert trace["rewritten_queries"] == [query]
    assert trace["rewrite_status"] == "disabled"
    assert trace["strategy"] == "hybrid"
    assert "graph" not in trace["pipeline"]
    assert trace["rerank_status"] == "skipped"
    assert trace["plan"]["source"] == "planner_fallback"
    assert trace["plan"]["fallbacks"][0]["action"] == "use_original_balanced_hybrid"


def test_auto_summary_requires_a_document_or_knowledge_base_scope(tmp_path: Path):
    file_path = tmp_path / "scope.md"
    file_path.write_text("这是一份需要在指定范围内总结的资料。", encoding="utf-8")
    processor = DocumentProcessor()
    document = processor.parse_file(file_path)
    retriever = HybridRetriever()
    retriever.add_document(document, processor.split(document))

    blocked_results, blocked_trace = retriever.search("总结这份文档", routing_mode="auto")
    scoped_results, scoped_trace = retriever.search(
        "总结这份文档",
        routing_mode="auto",
        document_ids=[document.document_id],
    )

    assert blocked_results == []
    assert blocked_trace["block"]["code"] == "summary_scope_required"
    assert scoped_trace["blocked"] is False
    assert scoped_results


def test_auto_composite_reranks_only_top_16_and_preserves_rrf_on_failure(tmp_path: Path):
    class RecordingReranker:
        name = "recording"

        def __init__(self):
            self.input_sizes = []

        def rerank(self, question: str, candidates: list[dict], top_k: int) -> list[dict]:
            self.input_sizes.append(len(candidates))
            raise RuntimeError("invalid structured rerank response")

    processor = DocumentProcessor()
    document = processor.parse_text_source("方案 alpha 和方案 beta 的对比资料", "compare.md")
    chunks = [
        Chunk(
            chunk_id=f"{document.document_id}:{index}",
            document_id=document.document_id,
            chunk_index=index,
            text=f"比较方案 alpha 和方案 beta 的指标 {index}",
            file_name=document.file_name,
        )
        for index in range(20)
    ]
    reranker = RecordingReranker()
    retriever = HybridRetriever(reranker=reranker)
    retriever.add_document(document, chunks)

    baseline, _ = retriever.search(
        "比较方案 alpha 和方案 beta",
        routing_mode="auto",
        top_k=10,
        rerank_enabled=False,
    )
    fallback, trace = retriever.search(
        "比较方案 alpha 和方案 beta",
        routing_mode="auto",
        top_k=10,
    )

    assert reranker.input_sizes == [16]
    assert trace["plan"]["route"] == "composite"
    assert trace["rerank_status"] == "fallback"
    assert [item["chunk"].chunk_id for item in fallback] == [
        item["chunk"].chunk_id for item in baseline
    ]
    assert trace["pipeline"]["fusion"]["algorithm"] == "weighted_rrf"


def test_persistent_sparse_store_is_not_fully_hydrated_on_retriever_startup():
    class PersistentStore:
        supports_persistent_sparse = True

        def list_chunks(self, **kwargs):
            raise AssertionError("persistent store must not hydrate all chunks")

        def count_chunks(self, **kwargs):
            return 0

        def sparse_search(self, query_tokens, **kwargs):
            return []

        def search(self, query_embedding, top_k=5, **kwargs):
            return []

        def add_chunks(self, chunks, embeddings):
            return None

        def delete_by_document_id(self, document_id):
            return None

        def has_document(self, document_id):
            return False

    retriever = HybridRetriever(vector_store=PersistentStore())

    assert retriever._chunk_cache == {}
    assert retriever.sparse_index.requires_hydration is False


def test_retrieval_and_parent_context_share_one_pinned_index_snapshot():
    leaf = Chunk(
        chunk_id="leaf:1",
        document_id="doc",
        chunk_index=0,
        text="pinned evidence",
        file_name="doc.md",
    )

    class PinningStore:
        supports_persistent_sparse = True

        def __init__(self):
            self.active = False
            self.last_sparse_search_stats = {
                "query_terms": 1,
                "posting_visits": 1,
                "evaluated_chunks": 1,
                "total_chunks": 1,
            }

        @contextmanager
        def pin_index(self):
            assert self.active is False
            self.active = True
            try:
                yield
            finally:
                self.active = False

        def count_chunks(self, **kwargs):
            assert self.active
            return 1

        def sparse_search(self, query_tokens, **kwargs):
            assert self.active
            return [{"chunk": leaf, "bm25_score": 2.0, "matched_terms": ["pinned"]}]

        def search(self, query_embedding, top_k=5, **kwargs):
            assert self.active
            return [{"chunk": leaf, "vector_score": 0.9}]

        def context_chunks(self, chunk_id, window=1):
            assert self.active
            return [leaf]

    store = PinningStore()
    retriever = HybridRetriever(vector_store=store)

    results, _trace = retriever.search("pinned", rerank_enabled=False)

    assert results[0]["parent_context"]["chunk_ids"] == [leaf.chunk_id]
    assert store.active is False


def test_graph_provenance_lookup_can_add_a_leaf_outside_base_candidates():
    graph_leaf = Chunk(
        chunk_id="graph:1",
        document_id="graph-doc",
        chunk_index=0,
        text="graph support",
        file_name="graph.md",
        element_ids=["element:bridge"],
        metadata={"knowledge_base_id": "team"},
    )

    class GraphLookupStore(MemoryVectorStore):
        def __init__(self):
            super().__init__()
            self.filters = None

        def chunks_by_element_ids(self, element_ids, **kwargs):
            self.filters = kwargs
            return [graph_leaf]

    store = GraphLookupStore()
    retriever = HybridRetriever(vector_store=store)
    candidates = {}

    ranking = retriever._graph_chunk_ranking(
        {"evidence_element_ids": ["element:bridge"]},
        candidates,
        set(),
        {"team"},
        {"text"},
    )

    assert ranking == [graph_leaf.chunk_id]
    assert candidates[graph_leaf.chunk_id] is graph_leaf
    assert store.filters["knowledge_base_ids"] == ["team"]
    assert store.filters["modalities"] == ["text"]
