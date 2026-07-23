from __future__ import annotations

from app.services.vectorstore import PgVectorStore


class Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.query = ""
        self.parameters = ()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, query, parameters=()):
        self.query = query
        self.parameters = parameters

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class Connection:
    def __init__(self, rows):
        self.cursor_instance = Cursor(rows)

    def cursor(self):
        return self.cursor_instance


class PsycopgFactory:
    def __init__(self, connections):
        self.connections = iter(connections)
        self.opened = 0

    def connect(self, _dsn):
        self.opened += 1
        return next(self.connections)


class HealthConnection(Connection):
    def close(self):
        self.closed = True


def test_pgvector_search_reconstructs_chunks_after_process_restart():
    store = PgVectorStore.__new__(PgVectorStore)
    store.table_name = "rag_chunks"
    store.chunks = {}
    store.embeddings = {}
    store.conn = Connection(
        [
            (
                "doc-1:0",
                "doc-1",
                "guide.md",
                0,
                2,
                ["Guide", "Retrieval"],
                {
                    "_chunk_element_ids": ["element-1"],
                    "_chunk_modality": "table",
                    "_chunk_parent_element_id": "element-1",
                    "source": "licensed",
                },
                "persistent evidence",
                0.91,
            )
        ]
    )

    results = store.search([0.1, 0.2], top_k=3)

    assert len(results) == 1
    assert results[0]["vector_score"] == 0.91
    assert results[0]["chunk"].chunk_id == "doc-1:0"
    assert results[0]["chunk"].element_ids == ["element-1"]
    assert results[0]["chunk"].modality == "table"
    assert results[0]["chunk"].metadata == {"source": "licensed"}
    assert "document_id" in store.conn.cursor_instance.query


def test_pgvector_hydrates_chunk_metadata_without_reembedding():
    store = PgVectorStore.__new__(PgVectorStore)
    store.table_name = "rag_chunks"
    store.conn = Connection(
        [
            (
                "doc-2:0",
                "doc-2",
                "persistent.md",
                0,
                None,
                ["Persistence"],
                {"modality": "text"},
                "survives restart",
            )
        ]
    )

    store._load_existing()

    assert list(store.chunks) == ["doc-2:0"]
    assert store.chunks["doc-2:0"].text == "survives restart"


def test_pgvector_health_opens_a_fresh_connection_after_database_restart():
    first = HealthConnection([(1,)])
    second = HealthConnection([(1,)])
    store = PgVectorStore.__new__(PgVectorStore)
    store._dsn = "postgresql://example/rag"
    store.psycopg = PsycopgFactory([first, second])
    store._register_vector = lambda _connection: None

    assert store.health() is True
    assert store.health() is True
    assert store.psycopg.opened == 2
    assert first.closed is True
    assert second.closed is True
