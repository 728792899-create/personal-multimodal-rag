from __future__ import annotations

import pytest

from app.models.domain import Chunk
from app.services.vectorstore import (
    MemoryVectorStore,
    PgVectorStore,
    VersionedPgVectorStore,
    versioned_pgvector_table_name,
)
from app.services.index_versions import IndexVersionRegistry


def chunk(
    chunk_id: str,
    document_id: str,
    index: int,
    *,
    kb: str,
    modality: str = "text",
    element_ids: list[str] | None = None,
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id=document_id,
        chunk_index=index,
        text=f"evidence {chunk_id}",
        file_name=f"{document_id}.md",
        modality=modality,
        element_ids=element_ids or [],
        metadata={"knowledge_base_id": kb},
    )


def test_memory_store_filters_and_returns_leaf_context():
    store = MemoryVectorStore()
    rows = [
        chunk("a:0", "a", 0, kb="one"),
        chunk("a:1", "a", 1, kb="one", modality="table", element_ids=["element-1"]),
        chunk("a:2", "a", 2, kb="one"),
        chunk("b:0", "b", 0, kb="two"),
    ]
    store.add_chunks(rows, [[1.0, 0.0], [0.9, 0.1], [0.8, 0.2], [0.0, 1.0]])

    result = store.search(
        [1.0, 0.0],
        top_k=5,
        knowledge_base_ids=["one"],
        modalities=["table"],
    )

    assert [item["chunk"].chunk_id for item in result] == ["a:1"]
    assert [item.chunk_id for item in store.context_chunks("a:1", 1)] == ["a:0", "a:1", "a:2"]
    assert [
        item.chunk_id
        for item in store.chunks_by_element_ids(
            ["element-1"], knowledge_base_ids=["one"]
        )
    ] == ["a:1"]


def test_versioned_table_name_is_deterministic_safe_and_bounded():
    first = versioned_pgvector_table_name("release/2026.08 candidate")
    second = versioned_pgvector_table_name("release/2026.08 candidate")

    assert first == second
    assert first.startswith("rag_chunks_v2_")
    assert len(first) <= 53
    assert ";" not in first and "/" not in first


def test_versioned_store_does_not_register_an_empty_fallback_as_active(
    monkeypatch,
):
    class BootstrapStore:
        def __init__(self, _dsn, *, table_name, dimension, **_kwargs):
            self.table_name = table_name
            self.dimension = dimension
            self.index_version = table_name

    monkeypatch.setattr(
        "app.services.vectorstore.PgVectorStore",
        BootstrapStore,
    )
    registry = IndexVersionRegistry(":memory:")

    store = VersionedPgVectorStore(
        "postgresql://unused",
        registry,
        fallback_table="rag_chunks_v2_initial",
        dimension=1536,
    )

    assert registry.active() is None
    assert registry.list() == []
    assert store.index_version == ""
    assert store.health() is False
    with pytest.raises(RuntimeError, match="No validated active index"):
        store.count_chunks()


class RecordingCursor:
    def __init__(self, *, vector_rows=None, sparse_rows=None, generic_rows=None):
        self.vector_rows = vector_rows or []
        self.sparse_rows = sparse_rows or []
        self.generic_rows = generic_rows or []
        self.queries: list[tuple[str, tuple]] = []
        self.current = ""

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, query, parameters=()):
        self.current = " ".join(str(query).split())
        self.queries.append((self.current, tuple(parameters)))

    def fetchone(self):
        if self.current.startswith("SELECT COUNT(*) FROM"):
            return (100,)
        return None

    def fetchall(self):
        if "bm25_score" in self.current:
            return self.sparse_rows
        if "vector_score" in self.current:
            return self.vector_rows
        return self.generic_rows


class RecordingConnection:
    def __init__(self, cursor):
        self.cursor_instance = cursor

    def cursor(self):
        return self.cursor_instance


def test_pgvector_filtered_search_uses_exact_plan_for_small_scope():
    row = (
        "doc:0", "doc", "doc.md", 0, None, [],
        {"_chunk_modality": "text", "knowledge_base_id": "kb"},
        "evidence", 0.92,
    )
    cursor = RecordingCursor(vector_rows=[row])
    store = PgVectorStore.__new__(PgVectorStore)
    store.table_name = "rag_chunks_v2_test"
    store.dimension = 2
    store.default_ef_search = 80
    store.conn = RecordingConnection(cursor)

    result = store.search(
        [0.1, 0.2],
        top_k=3,
        knowledge_base_ids=["kb"],
        modalities=["text"],
    )

    assert result[0]["chunk"].chunk_id == "doc:0"
    assert any("enable_indexscan = off" in query for query, _ in cursor.queries)
    final_query, final_params = cursor.queries[-1]
    assert "knowledge_base_id = ANY(%s)" in final_query
    assert "modality = ANY(%s)" in final_query
    assert final_params[-1] == 3


def test_pgvector_sparse_search_reads_only_matching_postings_with_filters():
    row = (
        "doc:0", "doc", "doc.md", 0, None, [],
        {"_chunk_modality": "table", "knowledge_base_id": "kb"},
        "persistent evidence", 4.2, ["persistent"], 7, 1, 20,
    )
    cursor = RecordingCursor(sparse_rows=[row])
    store = PgVectorStore.__new__(PgVectorStore)
    store.table_name = "rag_chunks_v2_test"
    store.postings_table_name = "rag_chunks_v2_test_postings"
    store.conn = RecordingConnection(cursor)

    result = store.sparse_search(
        ["persistent"],
        top_k=5,
        knowledge_base_ids=["kb"],
        modalities=["table"],
    )

    assert result[0]["bm25_score"] == 4.2
    assert result[0]["matched_terms"] == ["persistent"]
    query, parameters = cursor.queries[-1]
    assert "p.term = ANY(%s)" in query
    assert "p.knowledge_base_id = ANY(%s)" in query
    assert "p.modality = ANY(%s)" in query
    assert parameters[-1] == 5
    assert store.last_sparse_search_stats["posting_visits"] == 7


def test_pgvector_graph_evidence_lookup_uses_jsonb_and_scope_filters():
    row = (
        "doc:0", "doc", "doc.md", 0, None, [],
        {"_chunk_element_ids": ["element-1"], "knowledge_base_id": "kb"},
        "graph evidence",
    )
    cursor = RecordingCursor(generic_rows=[row])
    store = PgVectorStore.__new__(PgVectorStore)
    store.table_name = "rag_chunks_v2_test"
    store.conn = RecordingConnection(cursor)

    chunks = store.chunks_by_element_ids(
        ["element-1"],
        knowledge_base_ids=["kb"],
        limit=20,
    )

    assert [chunk.chunk_id for chunk in chunks] == ["doc:0"]
    query, parameters = cursor.queries[-1]
    assert "metadata -> '_chunk_element_ids'" in query
    assert "?| %s" in query
    assert "knowledge_base_id = ANY(%s)" in query
    assert parameters == (["element-1"], ["kb"], 20)
