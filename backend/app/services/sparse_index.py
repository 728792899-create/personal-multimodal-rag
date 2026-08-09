from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from app.models.domain import Chunk
from app.services.text_utils import tokenize


@dataclass(frozen=True)
class SparseSearchHit:
    chunk_id: str
    score: float
    matched_terms: tuple[str, ...]
    chunk: Chunk | None = None


class SparseBM25Index:
    """In-process inverted BM25 index for Memory and Chroma stores."""

    requires_hydration = True

    def __init__(self, *, k1: float = 1.5, b: float = 0.75):
        self.k1 = float(k1)
        self.b = float(b)
        self.postings: dict[str, dict[str, int]] = defaultdict(dict)
        self.chunk_lengths: dict[str, int] = {}
        self.chunk_tokens: dict[str, list[str]] = {}
        self.chunk_document_ids: dict[str, str] = {}
        self.document_chunks: dict[str, set[str]] = defaultdict(set)
        self.total_length = 0
        self.last_search_stats = {
            "query_terms": 0,
            "posting_visits": 0,
            "evaluated_chunks": 0,
            "total_chunks": 0,
        }

    @property
    def document_frequency(self) -> dict[str, int]:
        return {term: len(rows) for term, rows in self.postings.items()}

    @property
    def average_length(self) -> float:
        return self.total_length / len(self.chunk_lengths) if self.chunk_lengths else 0.0

    def clear(self) -> None:
        self.postings.clear()
        self.chunk_lengths.clear()
        self.chunk_tokens.clear()
        self.chunk_document_ids.clear()
        self.document_chunks.clear()
        self.total_length = 0

    def rebuild(self, chunks: Iterable[Chunk]) -> None:
        self.clear()
        self.add_chunks(chunks)

    def add_chunks(self, chunks: Iterable[Chunk]) -> None:
        for chunk in chunks:
            self.add_chunk(chunk)

    def add_chunk(self, chunk: Chunk) -> None:
        if chunk.chunk_id in self.chunk_lengths:
            self.remove_chunk(chunk.chunk_id)
        tokens = tokenize(chunk.text)
        counts = Counter(tokens)
        self.chunk_tokens[chunk.chunk_id] = tokens
        self.chunk_lengths[chunk.chunk_id] = len(tokens)
        self.chunk_document_ids[chunk.chunk_id] = chunk.document_id
        self.document_chunks[chunk.document_id].add(chunk.chunk_id)
        self.total_length += len(tokens)
        for term, frequency in counts.items():
            self.postings[term][chunk.chunk_id] = int(frequency)

    def remove_document(self, document_id: str) -> None:
        for chunk_id in tuple(self.document_chunks.get(document_id, ())):
            self.remove_chunk(chunk_id)

    def remove_chunk(self, chunk_id: str) -> None:
        tokens = self.chunk_tokens.pop(chunk_id, [])
        self.total_length -= self.chunk_lengths.pop(chunk_id, 0)
        document_id = self.chunk_document_ids.pop(chunk_id, "")
        if document_id:
            rows = self.document_chunks.get(document_id)
            if rows is not None:
                rows.discard(chunk_id)
                if not rows:
                    self.document_chunks.pop(document_id, None)
        for term in set(tokens):
            rows = self.postings.get(term)
            if rows is None:
                continue
            rows.pop(chunk_id, None)
            if not rows:
                self.postings.pop(term, None)

    def search(
        self,
        query_tokens: Iterable[str],
        *,
        top_k: int,
        allowed_chunk_ids: set[str] | None = None,
        document_ids: list[str] | None = None,
        knowledge_base_ids: list[str] | None = None,
        modalities: list[str] | None = None,
    ) -> list[SparseSearchHit]:
        del document_ids, knowledge_base_ids, modalities
        terms = tuple(dict.fromkeys(term for term in query_tokens if term))[:64]
        if not terms or top_k <= 0 or not self.chunk_lengths:
            self.last_search_stats = {
                "query_terms": len(terms),
                "posting_visits": 0,
                "evaluated_chunks": 0,
                "total_chunks": len(self.chunk_lengths),
            }
            return []

        candidate_ids: set[str] = set()
        posting_visits = 0
        for term in terms:
            rows = self.postings.get(term, {})
            posting_visits += len(rows)
            if allowed_chunk_ids is None:
                candidate_ids.update(rows)
            else:
                candidate_ids.update(
                    chunk_id for chunk_id in rows if chunk_id in allowed_chunk_ids
                )

        total_docs = max(len(self.chunk_lengths), 1)
        average_length = max(self.average_length, 1.0)
        hits: list[SparseSearchHit] = []
        for chunk_id in candidate_ids:
            length = self.chunk_lengths.get(chunk_id, 0)
            score = 0.0
            matched_terms: list[str] = []
            for term in terms:
                frequency = self.postings.get(term, {}).get(chunk_id, 0)
                if frequency <= 0:
                    continue
                matched_terms.append(term)
                document_frequency = len(self.postings.get(term, {}))
                inverse_frequency = math.log(
                    1
                    + (total_docs - document_frequency + 0.5)
                    / (document_frequency + 0.5)
                )
                denominator = frequency + self.k1 * (
                    1 - self.b + self.b * length / average_length
                )
                score += inverse_frequency * (frequency * (self.k1 + 1)) / denominator
            if score > 0:
                hits.append(
                    SparseSearchHit(
                        chunk_id=chunk_id,
                        score=score,
                        matched_terms=tuple(sorted(matched_terms)),
                    )
                )

        hits.sort(key=lambda item: (-item.score, item.chunk_id))
        self.last_search_stats = {
            "query_terms": len(terms),
            "posting_visits": posting_visits,
            "evaluated_chunks": len(candidate_ids),
            "total_chunks": len(self.chunk_lengths),
        }
        return hits[:top_k]


