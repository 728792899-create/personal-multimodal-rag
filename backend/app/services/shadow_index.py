from __future__ import annotations

import math
import time
from typing import Callable

from app.models.domain import Document
from app.services.document_processor import DocumentProcessor
from app.services.embeddings import BaseEmbeddingProvider, embedding_text_for_chunk
from app.services.index_versions import IndexVersionRegistry
from app.services.vectorstore import PgVectorStore


def _prepared_document(
    document: Document,
    *,
    parser_version: str,
    chunker_version: str,
) -> Document:
    prepared = document.model_copy(deep=True)
    prepared.metadata["parser_version"] = parser_version
    prepared.metadata["chunker_version"] = chunker_version
    return prepared


def _representative_sample(rows: list[tuple[Document, list]], percentage: int = 10):
    if not rows:
        return []
    ordered = sorted(
        rows,
        key=lambda row: sum(len(embedding_text_for_chunk(chunk)) for chunk in row[1]),
    )
    sample_count = max(1, (len(ordered) * percentage + 99) // 100)
    return [
        ordered[min(len(ordered) - 1, int((index + 0.5) * len(ordered) / sample_count))]
        for index in range(sample_count)
    ]


def estimate_dry_run(
    documents: list[Document],
    *,
    processor: DocumentProcessor | None = None,
    percentage: int = 10,
    provider: BaseEmbeddingProvider | None = None,
    price_per_million_tokens: float = 0.13,
    batch_size: int = 64,
) -> dict:
    processor = processor or DocumentProcessor()
    rows = [(document, processor.split(document)) for document in documents]
    sample = _representative_sample(rows, max(1, min(int(percentage), 100)))
    sample_texts = [
        embedding_text_for_chunk(chunk)
        for _, chunks in sample
        for chunk in chunks
    ]
    sample_characters = sum(map(len, sample_texts))
    all_characters = sum(
        len(embedding_text_for_chunk(chunk))
        for _, chunks in rows
        for chunk in chunks
    )
    before = int(getattr(provider, "input_tokens_used", 0)) if provider else 0
    started = time.perf_counter()
    if provider is not None:
        for start in range(0, len(sample_texts), max(1, int(batch_size))):
            provider.embed_batch(sample_texts[start : start + max(1, int(batch_size))])
    measured = (
        int(getattr(provider, "input_tokens_used", 0)) - before if provider else 0
    )
    sample_tokens = measured or math.ceil(sample_characters / 3)
    projected_tokens = round(
        sample_tokens * all_characters / max(1, sample_characters)
    )
    return {
        "mode": "provider-executed" if provider else "estimate-only",
        "sample_percentage": percentage,
        "sample_documents": len(sample),
        "sample_chunks": sum(len(chunks) for _, chunks in sample),
        "sample_characters": sample_characters,
        "sample_input_tokens": sample_tokens,
        "sample_elapsed_seconds": round(time.perf_counter() - started, 3),
        "projected_documents": len(documents),
        "projected_chunks": sum(len(chunks) for _, chunks in rows),
        "projected_input_tokens": projected_tokens,
        "projected_embedding_cost_usd": round(
            projected_tokens / 1_000_000 * max(0.0, price_per_million_tokens),
            6,
        ),
    }


class ShadowIndexRebuilder:
    """Idempotently build and validate an inactive pgvector index version."""

    def __init__(
        self,
        *,
        index_registry: IndexVersionRegistry,
        vector_dsn: str,
        embedding_provider: BaseEmbeddingProvider | None,
        processor: DocumentProcessor | None = None,
        embedding_batch_size: int = 64,
        embedding_price_per_million_tokens: float = 0.13,
    ):
        self.index_registry = index_registry
        self.vector_dsn = vector_dsn
        self.embedding_provider = embedding_provider
        self.processor = processor or DocumentProcessor()
        self.embedding_batch_size = max(1, min(int(embedding_batch_size), 256))
        self.embedding_price_per_million_tokens = max(
            0.0, float(embedding_price_per_million_tokens)
        )

    def _chunks_for_document(self, document: Document, record) -> tuple[Document, list]:
        prepared = _prepared_document(
            document,
            parser_version=record.parser_version,
            chunker_version=record.chunker_version,
        )
        chunks = self.processor.split(prepared)
        for chunk in chunks:
            chunk.metadata.update(
                {
                    "embedding_provider": record.embedding_provider,
                    "embedding_model": record.embedding_model,
                    "embedding_dimension": record.embedding_dimension,
                    "index_version": record.index_id,
                    "parser_version": record.parser_version,
                    "chunker_version": record.chunker_version,
                }
            )
        return prepared, chunks

    @staticmethod
    def _expected_signature(document: Document, chunks: list, record) -> dict:
        return {
            "chunk_ids": sorted(chunk.chunk_id for chunk in chunks),
            "content_hashes": [str(document.metadata.get("content_hash") or "")],
            "parser_versions": [record.parser_version],
            "chunker_versions": [record.chunker_version],
            "embedding_providers": [record.embedding_provider],
            "embedding_models": [record.embedding_model],
            "embedding_dimensions": [str(record.embedding_dimension)],
            "index_versions": [record.index_id],
        }

    def _ensure_dry_run(self, record, prepared_rows: list[tuple[Document, list]]) -> dict:
        existing = record.metrics.get("dry_run") if isinstance(record.metrics, dict) else None
        if isinstance(existing, dict) and int(existing.get("projected_input_tokens") or 0) > 0:
            return existing
        sample = _representative_sample(prepared_rows, 10)
        sample_texts = [
            embedding_text_for_chunk(chunk)
            for _, chunks in sample
            for chunk in chunks
        ]
        all_characters = sum(
            len(embedding_text_for_chunk(chunk))
            for _, chunks in prepared_rows
            for chunk in chunks
        )
        sample_characters = sum(map(len, sample_texts))
        before = int(getattr(self.embedding_provider, "input_tokens_used", 0))
        started = time.perf_counter()
        for start in range(0, len(sample_texts), self.embedding_batch_size):
            self.embedding_provider.embed_batch(
                sample_texts[start : start + self.embedding_batch_size]
            )
        sample_tokens = int(getattr(self.embedding_provider, "input_tokens_used", 0)) - before
        projected_tokens = round(
            sample_tokens * all_characters / max(1, sample_characters)
        )
        estimate = {
            "sample_percentage": 10,
            "sample_documents": len(sample),
            "sample_chunks": len(sample_texts),
            "sample_characters": sample_characters,
            "sample_input_tokens": sample_tokens,
            "sample_elapsed_seconds": round(time.perf_counter() - started, 3),
            "projected_documents": len(prepared_rows),
            "projected_chunks": sum(len(chunks) for _, chunks in prepared_rows),
            "projected_input_tokens": projected_tokens,
            "projected_embedding_cost_usd": round(
                projected_tokens / 1_000_000 * self.embedding_price_per_million_tokens,
                6,
            ),
        }
        self.index_registry.record_metrics(record.index_id, {"dry_run": estimate})
        return estimate

    def rebuild(
        self,
        index_id: str,
        documents: list[Document],
        *,
        progress: Callable[[str, int], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> dict:
        record = self.index_registry.get(index_id)
        if record is None:
            raise ValueError(f"Index candidate does not exist: {index_id}")
        if record.status not in {"candidate", "stable"}:
            raise ValueError("Only candidate or stable indexes can be rebuilt")
        if self.embedding_provider is None:
            raise ValueError("An OpenAI embedding provider is required for rebuild")
        store = PgVectorStore(
            self.vector_dsn,
            table_name=record.table_name,
            dimension=record.embedding_dimension,
            create_hnsw=False,
        )
        prepared_rows = [self._chunks_for_document(document, record) for document in documents]
        if progress:
            progress("embedding_dry_run", 5)
        dry_run = self._ensure_dry_run(record, prepared_rows)
        started = time.perf_counter()
        indexed_documents = indexed_chunks = skipped_documents = 0
        usage_before = int(getattr(self.embedding_provider, "input_tokens_used", 0))
        previous_usage = int(
            record.metrics.get("rebuild_usage", {}).get("input_tokens", 0)
            if isinstance(record.metrics, dict)
            else 0
        )
        try:
            for offset, (document, chunks) in enumerate(prepared_rows):
                if cancelled and cancelled():
                    raise RuntimeError("Shadow index rebuild was cancelled")
                stored_signature = store.document_index_signature(document.document_id)
                expected_signature = self._expected_signature(document, chunks, record)
                if stored_signature == expected_signature:
                    skipped_documents += 1
                    continue
                if stored_signature["chunk_ids"]:
                    store.delete_by_document_id(document.document_id)
                for start in range(0, len(chunks), self.embedding_batch_size):
                    batch = chunks[start : start + self.embedding_batch_size]
                    embeddings = self.embedding_provider.embed_batch(
                        [embedding_text_for_chunk(chunk) for chunk in batch]
                    )
                    store.add_chunks(batch, embeddings)
                    indexed_chunks += len(batch)
                indexed_documents += 1
                if progress:
                    progress("embed", min(90, 10 + round(80 * (offset + 1) / max(1, len(documents)))))
        finally:
            usage_delta = max(
                0,
                int(getattr(self.embedding_provider, "input_tokens_used", 0)) - usage_before,
            )
            actual_tokens = previous_usage + usage_delta
            projected_tokens = int(dry_run.get("projected_input_tokens") or 0)
            variance = (
                abs(actual_tokens - projected_tokens) / projected_tokens
                if projected_tokens
                else 1.0
            )
            self.index_registry.record_metrics(
                record.index_id,
                {
                    "rebuild_usage": {
                        "input_tokens": actual_tokens,
                        "embedding_cost_usd": round(
                            actual_tokens / 1_000_000 * self.embedding_price_per_million_tokens,
                            6,
                        ),
                    },
                    "cost_gate": {
                        "projected_input_tokens": projected_tokens,
                        "actual_input_tokens": actual_tokens,
                        "variance": round(variance, 6),
                        "threshold": 0.15,
                        "passed": variance <= 0.15,
                    },
                },
            )
        if progress:
            progress("build_hnsw", 92)
        store.ensure_hnsw_index()
        return {
            "index_id": record.index_id,
            "table_name": record.table_name,
            "indexed_documents": indexed_documents,
            "indexed_chunks": indexed_chunks,
            "skipped_documents": skipped_documents,
            "stored_chunks": store.count_chunks(),
            "input_tokens": int(getattr(self.embedding_provider, "input_tokens_used", 0)),
            "dry_run": dry_run,
            "cost_gate": self.index_registry.get(record.index_id).metrics.get("cost_gate", {}),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }

    def validate(
        self,
        index_id: str,
        documents: list[Document],
        *,
        benchmark_samples: int = 100,
    ) -> dict:
        record = self.index_registry.get(index_id)
        if record is None:
            raise ValueError(f"Index candidate does not exist: {index_id}")
        store = PgVectorStore(
            self.vector_dsn,
            table_name=record.table_name,
            dimension=record.embedding_dimension,
            create_hnsw=True,
        )
        expected_chunks = []
        expected_hashes: set[str] = set()
        elements_by_document: dict[str, set[str]] = {}
        for original in documents:
            document, chunks = self._chunks_for_document(original, record)
            expected_chunks.extend(chunks)
            content_hash = str(document.metadata.get("content_hash") or "")
            if content_hash:
                expected_hashes.add(content_hash)
            elements_by_document[document.document_id] = {
                element.element_id for element in document.elements
            }
        actual_chunks = store.list_chunks()
        structural = store.validate_index()
        citations_resolvable = all(
            chunk.document_id in elements_by_document
            and (
                not chunk.element_ids
                or set(chunk.element_ids).issubset(elements_by_document[chunk.document_id])
            )
            for chunk in actual_chunks
        )
        benchmark = store.benchmark_hnsw_recall(
            sample_size=max(1, benchmark_samples), top_k=50
        )
        checklist = {
            "document_count_matches": structural["document_count"] == len(documents),
            "chunk_count_matches": structural["chunk_count"] == len(expected_chunks),
            "content_hashes_match": bool(expected_hashes) and store.content_hashes() == expected_hashes,
            "embedding_model_matches": record.embedding_provider == "openai" and record.embedding_model == "text-embedding-3-large",
            "embedding_dimension_matches": record.embedding_dimension == 1536,
            "parser_version_matches": bool(actual_chunks) and all(chunk.metadata.get("parser_version") == record.parser_version for chunk in actual_chunks),
            "chunker_version_matches": bool(actual_chunks) and all(chunk.metadata.get("chunker_version") == record.chunker_version for chunk in actual_chunks),
            "no_empty_vectors": bool(structural["no_empty_vectors"]),
            "no_non_finite_vectors": bool(structural["no_non_finite_vectors"]),
            "no_duplicate_chunk_ids": bool(structural["no_duplicate_chunk_ids"]),
            "citations_resolvable": citations_resolvable,
            "hnsw_recall_passed": bool(benchmark["passed"]),
            "cost_projection_within_15_percent": bool(
                record.metrics.get("cost_gate", {}).get("passed")
            ),
        }
        metrics = {
            **record.metrics,
            **structural,
            "expected_document_count": len(documents),
            "expected_chunk_count": len(expected_chunks),
            "content_hash_count": len(expected_hashes),
            "hnsw": benchmark,
        }
        updated = self.index_registry.record_validation(index_id, checklist, metrics=metrics)
        return {
            "index": updated.model_dump(),
            "checklist": checklist,
            "metrics": metrics,
            "validation_errors": self.index_registry.validation_errors(index_id),
        }


def shadow_index_job_handler(rebuilder: ShadowIndexRebuilder, document_registry):
    def handle(job: dict, update_progress: Callable[[str, int], None], cancelled):
        index_id = str(job.get("payload", {}).get("index_id") or "")
        if not index_id:
            raise ValueError("Shadow index job is missing index_id")
        documents = document_registry.load_documents()
        report = rebuilder.rebuild(
            index_id,
            documents,
            progress=update_progress,
            cancelled=cancelled,
        )
        validation = rebuilder.validate(
            index_id,
            documents,
            benchmark_samples=int(job.get("payload", {}).get("benchmark_samples") or 100),
        )
        return {**report, "validation": validation}

    return handle
