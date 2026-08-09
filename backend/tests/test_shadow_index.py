from __future__ import annotations

from datetime import datetime

from app.models.domain import Document, DocumentPage
from app.services.embeddings import BaseEmbeddingProvider
from app.services.index_versions import IndexVersionRegistry
from app.services.shadow_index import ShadowIndexRebuilder


class TokenCountingProvider(BaseEmbeddingProvider):
    def __init__(self):
        self.input_tokens_used = 0

    def embed_text(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.input_tokens_used += sum(len(text) for text in texts)
        return [[1.0] * 1536 for _ in texts]


class FakePgStore:
    signatures: dict[str, dict] = {}
    deleted: list[str] = []
    stored_chunks: dict[str, list] = {}

    def __init__(self, *_args, **_kwargs):
        pass

    def document_index_signature(self, document_id: str) -> dict:
        return self.signatures.get(
            document_id,
            {
                "chunk_ids": [],
                "content_hashes": [],
                "parser_versions": [],
                "chunker_versions": [],
                "embedding_providers": [],
                "embedding_models": [],
                "embedding_dimensions": [],
                "index_versions": [],
            },
        )

    def delete_by_document_id(self, document_id: str):
        self.deleted.append(document_id)
        self.signatures.pop(document_id, None)
        self.stored_chunks.pop(document_id, None)

    def add_chunks(self, chunks, _embeddings):
        if not chunks:
            return
        document_id = chunks[0].document_id
        self.stored_chunks.setdefault(document_id, []).extend(chunks)
        all_chunks = self.stored_chunks[document_id]
        metadata = all_chunks[0].metadata
        self.signatures[document_id] = {
            "chunk_ids": sorted(chunk.chunk_id for chunk in all_chunks),
            "content_hashes": sorted({str(chunk.metadata.get("content_hash") or "") for chunk in all_chunks}),
            "parser_versions": [str(metadata["parser_version"])],
            "chunker_versions": [str(metadata["chunker_version"])],
            "embedding_providers": [str(metadata["embedding_provider"])],
            "embedding_models": [str(metadata["embedding_model"])],
            "embedding_dimensions": [str(metadata["embedding_dimension"])],
            "index_versions": [str(metadata["index_version"])],
        }

    def ensure_hnsw_index(self):
        return None

    def count_chunks(self, **_kwargs):
        return sum(len(chunks) for chunks in self.stored_chunks.values())

    def list_chunks(self, **_kwargs):
        return [
            chunk
            for document_chunks in self.stored_chunks.values()
            for chunk in document_chunks
        ]

    def validate_index(self):
        chunks = self.list_chunks()
        chunk_ids = {chunk.chunk_id for chunk in chunks}
        return {
            "chunk_count": len(chunks),
            "distinct_chunk_count": len(chunk_ids),
            "document_count": len({chunk.document_id for chunk in chunks}),
            "empty_citation_text": sum(not chunk.text for chunk in chunks),
            "empty_embedding_text": 0,
            "non_finite_vectors": 0,
            "no_duplicate_chunk_ids": len(chunk_ids) == len(chunks),
            "no_empty_vectors": bool(chunks),
            "no_non_finite_vectors": bool(chunks),
        }

    def content_hashes(self):
        return {
            str(chunk.metadata.get("content_hash") or "")
            for chunk in self.list_chunks()
            if chunk.metadata.get("content_hash")
        }

    def benchmark_hnsw_recall(self, **_kwargs):
        sample_count = len(self.list_chunks())
        return {
            "sample_count": sample_count,
            "top_k": 50,
            "recall_by_ef_search": {"80": 1.0},
            "selected_ef_search": 80,
            "passed": sample_count > 0,
        }


def test_shadow_rebuild_compares_full_signature_and_enforces_cost_gate(monkeypatch):
    FakePgStore.signatures = {
        "doc": {
            "chunk_ids": ["doc:0"],
            "content_hashes": ["old-hash"],
            "parser_versions": ["builtin-elements-v1"],
            "chunker_versions": ["structure-v2"],
            "embedding_providers": ["openai"],
            "embedding_models": ["text-embedding-3-large"],
            "embedding_dimensions": ["1536"],
            "index_versions": ["v2"],
        }
    }
    FakePgStore.deleted = []
    FakePgStore.stored_chunks = {}
    monkeypatch.setattr("app.services.shadow_index.PgVectorStore", FakePgStore)
    registry = IndexVersionRegistry(":memory:")
    registry.register_candidate(index_id="v2", parser_version="builtin-elements-v1")
    document = Document(
        document_id="doc",
        file_name="guide.md",
        file_path="guide.md",
        file_type="markdown",
        title="Guide",
        created_at=datetime(2026, 8, 9),
        pages=[DocumentPage(text="retrieval evidence " * 20)],
        metadata={"content_hash": "new-hash"},
    )
    provider = TokenCountingProvider()
    rebuilder = ShadowIndexRebuilder(
        index_registry=registry,
        vector_dsn="postgresql://unused",
        embedding_provider=provider,
    )

    first = rebuilder.rebuild("v2", [document])
    second = rebuilder.rebuild("v2", [document])
    validation = rebuilder.validate("v2", [document])

    assert FakePgStore.deleted == ["doc"]
    assert first["indexed_documents"] == 1
    assert second["indexed_documents"] == 0
    assert second["skipped_documents"] == 1
    metrics = registry.get("v2").metrics
    assert metrics["dry_run"]["sample_percentage"] == 10
    assert metrics["cost_gate"]["passed"] is True
    assert metrics["cost_gate"]["variance"] <= 0.15
    assert validation["validation_errors"] == []
    assert validation["metrics"]["document_count"] == 1
    assert validation["metrics"]["chunk_count"] > 0
    assert validation["metrics"]["hnsw"]["sample_count"] > 0
    assert registry.promote("v2").status == "stable"
    assert registry.activate("v2").status == "active"