class VectorStoreSparseIndex:
    """Adapter for stores that own versioned, persistent BM25 postings."""

    requires_hydration = False

    def __init__(self, vector_store: Any):
        if not bool(getattr(vector_store, "supports_persistent_sparse", False)):
            raise ValueError("Vector store does not support persistent sparse search")
        self.vector_store = vector_store
        self.chunk_tokens: dict[str, list[str]] = {}
        self.document_chunks: dict[str, set[str]] = {}
        self.last_search_stats = {
            "query_terms": 0,
            "posting_visits": 0,
            "evaluated_chunks": 0,
            "total_chunks": 0,
        }

    @property
    def document_frequency(self) -> dict[str, int]:
        return {}

    @property
    def average_length(self) -> float:
        return 0.0

    def rebuild(self, chunks: Iterable[Chunk]) -> None:
        raise RuntimeError("Persistent postings are rebuilt with the versioned vector index")

    def add_chunks(self, chunks: Iterable[Chunk]) -> None:
        # PgVectorStore.add_chunks updates vectors and postings in one transaction.
        del chunks

    def remove_document(self, document_id: str) -> None:
        # PgVectorStore.delete_by_document_id removes postings through its FK cascade.
        del document_id

    def search(
        self,
        query_tokens: Iterable[str],
        *,
        top_k: int,
        allowed_chunk_ids: set[str] | None = None,
        document_ids: list[str] | None = None,
        knowledge_base_ids: list[str] | None = None,
        modalities: list[str] | None = None,
    ) -> list[SparseSearchHit]:
        if allowed_chunk_ids is not None:
            raise ValueError("Persistent sparse filters must be pushed down by metadata")
        rows = self.vector_store.sparse_search(
            list(query_tokens)[:64],
            top_k=top_k,
            document_ids=document_ids,
            knowledge_base_ids=knowledge_base_ids,
            modalities=modalities,
        )
        self.last_search_stats = dict(
            getattr(self.vector_store, "last_sparse_search_stats", self.last_search_stats)
        )
        return [
            SparseSearchHit(
                chunk_id=row["chunk"].chunk_id,
                score=float(row.get("bm25_score", 0.0)),
                matched_terms=tuple(str(item) for item in row.get("matched_terms", [])),
                chunk=row["chunk"],
            )
            for row in rows
            if isinstance(row.get("chunk"), Chunk)
        ]
