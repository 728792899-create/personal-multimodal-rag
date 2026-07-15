import math
from collections import Counter, defaultdict
from typing import Optional

from app.models.domain import Chunk, Document
from app.services.embeddings import BaseEmbeddingProvider, MockEmbeddingProvider
from app.services.query_intelligence import analyze_query
from app.services.query_rewriter import BaseQueryRewriter, NoopQueryRewriter
from app.services.reranker import BaseReranker, KeywordReranker
from app.services.safe_logging import redact_sensitive_text
from app.services.text_utils import retrieval_tokens, tokenize
from app.services.vectorstore import BaseVectorStore, MemoryVectorStore


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
        mmr_lambda: float = 0.78,
        bm25_weight: float = 0.62,
        vector_weight: float = 0.38,
    ):
        self.embedding_provider = embedding_provider or MockEmbeddingProvider()
        self.vector_store = vector_store or MemoryVectorStore()
        self.reranker = reranker or KeywordReranker()
        self.query_rewriter = query_rewriter or NoopQueryRewriter()
        self.initial_retrieval_k = initial_retrieval_k
        self.embedding_provider_name = embedding_provider_name or self.embedding_provider.__class__.__name__
        self.embedding_model = embedding_model
        self.vector_store_name = vector_store_name or self.vector_store.__class__.__name__
        self.mmr_lambda = mmr_lambda
        self.bm25_weight = bm25_weight
        self.vector_weight = vector_weight
        self.documents: dict[str, Document] = {}
        self.chunk_tokens: dict[str, list[str]] = {}
        self.doc_freq: dict[str, int] = defaultdict(int)
        self.avg_len = 0.0
        self._hydrate_chunk_tokens()

    def add_document(self, doc: Document, chunks: list[Chunk]) -> None:
        self.documents[doc.document_id] = doc
        embeddings = self.embedding_provider.embed_batch([chunk.text for chunk in chunks])
        self.vector_store.add_chunks(chunks, embeddings)
        for chunk in chunks:
            tokens = tokenize(chunk.text)
            self.chunk_tokens[chunk.chunk_id] = tokens
        self._rebuild_doc_freq()

    def load_documents(self, documents: list[Document]) -> None:
        self.documents = {doc.document_id: doc for doc in documents}
        self._hydrate_chunk_tokens()

    def list_documents(self) -> list[dict]:
        return [
            {
                "id": doc.document_id,
                "filename": doc.file_name,
                "source_type": doc.file_type,
                "chunk_count": sum(1 for chunk in self.vector_store.chunks.values() if chunk.document_id == doc.document_id),
                "char_count": len(doc.text),
                "metadata": doc.metadata,
            }
            for doc in self.documents.values()
        ]

    def search(
        self,
        query: str,
        top_k: int = 5,
        candidate_k: Optional[int] = None,
        search_mode: str = "hybrid",
        search_profile: str = "balanced",
        document_ids: Optional[list[str]] = None,
        knowledge_base_ids: Optional[list[str]] = None,
        bm25_weight: Optional[float] = None,
        vector_weight: Optional[float] = None,
        mmr_lambda: Optional[float] = None,
        min_score: Optional[float] = None,
        query_rewrite: bool = True,
        rerank_enabled: bool = True,
    ) -> tuple[list[dict], dict]:
        search_mode = search_mode if search_mode in {"hybrid", "keyword", "semantic"} else "hybrid"
        search_profile = search_profile if search_profile in {"balanced", "precision", "recall"} else "balanced"
        active_bm25_weight, active_vector_weight = self._resolve_weights(search_mode, bm25_weight, vector_weight)
        active_mmr_lambda = self._resolve_mmr_lambda(search_profile, mmr_lambda)
        fallbacks: list[dict] = []
        query_analysis = analyze_query(query)
        document_filter = {item for item in (document_ids or []) if item}
        knowledge_base_filter = {item for item in (knowledge_base_ids or []) if item}
        chunks = {
            chunk_id: chunk
            for chunk_id, chunk in self.vector_store.chunks.items()
            if (not document_filter or chunk.document_id in document_filter)
            and (
                not knowledge_base_filter
                or self._knowledge_base_for_document(chunk.document_id) in knowledge_base_filter
            )
        }
        try:
            rewritten_queries = self._rewrite_queries(query, enabled=query_rewrite)
            rewrite_status = "disabled" if not query_rewrite else "success"
        except Exception as exc:
            rewritten_queries = [query]
            rewrite_status = "fallback"
            fallbacks.append(
                {
                    "stage": "query_rewrite",
                    "reason": redact_sensitive_text(exc),
                    "action": "use_original_query",
                }
            )
        query_token_sets = [retrieval_tokens(item) for item in rewritten_queries]
        query_terms = sorted({token for tokens in query_token_sets for token in tokens})
        active_candidate_k = self._resolve_candidate_k(
            top_k=top_k,
            candidate_k=candidate_k,
            profile=search_profile,
            total_chunks=len(chunks),
        )
        vector_scores: dict[str, float] = {}
        vector_status = "skipped"

        if active_vector_weight > 0 and chunks:
            try:
                query_vectors = self.embedding_provider.embed_batch(rewritten_queries)
                vector_fetch_k = len(self.vector_store.chunks) if (document_filter or knowledge_base_filter) else active_candidate_k
                for query_vec in query_vectors:
                    for item in self.vector_store.search(query_vec, top_k=vector_fetch_k):
                        chunk_id = item["chunk"].chunk_id
                        if chunk_id not in chunks:
                            continue
                        vector_scores[chunk_id] = max(vector_scores.get(chunk_id, 0.0), item["vector_score"])
                vector_status = "success"
            except Exception as exc:
                vector_scores = {}
                active_bm25_weight = 1.0
                active_vector_weight = 0.0
                vector_status = "fallback"
                fallbacks.append(
                    {
                        "stage": "vector_search",
                        "reason": redact_sensitive_text(exc),
                        "action": "fallback_to_keyword_bm25",
                    }
                )

        raw_scores = []

        for chunk_id, chunk in chunks.items():
            bm25 = max((self._bm25(tokens, self.chunk_tokens.get(chunk_id, [])) for tokens in query_token_sets), default=0.0)
            vector = vector_scores.get(chunk_id, 0.0)
            normalized_bm25 = self._squash(bm25)
            score = active_bm25_weight * normalized_bm25 + active_vector_weight * vector
            doc_boost = self._document_boost(chunk.document_id)
            score = score * doc_boost
            chunk_tokens = set(self.chunk_tokens.get(chunk_id, []))
            matched_terms = sorted(set(query_terms) & chunk_tokens)
            raw_scores.append(
                {
                    "chunk": chunk,
                    "score": score,
                    "bm25_score": bm25,
                    "normalized_bm25": normalized_bm25,
                    "vector_score": vector,
                    "matched_terms": matched_terms,
                    "score_breakdown": {
                        "bm25_weighted": round(active_bm25_weight * normalized_bm25, 6),
                        "vector_weighted": round(active_vector_weight * vector, 6),
                        "document_boost": round(doc_boost, 6),
                        "base_score": round(score, 6),
                    },
                }
            )

        sorted_scores = sorted(raw_scores, key=lambda item: item["score"], reverse=True)
        deduped = self._dedupe_candidates(sorted_scores)
        candidates = deduped[:active_candidate_k]
        mmr_candidates = self._mmr_select(candidates, active_candidate_k, mmr_lambda=active_mmr_lambda)
        rerank_status = "disabled" if not rerank_enabled else "success"
        if rerank_enabled:
            try:
                ranked = self.reranker.rerank(query, mmr_candidates, top_k=top_k)
            except Exception as exc:
                ranked = self._base_rank(mmr_candidates, top_k)
                rerank_status = "fallback"
                fallbacks.append(
                    {
                        "stage": "rerank",
                        "reason": redact_sensitive_text(exc),
                        "action": "use_base_score_order",
                    }
                )
        else:
            ranked = self._base_rank(mmr_candidates, top_k)
        if min_score is not None:
            ranked = [
                item
                for item in ranked
                if float(item.get("rerank_score", item["score"])) >= float(min_score)
            ]
        bm25_candidates = sum(1 for item in raw_scores if float(item["bm25_score"]) > 0)
        vector_candidates = sum(1 for item in raw_scores if float(item["vector_score"]) > 0)
        trace = {
            "query_tokens": tokenize(query),
            "rewritten_queries": rewritten_queries,
            "total_chunks": len(self.vector_store.chunks),
            "available_chunks": len(chunks),
            "top_k": top_k,
            "candidate_k": active_candidate_k,
            "raw_candidates": len(raw_scores),
            "bm25_candidates": bm25_candidates,
            "vector_candidates": vector_candidates,
            "deduped_candidates": len(deduped),
            "mmr_selected": len(mmr_candidates),
            "returned": len(ranked),
            "search_mode": search_mode,
            "search_profile": search_profile,
            "document_ids": sorted(document_filter),
            "knowledge_base_ids": sorted(knowledge_base_filter),
            "scoring": f"{active_bm25_weight} * normalized BM25 + {active_vector_weight} * vector similarity",
            "bm25_weight": active_bm25_weight,
            "vector_weight": active_vector_weight,
            "embedding_provider": self.embedding_provider_name,
            "embedding_model": self.embedding_model or "-",
            "vector_store": self.vector_store_name,
            "query_rewriter": self.query_rewriter.name if query_rewrite else "off",
            "rewrite_status": rewrite_status,
            "vector_status": vector_status,
            "mmr_lambda": active_mmr_lambda,
            "reranker": self.reranker.name if rerank_enabled else "off",
            "rerank_status": rerank_status,
            "min_score": min_score,
            "fallbacks": fallbacks,
            "query_analysis": query_analysis,
            "pipeline": {
                "bm25": {
                    "status": "success" if active_bm25_weight > 0 else "skipped",
                    "candidates": bm25_candidates,
                    "weight": active_bm25_weight,
                },
                "vector": {
                    "status": vector_status,
                    "candidates": vector_candidates,
                    "weight": active_vector_weight,
                },
                "fusion": {"candidates": len(raw_scores), "deduped": len(deduped)},
                "mmr": {"selected": len(mmr_candidates), "lambda": active_mmr_lambda},
                "rerank": {"status": rerank_status, "returned": len(ranked), "provider": self.reranker.name if rerank_enabled else "off"},
            },
        }
        return ranked, trace

    def _knowledge_base_for_document(self, document_id: str) -> str:
        document = self.documents.get(document_id)
        if document is None:
            return "default"
        return str(document.metadata.get("knowledge_base_id", "default"))

    def delete_document(self, document_id: str) -> bool:
        if document_id not in self.documents:
            return False
        self.documents.pop(document_id, None)
        for chunk_id in list(self.chunk_tokens):
            if chunk_id.startswith(f"{document_id}:"):
                self.chunk_tokens.pop(chunk_id, None)
        self.vector_store.delete_by_document_id(document_id)
        self._rebuild_doc_freq()
        return True

    def _hydrate_chunk_tokens(self) -> None:
        self.chunk_tokens = {
            chunk_id: tokenize(chunk.text)
            for chunk_id, chunk in self.vector_store.chunks.items()
        }
        self._rebuild_doc_freq()

    def _rewrite_queries(self, query: str, enabled: bool = True) -> list[str]:
        if not enabled:
            return [query]
        queries = self.query_rewriter.rewrite(query)
        deduped = []
        for item in queries:
            cleaned = item.strip()
            if cleaned and cleaned not in deduped:
                deduped.append(cleaned)
        return deduped or [query]

    def _mmr_select(self, candidates: list[dict], limit: int, mmr_lambda: float) -> list[dict]:
        if not candidates or len(candidates) <= 2:
            return candidates
        selected = [candidates[0]]
        remaining = candidates[1:]
        while remaining and len(selected) < limit:
            scored = []
            for item in remaining:
                redundancy = max(self._token_overlap(item["chunk"], row["chunk"]) for row in selected)
                mmr_score = mmr_lambda * item["score"] - (1 - mmr_lambda) * redundancy
                scored.append((mmr_score, item))
            _, best = max(scored, key=lambda row: row[0])
            selected.append(best)
            remaining = [item for item in remaining if item["chunk"].chunk_id != best["chunk"].chunk_id]
        return selected

    def _dedupe_candidates(self, candidates: list[dict]) -> list[dict]:
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

    def _base_rank(self, candidates: list[dict], top_k: int) -> list[dict]:
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

    def _rebuild_doc_freq(self) -> None:
        self.doc_freq.clear()
        lengths = []
        for tokens in self.chunk_tokens.values():
            lengths.append(len(tokens))
            for token in set(tokens):
                self.doc_freq[token] += 1
        self.avg_len = sum(lengths) / len(lengths) if lengths else 0.0

    def _bm25(self, query_tokens: list[str], doc_tokens: list[str], k1: float = 1.5, b: float = 0.75) -> float:
        if not query_tokens or not doc_tokens:
            return 0.0
        counts = Counter(doc_tokens)
        total_docs = max(len(self.chunk_tokens), 1)
        score = 0.0
        for token in query_tokens:
            freq = counts[token]
            if freq == 0:
                continue
            df = self.doc_freq.get(token, 0)
            idf = math.log(1 + (total_docs - df + 0.5) / (df + 0.5))
            denom = freq + k1 * (1 - b + b * len(doc_tokens) / max(self.avg_len, 1))
            score += idf * (freq * (k1 + 1)) / denom
        return score

    def _squash(self, score: float) -> float:
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
