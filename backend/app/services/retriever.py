from __future__ import annotations

from collections import defaultdict
from contextlib import nullcontext
from functools import wraps
from typing import Any, Optional

from app.models.domain import Chunk, Document
from app.services.embeddings import BaseEmbeddingProvider, MockEmbeddingProvider
from app.services.query_intelligence import analyze_query
from app.services.query_rewriter import BaseQueryRewriter, NoopQueryRewriter
from app.services.reranker import BaseReranker, KeywordReranker
from app.services.retrieval_planner import RetrievalPlan, RetrievalPlanner
from app.services.safe_logging import public_error_message
from app.services.sparse_index import SparseBM25Index, VectorStoreSparseIndex
from app.services.text_utils import retrieval_tokens, tokenize
from app.services.vectorstore import BaseVectorStore, MemoryVectorStore


RRF_K = 60


def _pin_active_index(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        pin = getattr(self.vector_store, "pin_index", None)
        context = pin() if callable(pin) else nullcontext()
        with context:
            return method(self, *args, **kwargs)

    return wrapped


def weighted_reciprocal_rank_fusion(
    rankings: list[tuple[str, list[str], float]],
    *,
    k: int = RRF_K,
) -> tuple[dict[str, float], dict[str, dict[str, dict]]]:
    """Fuse ranked ids without mixing incomparable raw retrieval scores."""

    scores: dict[str, float] = defaultdict(float)
    contributions: dict[str, dict[str, dict]] = defaultdict(dict)
    for channel, ranked_ids, weight in rankings:
        if weight <= 0:
            continue
        seen: set[str] = set()
        rank = 0
        for candidate_id in ranked_ids:
            if not candidate_id or candidate_id in seen:
                continue
            seen.add(candidate_id)
            rank += 1
            contribution = (k + 1) * float(weight) / (k + rank)
            scores[candidate_id] += contribution
            contributions[candidate_id][channel] = {
                "rank": rank,
                "weight": round(float(weight), 6),
                "rrf": round(contribution, 6),
            }
    return dict(scores), {key: dict(value) for key, value in contributions.items()}


class HybridRetriever:
    def __init__(
        self,
        embedding_provider: Optional[BaseEmbeddingProvider] = None,
        vector_store: Optional[BaseVectorStore] = None,
        reranker: Optional[BaseReranker] = None,
        initial_retrieval_k: int = 24,
        embedding_provider_name: Optional[str] = None,
        embedding_model: str = "",
        vector_store_name: Optional[str] = None,
        query_rewriter: Optional[BaseQueryRewriter] = None,
        graph_store=None,
        mmr_lambda: float = 0.78,
        bm25_weight: float = 0.62,
        vector_weight: float = 0.38,
        embedding_batch_size: int = 32,
        retrieval_planner: Optional[RetrievalPlanner] = None,
        sparse_index: Any | None = None,
        index_version: str = "",
    ):
        self.embedding_provider = embedding_provider or MockEmbeddingProvider()
        self.vector_store = vector_store or MemoryVectorStore()
        self.reranker = reranker or KeywordReranker()
        self.query_rewriter = query_rewriter or NoopQueryRewriter()
        self.retrieval_planner = retrieval_planner or RetrievalPlanner()
        self.graph_store = graph_store
        self.initial_retrieval_k = initial_retrieval_k
        self.embedding_provider_name = embedding_provider_name or self.embedding_provider.__class__.__name__
        self.embedding_model = embedding_model
        self.vector_store_name = vector_store_name or self.vector_store.__class__.__name__
        self.index_version = index_version
        self.mmr_lambda = mmr_lambda
        self.bm25_weight = bm25_weight
        self.vector_weight = vector_weight
        self.embedding_batch_size = max(1, int(embedding_batch_size))
        self.documents: dict[str, Document] = {}
        self.sparse_index = sparse_index or self._default_sparse_index()
        self._persistent_sparse = not bool(
            getattr(self.sparse_index, "requires_hydration", True)
        )
        self._chunk_cache: dict[str, Chunk] = {}
        # Compatibility views used by older diagnostics.
        self.chunk_tokens = self.sparse_index.chunk_tokens
        self.doc_freq: dict[str, int] = {}
        self.avg_len = 0.0
        self._hydrate_chunk_tokens()

    def add_document(self, doc: Document, chunks: list[Chunk]) -> None:
        self.documents[doc.document_id] = doc
        embeddings: list[list[float]] = []
        texts = [self._embedding_text(doc, chunk) for chunk in chunks]
        for offset in range(0, len(texts), self.embedding_batch_size):
            embeddings.extend(
                self.embedding_provider.embed_batch(
                    texts[offset : offset + self.embedding_batch_size]
                )
            )
        self.vector_store.add_chunks(chunks, embeddings)
        if not self._persistent_sparse:
            for chunk in chunks:
                self._chunk_cache[chunk.chunk_id] = chunk
        self.sparse_index.add_chunks(chunks)
        self._sync_sparse_stats()

    def load_documents(self, documents: list[Document]) -> None:
        self.documents = {doc.document_id: doc for doc in documents}
        self._hydrate_chunk_tokens()

    def list_documents(self) -> list[dict]:
        return [
            {
                "id": doc.document_id,
                "filename": doc.file_name,
                "source_type": doc.file_type,
                "chunk_count": self._store_count(document_ids=[doc.document_id]),
                "char_count": len(doc.text),
                "metadata": doc.metadata,
            }
            for doc in self.documents.values()
        ]

    @_pin_active_index
    def search(
        self,
        query: str,
        top_k: int = 5,
        candidate_k: Optional[int] = None,
        search_mode: str = "hybrid",
        search_profile: str = "balanced",
        strategy: str = "hybrid",
        document_ids: Optional[list[str]] = None,
        knowledge_base_ids: Optional[list[str]] = None,
        bm25_weight: Optional[float] = None,
        vector_weight: Optional[float] = None,
        mmr_lambda: Optional[float] = None,
        min_score: Optional[float] = None,
        query_rewrite: bool = True,
        rerank_enabled: bool = True,
        graph_weight: float = 0.25,
        graph_max_hops: int = 2,
        modality_filters: Optional[list[str]] = None,
        parent_window: int = 1,
        routing_mode: str = "manual",
    ) -> tuple[list[dict], dict]:
        routing_mode = "auto" if routing_mode == "auto" else "manual"
        planning = self.retrieval_planner.plan(query, routing_mode=routing_mode)
        plan = planning.plan
        fallbacks: list[dict] = [planning.fallback] if planning.fallback else []
        degraded = bool(planning.degraded)
        blocked: dict | None = None

        document_filter = {item for item in (document_ids or []) if item}
        knowledge_base_filter = {item for item in (knowledge_base_ids or []) if item}
        modality_filter = {item for item in (modality_filters or []) if item}

        if routing_mode == "auto":
            modifiers = plan.modifiers
            search_mode = str(modifiers["search_mode"])
            search_profile = str(modifiers["search_profile"])
            bm25_weight = float(modifiers["bm25_weight"])
            vector_weight = float(modifiers["vector_weight"])
            query_rewrite = bool(modifiers["query_rewrite"])
            requested_strategy = "auto" if modifiers.get("graph") else "hybrid"
            graph_max_hops = 2 if plan.route == "multihop" else 1
            graph_weight = min(float(graph_weight), 0.15)
            if modifiers.get("requires_scope") and not (document_filter or knowledge_base_filter):
                blocked = {
                    "stage": "query_planning",
                    "code": "summary_scope_required",
                    "message": "总结查询必须指定文档或知识库范围。",
                    "retryable": False,
                }
        else:
            search_mode = search_mode if search_mode in {"hybrid", "keyword", "semantic"} else "hybrid"
            search_profile = search_profile if search_profile in {"balanced", "precision", "recall"} else "balanced"
            requested_strategy = strategy if strategy in {"hybrid", "hybrid_graph", "auto"} else "hybrid"

        active_bm25_weight, active_vector_weight = self._resolve_weights(
            search_mode, bm25_weight, vector_weight
        )
        active_mmr_lambda = self._resolve_mmr_lambda(search_profile, mmr_lambda)
        query_analysis = analyze_query(query)
        exact_bm25_fallback_allowed = (
            query_analysis.get("route") == "exact"
            and float(query_analysis.get("confidence", 0.0)) >= 0.85
        )
        chunk_map = self._filtered_chunk_map(
            document_filter, knowledge_base_filter, modality_filter
        )
        allowed_chunk_ids = set(chunk_map)
        use_allowed_filter = bool(document_filter or knowledge_base_filter or modality_filter)
        total_chunks = self._store_count()
        available_chunks = self._store_count(
            document_ids=sorted(document_filter) or None,
            knowledge_base_ids=sorted(knowledge_base_filter) or None,
            modalities=sorted(modality_filter) or None,
        )

        if routing_mode == "auto":
            branch_candidate_k = min(
                int(plan.modifiers.get("branch_candidate_k", 40)), available_chunks
            )
            fusion_pool_k = min(
                int(plan.modifiers.get("fusion_pool_k", 40)), available_chunks
            )
            output_k = min(top_k, int(plan.modifiers.get("final_k_cap", 8)))
            active_candidate_k = fusion_pool_k
            derived_query_limit = int(plan.modifiers.get("derived_query_limit", 0))
            # A planner may decompose a multihop question, but it must not invent
            # the second-hop entity. Multihop starts with the original query and
            # may add one provenance-bound query after first-hop retrieval.
            planned_subqueries = [] if plan.route == "multihop" else list(plan.subqueries)
        else:
            active_candidate_k = self._resolve_candidate_k(
                top_k=top_k,
                candidate_k=candidate_k,
                profile=search_profile,
                total_chunks=available_chunks,
            )
            branch_candidate_k = active_candidate_k
            fusion_pool_k = active_candidate_k
            output_k = top_k
            derived_query_limit = 3
            planned_subqueries = []

        try:
            rewritten_queries = self._prepare_queries(
                query,
                enabled=query_rewrite and not (
                    routing_mode == "auto" and plan.route == "multihop"
                ),
                planned_subqueries=planned_subqueries,
                derived_query_limit=derived_query_limit,
            )
            if routing_mode == "auto" and plan.route == "multihop":
                rewrite_status = "deferred_to_provenance_hop"
            elif not query_rewrite and not planned_subqueries:
                rewrite_status = "disabled"
            elif planned_subqueries and len(rewritten_queries) > 1:
                rewrite_status = "planned"
            else:
                rewrite_status = "success"
        except Exception as exc:
            rewritten_queries = [query]
            rewrite_status = "fallback"
            degraded = True
            fallbacks.append(
                {
                    "stage": "query_rewrite",
                    "reason": public_error_message(
                        exc,
                        "查询改写暂时不可用，已使用原始问题。",
                    ),
                    "action": "use_original_query",
                }
            )

        query_token_sets = [retrieval_tokens(item) for item in rewritten_queries]
        query_terms = sorted({token for tokens in query_token_sets for token in tokens})
        channel_rankings: list[dict] = []
        bm25_by_chunk: dict[str, float] = defaultdict(float)
        vector_by_chunk: dict[str, float] = defaultdict(float)
        matched_by_chunk: dict[str, set[str]] = defaultdict(set)
        sparse_posting_visits = 0
        sparse_evaluated: set[str] = set()

        if active_bm25_weight > 0 and branch_candidate_k > 0 and blocked is None:
            for branch, tokens in enumerate(query_token_sets):
                hits = self.sparse_index.search(
                    tokens,
                    top_k=branch_candidate_k,
                    allowed_chunk_ids=(
                        allowed_chunk_ids
                        if use_allowed_filter and not self._persistent_sparse
                        else None
                    ),
                    document_ids=sorted(document_filter) or None,
                    knowledge_base_ids=sorted(knowledge_base_filter) or None,
                    modalities=sorted(modality_filter) or None,
                )
                sparse_posting_visits += int(
                    self.sparse_index.last_search_stats["posting_visits"]
                )
                sparse_evaluated.update(hit.chunk_id for hit in hits)
                if hits:
                    channel_rankings.append(
                        {
                            "name": f"bm25:{branch}",
                            "kind": "bm25",
                            "ids": [hit.chunk_id for hit in hits],
                        }
                    )
                for hit in hits:
                    if hit.chunk is not None:
                        chunk_map[hit.chunk_id] = hit.chunk
                    bm25_by_chunk[hit.chunk_id] = max(
                        bm25_by_chunk[hit.chunk_id], hit.score
                    )
                    matched_by_chunk[hit.chunk_id].update(hit.matched_terms)

        vector_status = "skipped"
        if active_vector_weight > 0 and branch_candidate_k > 0 and blocked is None:
            try:
                query_vectors = self.embedding_provider.embed_batch(rewritten_queries)
                for branch, query_vector in enumerate(query_vectors):
                    rows = self._vector_search(
                        query_vector,
                        top_k=branch_candidate_k,
                        document_ids=sorted(document_filter) or None,
                        knowledge_base_ids=sorted(knowledge_base_filter) or None,
                        modalities=sorted(modality_filter) or None,
                    )
                    ranked_ids: list[str] = []
                    for row in rows:
                        chunk = row.get("chunk")
                        if not isinstance(chunk, Chunk) or not self._chunk_matches(
                            chunk, document_filter, knowledge_base_filter, modality_filter
                        ):
                            continue
                        if not self._persistent_sparse:
                            self._chunk_cache[chunk.chunk_id] = chunk
                        chunk_map[chunk.chunk_id] = chunk
                        ranked_ids.append(chunk.chunk_id)
                        vector_by_chunk[chunk.chunk_id] = max(
                            vector_by_chunk[chunk.chunk_id],
                            float(row.get("vector_score", 0.0)),
                        )
                    if ranked_ids:
                        channel_rankings.append(
                            {
                                "name": f"dense:{branch}",
                                "kind": "dense",
                                "ids": list(dict.fromkeys(ranked_ids)),
                            }
                        )
                vector_status = "success"
            except Exception as exc:
                vector_by_chunk.clear()
                channel_rankings = [
                    row for row in channel_rankings if row["kind"] != "dense"
                ]
                # Embedding failure is fail-closed for every client mode.  The
                # sole exception is a high-confidence exact intent established
                # by deterministic analysis of the original query; a manual or
                # structured plan cannot promote a semantic query into this
                # BM25-only escape hatch.
                if not exact_bm25_fallback_allowed:
                    vector_status = "blocked"
                    blocked = {
                        "stage": "vector_search",
                        "code": "embedding_unavailable",
                        "message": "语义检索暂时不可用，该查询不允许仅使用关键词给出结果。",
                        "retryable": True,
                    }
                    fallbacks.append(
                        {
                            "stage": "vector_search",
                            "reason": public_error_message(
                                exc, "语义检索暂时不可用。"
                            ),
                            "action": "block_unreliable_retrieval",
                        }
                    )
                else:
                    active_bm25_weight = 1.0
                    active_vector_weight = 0.0
                    vector_status = "fallback"
                    fallbacks.append(
                        {
                            "stage": "vector_search",
                            "reason": public_error_message(
                                exc,
                                "向量检索暂时不可用，已回退到 BM25 关键词检索。",
                            ),
                            "action": "fallback_to_keyword_bm25",
                        }
                    )
                    if not any(row["kind"] == "bm25" for row in channel_rankings):
                        for branch, tokens in enumerate(query_token_sets):
                            hits = self.sparse_index.search(
                                tokens,
                                top_k=branch_candidate_k,
                                allowed_chunk_ids=(
                                    allowed_chunk_ids
                                    if use_allowed_filter and not self._persistent_sparse
                                    else None
                                ),
                                document_ids=sorted(document_filter) or None,
                                knowledge_base_ids=sorted(knowledge_base_filter) or None,
                                modalities=sorted(modality_filter) or None,
                            )
                            sparse_posting_visits += int(
                                self.sparse_index.last_search_stats["posting_visits"]
                            )
                            sparse_evaluated.update(hit.chunk_id for hit in hits)
                            if hits:
                                channel_rankings.append(
                                    {
                                        "name": f"bm25:{branch}",
                                        "kind": "bm25",
                                        "ids": [hit.chunk_id for hit in hits],
                                    }
                                )
                            for hit in hits:
                                if hit.chunk is not None:
                                    chunk_map[hit.chunk_id] = hit.chunk
                                bm25_by_chunk[hit.chunk_id] = max(
                                    bm25_by_chunk[hit.chunk_id], hit.score
                                )
                                matched_by_chunk[hit.chunk_id].update(hit.matched_terms)
                degraded = True

        active_strategy = "hybrid"
        graph_result: dict | None = None
        graph_ranking: list[str] = []
        graph_reason = "not_requested"
        auto_multihop = routing_mode == "auto" and plan.route == "multihop"
        derived_hop: dict | None = None
        hop_candidate_ids: set[str] = set()
        hop_trace: list[dict] = [
            {
                "hop": 1,
                "query": query,
                "entity": None,
                "provenance": [],
                "status": "executed",
            }
        ] if auto_multihop else []
        if requested_strategy != "hybrid" and blocked is None:
            if self.graph_store is None:
                graph_reason = "store_unavailable"
                if auto_multihop:
                    degraded = True
                    fallbacks.append(
                        {
                            "stage": "graph_search",
                            "reason": "图检索暂时不可用，多跳证据链无法完成。",
                            "action": "block_incomplete_multihop",
                        }
                    )
            else:
                try:
                    graph_result = self.graph_store.search(
                        query,
                        knowledge_base_ids=sorted(knowledge_base_filter) or None,
                        max_hops=max(1, min(int(graph_max_hops), 2)),
                    )
                    if not isinstance(graph_result, dict):
                        raise ValueError("graph search returned an invalid result")
                except Exception as exc:
                    graph_result = None
                    graph_reason = "store_error"
                    degraded = True
                    fallbacks.append(
                        {
                            "stage": "graph_search",
                            "reason": public_error_message(
                                exc, "图检索暂时不可用。"
                            ),
                            "action": (
                                "block_incomplete_multihop"
                                if auto_multihop
                                else "skip_graph_channel"
                            ),
                        }
                    )
                if auto_multihop and graph_result is not None:
                    derived_hop = self._derive_multihop_query(
                        query=query,
                        graph_result=graph_result,
                        channel_rankings=channel_rankings,
                        chunks=chunk_map,
                        bm25_weight=active_bm25_weight,
                        vector_weight=active_vector_weight,
                    )
                    if derived_hop is None:
                        hop_trace.append(
                            {
                                "hop": 2,
                                "query": None,
                                "entity": None,
                                "provenance": [],
                                "status": "skipped_no_provenance_entity",
                            }
                        )
                    else:
                        hop_query = derived_hop["query"]
                        hop_trace.append(derived_hop)
                        rewritten_queries.append(hop_query)
                        hop_tokens = retrieval_tokens(hop_query)
                        query_token_sets.append(hop_tokens)
                        query_terms = sorted(set(query_terms) | set(hop_tokens))
                        hop_branch = len(rewritten_queries) - 1
                        if active_bm25_weight > 0:
                            hits = self.sparse_index.search(
                                hop_tokens,
                                top_k=branch_candidate_k,
                                allowed_chunk_ids=(
                                    allowed_chunk_ids
                                    if use_allowed_filter and not self._persistent_sparse
                                    else None
                                ),
                                document_ids=sorted(document_filter) or None,
                                knowledge_base_ids=sorted(knowledge_base_filter) or None,
                                modalities=sorted(modality_filter) or None,
                            )
                            sparse_posting_visits += int(
                                self.sparse_index.last_search_stats["posting_visits"]
                            )
                            sparse_evaluated.update(hit.chunk_id for hit in hits)
                            if hits:
                                channel_rankings.append(
                                    {
                                        "name": f"bm25:{hop_branch}",
                                        "kind": "bm25",
                                        "ids": [hit.chunk_id for hit in hits],
                                    }
                                )
                            for hit in hits:
                                hop_candidate_ids.add(hit.chunk_id)
                                if hit.chunk is not None:
                                    chunk_map[hit.chunk_id] = hit.chunk
                                bm25_by_chunk[hit.chunk_id] = max(
                                    bm25_by_chunk[hit.chunk_id], hit.score
                                )
                                matched_by_chunk[hit.chunk_id].update(hit.matched_terms)
                        if active_vector_weight > 0:
                            try:
                                hop_vector = self.embedding_provider.embed_batch([hop_query])[0]
                                rows = self._vector_search(
                                    hop_vector,
                                    top_k=branch_candidate_k,
                                    document_ids=sorted(document_filter) or None,
                                    knowledge_base_ids=sorted(knowledge_base_filter) or None,
                                    modalities=sorted(modality_filter) or None,
                                )
                                hop_ids: list[str] = []
                                for row in rows:
                                    chunk = row.get("chunk")
                                    if not isinstance(chunk, Chunk) or not self._chunk_matches(
                                        chunk,
                                        document_filter,
                                        knowledge_base_filter,
                                        modality_filter,
                                    ):
                                        continue
                                    chunk_map[chunk.chunk_id] = chunk
                                    hop_ids.append(chunk.chunk_id)
                                    vector_by_chunk[chunk.chunk_id] = max(
                                        vector_by_chunk[chunk.chunk_id],
                                        float(row.get("vector_score", 0.0)),
                                    )
                                if hop_ids:
                                    hop_candidate_ids.update(hop_ids)
                                    channel_rankings.append(
                                        {
                                            "name": f"dense:{hop_branch}",
                                            "kind": "dense",
                                            "ids": list(dict.fromkeys(hop_ids)),
                                        }
                                    )
                            except Exception as exc:
                                blocked = {
                                    "stage": "vector_search",
                                    "code": "embedding_unavailable",
                                    "message": "语义检索暂时不可用，多跳查询无法完成第二跳。",
                                    "retryable": True,
                                }
                                degraded = True
                                hop_trace[-1]["status"] = "blocked_embedding_unavailable"
                                fallbacks.append(
                                    {
                                        "stage": "vector_search",
                                        "reason": public_error_message(
                                            exc, "多跳语义检索暂时不可用。"
                                        ),
                                        "action": "block_incomplete_multihop",
                                    }
                                )
                if graph_result is not None:
                    graph_ranking = self._graph_chunk_ranking(
                        graph_result,
                        chunk_map,
                        document_filter,
                        knowledge_base_filter,
                        modality_filter,
                    )
                    eligible = bool(graph_result.get("eligible"))
                    graph_active = bool(graph_ranking) and (
                        requested_strategy == "hybrid_graph" or eligible
                    )
                    if graph_active:
                        active_strategy = "hybrid_graph"
                        graph_reason = "provenance_evidence_fused"
                        channel_rankings.append(
                            {"name": "graph", "kind": "graph", "ids": graph_ranking}
                        )
                    elif graph_result.get("evidence_element_ids") and not graph_ranking:
                        graph_reason = "stale_or_missing_provenance"
                        degraded = True
                        fallbacks.append(
                            {
                                "stage": "graph_search",
                                "reason": "图证据无法解析到当前索引，已跳过图通道。",
                                "action": "skip_graph_channel",
                            }
                        )
                    else:
                        graph_reason = "auto_gate_or_no_path"

        if auto_multihop and blocked is None:
            chain = self._multihop_chain_evidence(
                derived_hop=derived_hop,
                hop_candidate_ids=hop_candidate_ids,
                chunks=chunk_map,
            )
            if hop_trace and len(hop_trace) == 1:
                hop_trace.append(
                    {
                        "hop": 2,
                        "query": None,
                        "entity": None,
                        "provenance": [],
                        "status": "skipped_no_provenance_entity",
                    }
                )
            if not chain["complete"]:
                degraded = True
                hop_trace[-1].update(
                    {
                        "status": "blocked_incomplete_evidence",
                        "candidate_chunk_ids": chain["candidate_chunk_ids"],
                        "evidence_element_ids": chain["evidence_element_ids"],
                        "missing_evidence_element_ids": chain[
                            "missing_evidence_element_ids"
                        ],
                    }
                )
                blocked = {
                    "stage": "evidence_gate",
                    "code": "incomplete_multihop_evidence",
                    "message": "多跳查询没有取得完整、可验证的两跳证据链。",
                    "retryable": False,
                }
                fallbacks.append(
                    {
                        "stage": "evidence_gate",
                        "reason": "第二跳实体或 provenance 证据链不完整。",
                        "action": "block_incomplete_multihop",
                    }
                )
            else:
                hop_trace[-1].update(
                    {
                        "status": "complete",
                        "candidate_chunk_ids": chain["candidate_chunk_ids"],
                        "evidence_element_ids": chain["evidence_element_ids"],
                        "missing_evidence_element_ids": [],
                    }
                )

        fused_rows: list[dict] = []
        deduped: list[dict] = []
        candidates: list[dict] = []
        if blocked is None:
            weighted_rankings = self._weighted_channels(
                channel_rankings,
                bm25_weight=active_bm25_weight,
                vector_weight=active_vector_weight,
                graph_weight=min(max(float(graph_weight), 0.0), 0.15),
            )
            fused_scores, contributions = weighted_reciprocal_rank_fusion(
                weighted_rankings, k=RRF_K
            )
            for chunk_id, score in fused_scores.items():
                chunk = chunk_map.get(chunk_id) or self._chunk_cache.get(chunk_id)
                if chunk is None:
                    continue
                document_boost = self._document_boost(chunk.document_id)
                boosted_score = score * document_boost
                channel_contributions = contributions.get(chunk_id, {})
                fused_rows.append(
                    {
                        "chunk": chunk,
                        "score": boosted_score,
                        "bm25_score": float(bm25_by_chunk.get(chunk_id, 0.0)),
                        "normalized_bm25": self._squash(
                            float(bm25_by_chunk.get(chunk_id, 0.0))
                        ),
                        "vector_score": float(vector_by_chunk.get(chunk_id, 0.0)),
                        "matched_terms": sorted(matched_by_chunk.get(chunk_id, set())),
                        "score_breakdown": {
                            "algorithm": "weighted_rrf",
                            "rrf_k": RRF_K,
                            "channels": channel_contributions,
                            "bm25_weighted": round(
                                sum(
                                    row["rrf"]
                                    for name, row in channel_contributions.items()
                                    if name.startswith("bm25:")
                                ),
                                6,
                            ),
                            "vector_weighted": round(
                                sum(
                                    row["rrf"]
                                    for name, row in channel_contributions.items()
                                    if name.startswith("dense:")
                                ),
                                6,
                            ),
                            "graph_weighted": round(
                                float(channel_contributions.get("graph", {}).get("rrf", 0.0)),
                                6,
                            ),
                            "document_boost": round(document_boost, 6),
                            "base_score": round(boosted_score, 6),
                        },
                    }
                )
            fused_rows.sort(key=lambda item: item["score"], reverse=True)
            deduped = self._dedupe_candidates(fused_rows)
            candidates = deduped[:fusion_pool_k]

        if routing_mode == "auto":
            mmr_candidates = candidates
        else:
            mmr_candidates = self._mmr_select(
                candidates, active_candidate_k, mmr_lambda=active_mmr_lambda
            )

        rerank_trigger = "disabled"
        should_rerank = bool(rerank_enabled and mmr_candidates and blocked is None)
        if routing_mode == "auto" and should_rerank:
            policy = str(plan.modifiers.get("rerank_policy", "never"))
            if policy == "always":
                rerank_trigger = f"route:{plan.route}"
            elif policy == "low_overlap_or_conflict":
                overlap = self._channel_overlap(channel_rankings)
                conflict = self._has_version_conflict(mmr_candidates[:16])
                should_rerank = overlap < 3 or conflict
                rerank_trigger = (
                    "low_sparse_dense_overlap"
                    if overlap < 3
                    else "version_conflict" if conflict else "not_needed"
                )
            else:
                should_rerank = False
                rerank_trigger = "route_policy_disabled"
        elif routing_mode == "manual" and should_rerank:
            rerank_trigger = "manual_enabled"

        if blocked is not None:
            ranked: list[dict] = []
            rerank_status = "blocked"
        elif should_rerank:
            rerank_input = mmr_candidates[:16] if routing_mode == "auto" else mmr_candidates
            try:
                ranked = self.reranker.rerank(query, rerank_input, top_k=output_k)
                rerank_status = "success"
            except Exception as exc:
                ranked = self._base_rank(rerank_input, output_k)
                rerank_status = "fallback"
                degraded = True
                fallbacks.append(
                    {
                        "stage": "rerank",
                        "reason": public_error_message(
                            exc,
                            "Rerank 暂时不可用，已使用基础相关性排序。",
                        ),
                        "action": "preserve_rrf_order",
                    }
                )
        else:
            ranked = self._base_rank(mmr_candidates, output_k)
            rerank_status = "disabled" if not rerank_enabled else "skipped"

        if min_score is not None:
            ranked = [
                item
                for item in ranked
                if float(item.get("rerank_score", item["score"])) >= float(min_score)
            ]
        subquery_coverage: list[dict] = []
        if (
            routing_mode == "auto"
            and plan.route in {"composite", "multihop"}
            and len(rewritten_queries) > 1
            and blocked is None
        ):
            ranked, subquery_coverage = self._ensure_subquery_coverage(
                ranked,
                candidates=mmr_candidates,
                channel_rankings=channel_rankings,
                branch_count=len(rewritten_queries),
                limit=output_k,
                min_score=min_score,
            )
            missing_branches = [
                row["branch"] for row in subquery_coverage if row["status"] == "missing"
            ]
            if missing_branches:
                blocked = {
                    "stage": "evidence_gate",
                    "code": "incomplete_subquery_evidence",
                    "message": "复合查询的部分子问题没有可验证证据。",
                    "retryable": False,
                }
                ranked = []
        active_parent_window = max(0, min(int(parent_window), 3))
        for item in ranked:
            item["parent_window"] = active_parent_window
            item["parent_context"] = self._parent_context(
                item["chunk"], active_parent_window
            )

        bm25_candidates = len(bm25_by_chunk)
        vector_candidates = len(vector_by_chunk)
        plan_trace = plan.to_trace()
        if routing_mode == "manual":
            plan_trace["modifiers"] = {
                "search_mode": search_mode,
                "search_profile": search_profile,
                "strategy": requested_strategy,
                "bm25_weight": active_bm25_weight,
                "vector_weight": active_vector_weight,
                "query_rewrite": query_rewrite,
                "rerank_enabled": rerank_enabled,
            }
        plan_trace.update(
            {
                "routing_mode": routing_mode,
                "applied": routing_mode == "auto",
                "budget": {
                    "derived_queries": max(0, len(rewritten_queries) - 1),
                    "derived_query_limit": derived_query_limit,
                    "branch_candidate_k": branch_candidate_k,
                    "fusion_pool_k": fusion_pool_k,
                    "rerank_k": 16,
                    "final_k": output_k,
                },
                "subquery_coverage": subquery_coverage,
                "hops": hop_trace,
                "index_version": self._resolved_index_version(),
                "degraded": degraded,
                "fallbacks": list(fallbacks),
            }
        )
        trace = {
            "query_tokens": tokenize(query),
            "rewritten_queries": rewritten_queries,
            "total_chunks": total_chunks,
            "available_chunks": available_chunks,
            "top_k": output_k,
            "candidate_k": active_candidate_k,
            "raw_candidates": len(fused_rows),
            "bm25_candidates": bm25_candidates,
            "vector_candidates": vector_candidates,
            "deduped_candidates": len(deduped),
            "mmr_selected": len(mmr_candidates),
            "returned": len(ranked),
            "search_mode": search_mode,
            "search_profile": search_profile,
            "strategy": active_strategy,
            "graph_requested_strategy": requested_strategy,
            "document_ids": sorted(document_filter),
            "knowledge_base_ids": sorted(knowledge_base_filter),
            "modality_filters": sorted(modality_filter),
            "parent_window": active_parent_window,
            "scoring": f"weighted reciprocal rank fusion (k={RRF_K})",
            "bm25_weight": active_bm25_weight,
            "vector_weight": active_vector_weight,
            "embedding_provider": self.embedding_provider_name,
            "embedding_model": self.embedding_model or "-",
            "vector_store": self.vector_store_name,
            "index_version": self._resolved_index_version(),
            "query_rewriter": self.query_rewriter.name if query_rewrite else "off",
            "rewrite_status": rewrite_status,
            "vector_status": vector_status,
            "mmr_lambda": active_mmr_lambda,
            "reranker": self.reranker.name if rerank_enabled else "off",
            "rerank_status": rerank_status,
            "rerank_trigger": rerank_trigger,
            "min_score": min_score,
            "plan": plan_trace,
            "degraded": degraded,
            "blocked": blocked is not None,
            "block": blocked,
            "fallbacks": fallbacks,
            "query_analysis": query_analysis,
            "pipeline": {
                "bm25": {
                    "status": "success" if active_bm25_weight > 0 else "skipped",
                    "candidates": bm25_candidates,
                    "weight": active_bm25_weight,
                    "posting_visits": sparse_posting_visits,
                    "evaluated_chunks": len(sparse_evaluated),
                },
                "vector": {
                    "status": vector_status,
                    "candidates": vector_candidates,
                    "weight": active_vector_weight,
                    "filters_pushed_down": True,
                },
                "fusion": {
                    "algorithm": "weighted_rrf",
                    "k": RRF_K,
                    "channels": len(channel_rankings),
                    "candidates": len(fused_rows),
                    "deduped": len(deduped),
                },
                "mmr": {
                    "status": "skipped" if routing_mode == "auto" else "success",
                    "selected": len(mmr_candidates),
                    "lambda": active_mmr_lambda,
                },
                "rerank": {
                    "status": rerank_status,
                    "trigger": rerank_trigger,
                    "input": min(len(mmr_candidates), 16)
                    if routing_mode == "auto"
                    else len(mmr_candidates),
                    "returned": len(ranked),
                    "provider": self.reranker.name if rerank_enabled else "off",
                },
            },
        }
        if requested_strategy != "hybrid":
            graph_payload = graph_result or {
                "seed_count": 0,
                "seed_nodes": [],
                "paths": [],
                "evidence_element_ids": [],
                "eligible": False,
                "max_hops": max(1, min(int(graph_max_hops), 2)),
            }
            trace["pipeline"]["graph"] = {
                "status": "success" if active_strategy == "hybrid_graph" else "skipped",
                "reason": graph_reason,
                "weight": min(max(float(graph_weight), 0.0), 0.15),
                "seed_count": int(graph_payload.get("seed_count", 0)),
                "seed_nodes": graph_payload.get("seed_nodes", []),
                "paths": graph_payload.get("paths", []),
                "evidence_element_ids": graph_payload.get("evidence_element_ids", []),
                "eligible": bool(graph_payload.get("eligible")),
                "max_hops": graph_payload.get("max_hops", graph_max_hops),
            }
        return ranked, trace

    def delete_document(self, document_id: str) -> bool:
        document_existed = self.documents.pop(document_id, None) is not None
        document_chunks = getattr(self.sparse_index, "document_chunks", {})
        chunk_ids = list(document_chunks.get(document_id, set()))
        self.sparse_index.remove_document(document_id)
        for chunk_id in chunk_ids:
            self._chunk_cache.pop(chunk_id, None)
        store_existed = False
        try:
            store_existed = bool(self.vector_store.has_document(document_id))
        except Exception:
            store_existed = bool(chunk_ids)
        self.vector_store.delete_by_document_id(document_id)
        self._sync_sparse_stats()
        return document_existed or store_existed or bool(chunk_ids)

    def _hydrate_chunk_tokens(self) -> None:
        if self._persistent_sparse:
            self._chunk_cache = {}
            self._sync_sparse_stats()
            return
        chunks = self._store_list_chunks()
        self._chunk_cache = {chunk.chunk_id: chunk for chunk in chunks}
        self.sparse_index.rebuild(chunks)
        self._sync_sparse_stats()

    def _default_sparse_index(self):
        if bool(getattr(self.vector_store, "supports_persistent_sparse", False)):
            return VectorStoreSparseIndex(self.vector_store)
        return SparseBM25Index()

    def _store_list_chunks(
        self,
        *,
        document_ids: list[str] | None = None,
        knowledge_base_ids: list[str] | None = None,
        modalities: list[str] | None = None,
    ) -> list[Chunk]:
        if hasattr(self.vector_store, "list_chunks"):
            try:
                return list(
                    self.vector_store.list_chunks(
                        document_ids=document_ids,
                        knowledge_base_ids=knowledge_base_ids,
                        modalities=modalities,
                    )
                )
            except TypeError:
                return list(self.vector_store.list_chunks())
        return list(getattr(self.vector_store, "chunks", {}).values())

    def _store_count(
        self,
        *,
        document_ids: list[str] | None = None,
        knowledge_base_ids: list[str] | None = None,
        modalities: list[str] | None = None,
    ) -> int:
        if hasattr(self.vector_store, "count_chunks"):
            try:
                return int(
                    self.vector_store.count_chunks(
                        document_ids=document_ids,
                        knowledge_base_ids=knowledge_base_ids,
                        modalities=modalities,
                    )
                )
            except TypeError:
                return int(self.vector_store.count_chunks())
        chunks = self._store_list_chunks(
            document_ids=document_ids,
            knowledge_base_ids=knowledge_base_ids,
            modalities=modalities,
        )
        return len(chunks)

    def _vector_search(
        self,
        query_vector: list[float],
        *,
        top_k: int,
        document_ids: list[str] | None,
        knowledge_base_ids: list[str] | None,
        modalities: list[str] | None,
    ) -> list[dict]:
        try:
            return self.vector_store.search(
                query_vector,
                top_k=top_k,
                document_ids=document_ids,
                knowledge_base_ids=knowledge_base_ids,
                modalities=modalities,
                candidate_count=top_k,
                exact_threshold=2_000,
            )
        except TypeError:
            fetch_k = self._store_count() if any(
                (document_ids, knowledge_base_ids, modalities)
            ) else top_k
            return self.vector_store.search(query_vector, top_k=fetch_k)

    def _prepare_queries(
        self,
        query: str,
        *,
        enabled: bool,
        planned_subqueries: list[str],
        derived_query_limit: int,
    ) -> list[str]:
        queries = [query]
        for item in planned_subqueries:
            cleaned = item.strip()
            if cleaned and cleaned not in queries:
                queries.append(cleaned)
            if len(queries) >= derived_query_limit + 1:
                return queries
        if enabled and len(queries) < derived_query_limit + 1:
            for item in self.query_rewriter.rewrite(query):
                cleaned = item.strip()
                if cleaned and cleaned not in queries:
                    queries.append(cleaned)
                if len(queries) >= derived_query_limit + 1:
                    break
        return queries or [query]

    def _filtered_chunk_map(
        self,
        document_ids: set[str],
        knowledge_base_ids: set[str],
        modalities: set[str],
    ) -> dict[str, Chunk]:
        return {
            chunk_id: chunk
            for chunk_id, chunk in self._chunk_cache.items()
            if self._chunk_matches(chunk, document_ids, knowledge_base_ids, modalities)
        }

    def _chunk_matches(
        self,
        chunk: Chunk,
        document_ids: set[str],
        knowledge_base_ids: set[str],
        modalities: set[str],
    ) -> bool:
        return (
            (not document_ids or chunk.document_id in document_ids)
            and (
                not knowledge_base_ids
                or self._knowledge_base_for_chunk(chunk) in knowledge_base_ids
            )
            and (not modalities or chunk.modality in modalities)
        )

    def _knowledge_base_for_chunk(self, chunk: Chunk) -> str:
        chunk_value = str(chunk.metadata.get("knowledge_base_id") or "")
        if chunk_value:
            return chunk_value
        document = self.documents.get(chunk.document_id)
        if document is None:
            return "default"
        return str(document.metadata.get("knowledge_base_id", "default"))

    def _embedding_text(self, document: Document, chunk: Chunk) -> str:
        explicit = chunk.metadata.get("embedding_text") or chunk.metadata.get("_embedding_text")
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip()
        title = (document.title or document.file_name).strip()
        section = " > ".join(item.strip() for item in chunk.heading_path if item.strip())
        return "\n".join(item for item in (title, section, chunk.text) if item)

    def _weighted_channels(
        self,
        channels: list[dict],
        *,
        bm25_weight: float,
        vector_weight: float,
        graph_weight: float,
    ) -> list[tuple[str, list[str], float]]:
        base = [row for row in channels if row["kind"] in {"bm25", "dense"} and row["ids"]]
        graph = next(
            (row for row in channels if row["kind"] == "graph" and row["ids"]), None
        )
        # Graph evidence is never allowed to create a graph-only result.
        active_graph_weight = min(graph_weight, 0.15) if graph is not None and base else 0.0
        kind_counts = {
            "bm25": sum(1 for row in base if row["kind"] == "bm25"),
            "dense": sum(1 for row in base if row["kind"] == "dense"),
        }
        raw_rows: list[tuple[dict, float]] = []
        for row in base:
            kind_weight = bm25_weight if row["kind"] == "bm25" else vector_weight
            count = max(kind_counts[row["kind"]], 1)
            raw_rows.append((row, max(0.0, float(kind_weight)) / count))
        total_raw = sum(weight for _, weight in raw_rows)
        if total_raw <= 0 and raw_rows:
            raw_rows = [(row, 1.0 / len(raw_rows)) for row, _ in raw_rows]
            total_raw = 1.0
        base_budget = 1.0 - active_graph_weight
        weighted = [
            (row["name"], row["ids"], base_budget * weight / total_raw)
            for row, weight in raw_rows
            if total_raw > 0
        ]
        if active_graph_weight > 0 and graph is not None:
            weighted.append(("graph", graph["ids"], active_graph_weight))
        return weighted

    def _graph_chunk_ranking(
        self,
        graph_result: dict,
        chunks: dict[str, Chunk],
        document_ids: set[str],
        knowledge_base_ids: set[str],
        modalities: set[str],
    ) -> list[str]:
        evidence_ids = [
            str(item) for item in graph_result.get("evidence_element_ids", []) if item
        ]
        if not evidence_ids:
            return []
        lookup = getattr(self.vector_store, "chunks_by_element_ids", None)
        if callable(lookup):
            try:
                evidence_chunks = lookup(
                    evidence_ids,
                    document_ids=sorted(document_ids) or None,
                    knowledge_base_ids=sorted(knowledge_base_ids) or None,
                    modalities=sorted(modalities) or None,
                    limit=100,
                )
            except TypeError:
                evidence_chunks = lookup(evidence_ids)
            for chunk in evidence_chunks:
                if self._chunk_matches(
                    chunk, document_ids, knowledge_base_ids, modalities
                ):
                    chunks[chunk.chunk_id] = chunk
        element_to_chunks: dict[str, list[str]] = defaultdict(list)
        for chunk_id, chunk in chunks.items():
            if not self._chunk_matches(
                chunk, document_ids, knowledge_base_ids, modalities
            ):
                continue
            for element_id in chunk.element_ids:
                element_to_chunks[element_id].append(chunk_id)
        ranking: list[str] = []
        for element_id in evidence_ids:
            for chunk_id in element_to_chunks.get(element_id, []):
                if chunk_id not in ranking:
                    ranking.append(chunk_id)
        return ranking

    def _derive_multihop_query(
        self,
        *,
        query: str,
        graph_result: dict,
        channel_rankings: list[dict],
        chunks: dict[str, Chunk],
        bm25_weight: float,
        vector_weight: float,
    ) -> dict | None:
        """Derive hop two only from an entity present in hop-one evidence.

        Requiring agreement between sparse and dense Top-10 makes the source
        evidence high confidence. The chosen entity must occur verbatim in that
        source leaf and belong to a graph path backed by the leaf's element ID.
        """

        sparse_ids = {
            candidate_id
            for row in channel_rankings
            if row["kind"] == "bm25"
            for candidate_id in row["ids"][:10]
        }
        dense_ids = {
            candidate_id
            for row in channel_rankings
            if row["kind"] == "dense"
            for candidate_id in row["ids"][:10]
        }
        agreed_ids = sparse_ids & dense_ids
        if not agreed_ids:
            return None
        base_channels = [
            row for row in channel_rankings if row["kind"] in {"bm25", "dense"}
        ]
        weighted = self._weighted_channels(
            base_channels,
            bm25_weight=bm25_weight,
            vector_weight=vector_weight,
            graph_weight=0.0,
        )
        scores, _ = weighted_reciprocal_rank_fusion(weighted, k=RRF_K)
        first_round_ids = [
            chunk_id
            for chunk_id, _score in sorted(
                scores.items(), key=lambda item: item[1], reverse=True
            )
            if chunk_id in agreed_ids and chunk_id in chunks
        ][:8]
        query_lower = query.lower()
        for path in graph_result.get("paths", []):
            path_evidence = {
                str(item) for item in path.get("evidence_element_ids", []) if item
            }
            if not path_evidence:
                continue
            for chunk_id in first_round_ids:
                chunk = chunks[chunk_id]
                provenance = sorted(path_evidence & set(chunk.element_ids))
                if not provenance:
                    continue
                text_lower = chunk.text.lower()
                labels = [str(item).strip() for item in path.get("labels", [])]
                for entity in labels:
                    normalized = entity.lower()
                    if (
                        len(normalized) < 2
                        or normalized in query_lower
                        or normalized not in text_lower
                    ):
                        continue
                    return {
                        "hop": 2,
                        "query": f"{query}\n桥接实体：{entity}",
                        "entity": entity,
                        "provenance": provenance,
                        "path_provenance": sorted(path_evidence),
                        "source_chunk_ids": [chunk_id],
                        "status": "executed",
                    }
        return None

    @staticmethod
    def _multihop_chain_evidence(
        *,
        derived_hop: dict | None,
        hop_candidate_ids: set[str],
        chunks: dict[str, Chunk],
    ) -> dict:
        """Verify that hop two completes the provenance-backed graph path.

        First-hop evidence must still resolve to the provenance used to choose
        the bridge entity.  Separately retrieved hop-two candidates must contain
        that entity, and together with the first-hop leaf/leaves must cover every
        evidence element on the selected graph path.  This permits a single leaf
        to prove both edges while rejecting an unresolved or one-hop-only path.
        """

        empty = {
            "complete": False,
            "candidate_chunk_ids": [],
            "evidence_element_ids": [],
            "missing_evidence_element_ids": [],
        }
        if not isinstance(derived_hop, dict):
            return empty

        entity = str(derived_hop.get("entity") or "").strip()
        source_ids = {
            str(item) for item in derived_hop.get("source_chunk_ids", []) if item
        }
        first_hop_provenance = {
            str(item) for item in derived_hop.get("provenance", []) if item
        }
        path_provenance = {
            str(item) for item in derived_hop.get("path_provenance", []) if item
        }
        if not entity or not source_ids or not first_hop_provenance or not path_provenance:
            return empty

        source_chunks = [chunks[item] for item in source_ids if item in chunks]
        candidate_chunks = [
            chunks[item] for item in sorted(hop_candidate_ids) if item in chunks
        ]
        source_evidence = {
            element_id
            for chunk in source_chunks
            for element_id in chunk.element_ids
            if element_id in path_provenance
        }
        hop_evidence = {
            element_id
            for chunk in candidate_chunks
            for element_id in chunk.element_ids
            if element_id in path_provenance
        }
        entity_lower = entity.lower()
        entity_backed = any(entity_lower in chunk.text.lower() for chunk in candidate_chunks)
        covered = source_evidence | hop_evidence
        missing = sorted(path_provenance - covered)
        complete = bool(
            first_hop_provenance <= source_evidence
            and hop_evidence
            and entity_backed
            and not missing
        )
        return {
            "complete": complete,
            "candidate_chunk_ids": [chunk.chunk_id for chunk in candidate_chunks],
            "evidence_element_ids": sorted(covered),
            "missing_evidence_element_ids": missing,
        }

    @staticmethod
    def _channel_overlap(channels: list[dict]) -> int:
        sparse = next((row["ids"][:10] for row in channels if row["kind"] == "bm25"), [])
        dense = next((row["ids"][:10] for row in channels if row["kind"] == "dense"), [])
        return len(set(sparse) & set(dense))

    @staticmethod
    def _has_version_conflict(candidates: list[dict]) -> bool:
        versions: dict[str, set[str]] = defaultdict(set)
        for item in candidates:
            chunk = item["chunk"]
            logical_id = str(
                chunk.metadata.get("logical_document_id")
                or chunk.metadata.get("source_id")
                or chunk.file_name.rsplit(".", 1)[0]
            )
            version = chunk.metadata.get("version") or chunk.metadata.get("revision")
            if version not in (None, ""):
                versions[logical_id].add(str(version))
        return any(len(rows) > 1 for rows in versions.values())

    @staticmethod
    def _ensure_subquery_coverage(
        ranked: list[dict],
        *,
        candidates: list[dict],
        channel_rankings: list[dict],
        branch_count: int,
        limit: int,
        min_score: float | None,
    ) -> tuple[list[dict], list[dict]]:
        output = list(ranked)
        candidate_by_id = {
            item["chunk"].chunk_id: item for item in candidates
        }
        protected_ids: set[str] = set()
        coverage: list[dict] = []
        for branch in range(1, branch_count):
            branch_ids: list[str] = []
            for channel in channel_rankings:
                if channel["name"] in {f"bm25:{branch}", f"dense:{branch}"}:
                    for candidate_id in channel["ids"]:
                        if candidate_id not in branch_ids:
                            branch_ids.append(candidate_id)
            selected_id = next(
                (
                    candidate_id
                    for candidate_id in branch_ids
                    if candidate_id in candidate_by_id
                    and (
                        min_score is None
                        or float(
                            candidate_by_id[candidate_id].get(
                                "rerank_score", candidate_by_id[candidate_id]["score"]
                            )
                        )
                        >= float(min_score)
                    )
                ),
                "",
            )
            if not selected_id:
                coverage.append({"branch": branch, "status": "missing"})
                continue
            protected_ids.add(selected_id)
            if any(item["chunk"].chunk_id == selected_id for item in output):
                coverage.append(
                    {"branch": branch, "status": "present", "candidate_id": selected_id}
                )
                continue
            selected = candidate_by_id[selected_id]
            selected.setdefault("rerank_score", selected["score"])
            if len(output) < limit:
                output.append(selected)
            else:
                replace_at = next(
                    (
                        index
                        for index in range(len(output) - 1, -1, -1)
                        if output[index]["chunk"].chunk_id not in protected_ids
                    ),
                    None,
                )
                if replace_at is None:
                    coverage.append({"branch": branch, "status": "missing"})
                    continue
                output[replace_at] = selected
            coverage.append(
                {"branch": branch, "status": "inserted", "candidate_id": selected_id}
            )
        return output[:limit], coverage

    def _mmr_select(self, candidates: list[dict], limit: int, mmr_lambda: float) -> list[dict]:
        if not candidates or len(candidates) <= 2:
            return candidates
        selected = [candidates[0]]
        remaining = candidates[1:]
        while remaining and len(selected) < limit:
            scored = []
            for item in remaining:
                redundancy = max(
                    self._token_overlap(item["chunk"], row["chunk"])
                    for row in selected
                )
                mmr_score = mmr_lambda * item["score"] - (1 - mmr_lambda) * redundancy
                scored.append((mmr_score, item))
            _, best = max(scored, key=lambda row: row[0])
            selected.append(best)
            remaining = [
                item
                for item in remaining
                if item["chunk"].chunk_id != best["chunk"].chunk_id
            ]
        return selected

    @staticmethod
    def _dedupe_candidates(candidates: list[dict]) -> list[dict]:
        seen = set()
        deduped = []
        for item in candidates:
            chunk = item["chunk"]
            key = (chunk.file_name, " ".join(chunk.text.split()))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    @staticmethod
    def _base_rank(candidates: list[dict], top_k: int) -> list[dict]:
        ranked = sorted(candidates, key=lambda item: item["score"], reverse=True)[:top_k]
        for item in ranked:
            item["rerank_score"] = item["score"]
        return ranked

    def _token_overlap(self, left: Chunk, right: Chunk) -> float:
        left_tokens = set(self.chunk_tokens.get(left.chunk_id, tokenize(left.text)))
        right_tokens = set(self.chunk_tokens.get(right.chunk_id, tokenize(right.text)))
        if not left_tokens or not right_tokens:
            return 0.0
        return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)

    def _parent_context(self, chunk: Chunk, radius: int) -> dict:
        radius = max(0, min(int(radius), 3))
        if hasattr(self.vector_store, "context_chunks"):
            siblings = self.vector_store.context_chunks(chunk.chunk_id, radius)
        else:
            siblings = [
                item
                for item in self._chunk_cache.values()
                if item.document_id == chunk.document_id
                and abs(item.chunk_index - chunk.chunk_index) <= radius
            ]
        siblings = sorted(siblings, key=lambda item: item.chunk_index)
        if not siblings:
            siblings = [chunk]
        return {
            "strategy": "parent_child",
            "text": "\n\n".join(item.text for item in siblings),
            "chunk_ids": [item.chunk_id for item in siblings],
            "current_chunk_id": chunk.chunk_id,
            "window": radius,
        }

    def _sync_sparse_stats(self) -> None:
        self.chunk_tokens = self.sparse_index.chunk_tokens
        self.doc_freq = self.sparse_index.document_frequency
        self.avg_len = self.sparse_index.average_length

    @staticmethod
    def _squash(score: float) -> float:
        return score / (score + 1) if score > 0 else 0.0

    def _resolve_candidate_k(
        self,
        top_k: int,
        candidate_k: Optional[int],
        profile: str,
        total_chunks: int,
    ) -> int:
        if total_chunks <= 0:
            return 0
        if candidate_k is not None:
            return max(top_k, min(candidate_k, total_chunks))
        if profile == "precision":
            resolved = max(top_k * 2, top_k)
        elif profile == "recall":
            resolved = max(top_k * 6, self.initial_retrieval_k)
        else:
            resolved = self.initial_retrieval_k
        return max(top_k, min(resolved, total_chunks))

    def _resolve_weights(
        self,
        mode: str,
        bm25_weight: Optional[float],
        vector_weight: Optional[float],
    ) -> tuple[float, float]:
        if mode == "keyword":
            return 1.0, 0.0
        if mode == "semantic":
            return 0.0, 1.0
        bm25 = self.bm25_weight if bm25_weight is None else float(bm25_weight)
        vector = self.vector_weight if vector_weight is None else float(vector_weight)
        total = bm25 + vector
        if total <= 0:
            return self.bm25_weight, self.vector_weight
        return round(bm25 / total, 4), round(vector / total, 4)

    def _resolve_mmr_lambda(self, profile: str, mmr_lambda: Optional[float]) -> float:
        if mmr_lambda is not None:
            return float(mmr_lambda)
        if profile == "precision":
            return 0.9
        if profile == "recall":
            return 0.62
        return self.mmr_lambda

    def _document_boost(self, document_id: str) -> float:
        document = self.documents.get(document_id)
        if not document:
            return 1.0
        quality = document.metadata.get("quality")
        quality_score = quality.get("score", 80) if isinstance(quality, dict) else 80
        priority = float(document.metadata.get("priority", 1.0) or 1.0)
        quality_boost = 0.94 + min(max(float(quality_score), 0), 100) / 1000
        priority_boost = min(max(priority, 0.7), 1.3)
        return round(quality_boost * priority_boost, 4)

    def _resolved_index_version(self) -> str:
        if self.index_version:
            return self.index_version
        for attribute in ("active_index_id", "index_version", "table_name"):
            value = getattr(self.vector_store, attribute, "")
            if value:
                return str(value)
        versions = {
            str(doc.metadata.get("index_version"))
            for doc in self.documents.values()
            if doc.metadata.get("index_version")
        }
        return next(iter(versions)) if len(versions) == 1 else "unknown"
