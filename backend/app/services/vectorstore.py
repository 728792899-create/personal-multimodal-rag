from __future__ import annotations

import math
import json
import re
from abc import ABC, abstractmethod
from pathlib import Path

from app.models.domain import Chunk


class BaseVectorStore(ABC):
    @abstractmethod
    def add_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        raise NotImplementedError

    @abstractmethod
    def search(self, query_embedding: list[float], top_k: int = 5) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def delete_by_document_id(self, document_id: str) -> None:
        raise NotImplementedError


class MemoryVectorStore(BaseVectorStore):
    def __init__(self):
        self.chunks: dict[str, Chunk] = {}
        self.embeddings: dict[str, list[float]] = {}

    def add_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings length mismatch")
        for chunk, embedding in zip(chunks, embeddings):
            self.chunks[chunk.chunk_id] = chunk
            self.embeddings[chunk.chunk_id] = embedding

    def search(self, query_embedding: list[float], top_k: int = 5) -> list[dict]:
        scored = [
            {
                "chunk": chunk,
                "vector_score": self._cosine(query_embedding, self.embeddings[chunk_id]),
            }
            for chunk_id, chunk in self.chunks.items()
        ]
        return sorted(scored, key=lambda item: item["vector_score"], reverse=True)[:top_k]

    def delete_by_document_id(self, document_id: str) -> None:
        chunk_ids = [chunk_id for chunk_id, chunk in self.chunks.items() if chunk.document_id == document_id]
        for chunk_id in chunk_ids:
            self.chunks.pop(chunk_id, None)
            self.embeddings.pop(chunk_id, None)

    def _cosine(self, left: list[float], right: list[float]) -> float:
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if not left_norm or not right_norm:
            return 0.0
        return max(0.0, sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm))


class ChromaVectorStore(BaseVectorStore):
    def __init__(
        self,
        persist_path: str,
        collection_name: str = "personal_knowledge",
        expected_dimension: int = 0,
        index_version: str = "",
        embedding_model: str = "",
    ):
        try:
            import chromadb
        except ImportError as exc:
            raise RuntimeError("Install chromadb to use ChromaVectorStore") from exc

        Path(persist_path).mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=persist_path)
        metadata = {
            "embedding_dimension": int(expected_dimension or 0),
            "index_version": index_version or "unspecified",
            "embedding_model": embedding_model or "unspecified",
        }
        self.collection = self.client.get_or_create_collection(name=collection_name, metadata=metadata)
        self.expected_dimension = int(expected_dimension or 0)
        stored_metadata = getattr(self.collection, "metadata", None) or {}
        stored_dimension = int(stored_metadata.get("embedding_dimension") or 0)
        stored_version = str(stored_metadata.get("index_version") or "")
        if self.expected_dimension and stored_dimension and stored_dimension != self.expected_dimension:
            raise ValueError(
                f"Chroma collection embedding dimension mismatch: stored {stored_dimension}, expected {self.expected_dimension}"
            )
        if index_version and stored_version and stored_version not in {"unspecified", index_version}:
            raise ValueError(
                f"Chroma collection index version mismatch: stored {stored_version}, expected {index_version}"
            )
        self.chunks: dict[str, Chunk] = {}
        self.embeddings: dict[str, list[float]] = {}
        self._load_existing()

    def add_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings length mismatch")
        if self.expected_dimension and any(len(item) != self.expected_dimension for item in embeddings):
            actual = len(embeddings[0]) if embeddings else 0
            raise ValueError(f"Chroma embedding dimension mismatch: expected {self.expected_dimension}, got {actual}")
        ids = [chunk.chunk_id for chunk in chunks]
        metadatas = [self._metadata(chunk) for chunk in chunks]
        documents = [chunk.text for chunk in chunks]
        self.collection.upsert(ids=ids, embeddings=embeddings, metadatas=metadatas, documents=documents)
        for chunk, embedding in zip(chunks, embeddings):
            self.chunks[chunk.chunk_id] = chunk
            self.embeddings[chunk.chunk_id] = embedding

    def search(self, query_embedding: list[float], top_k: int = 5) -> list[dict]:
        if not self.chunks:
            return []
        result = self.collection.query(query_embeddings=[query_embedding], n_results=min(top_k, len(self.chunks)))
        ids = result.get("ids", [[]])[0]
        distances = result.get("distances", [[]])[0]
        return [
            {
                "chunk": self.chunks[chunk_id],
                "vector_score": max(0.0, 1 - float(distance)),
            }
            for chunk_id, distance in zip(ids, distances)
            if chunk_id in self.chunks
        ]

    def delete_by_document_id(self, document_id: str) -> None:
        ids = [chunk_id for chunk_id, chunk in self.chunks.items() if chunk.document_id == document_id]
        if ids:
            self.collection.delete(ids=ids)
        for chunk_id in ids:
            self.chunks.pop(chunk_id, None)
            self.embeddings.pop(chunk_id, None)

    def _metadata(self, chunk: Chunk) -> dict:
        return {
            "document_id": chunk.document_id,
            "file_name": chunk.file_name,
            "chunk_index": chunk.chunk_index,
            "page_number": chunk.page_number or 0,
            "heading_path": json.dumps(chunk.heading_path, ensure_ascii=False),
            "metadata": json.dumps(chunk.metadata, ensure_ascii=False),
        }

    def _load_existing(self) -> None:
        try:
            result = self.collection.get(include=["metadatas", "documents", "embeddings"])
        except Exception:
            return
        ids = result.get("ids", []) or []
        documents = result.get("documents", []) or []
        metadatas = result.get("metadatas", []) or []
        embeddings = result.get("embeddings")
        if embeddings is None:
            embeddings = []
        for idx, chunk_id in enumerate(ids):
            metadata = metadatas[idx] if idx < len(metadatas) and metadatas[idx] else {}
            text = documents[idx] if idx < len(documents) and documents[idx] else ""
            chunk = self._chunk_from_metadata(chunk_id, text, metadata)
            self.chunks[chunk_id] = chunk
            if idx < len(embeddings) and embeddings[idx] is not None:
                embedding = embeddings[idx]
                self.embeddings[chunk_id] = embedding.tolist() if hasattr(embedding, "tolist") else list(embedding)

    def _chunk_from_metadata(self, chunk_id: str, text: str, metadata: dict) -> Chunk:
        return Chunk(
            chunk_id=chunk_id,
            document_id=str(metadata.get("document_id", "")),
            file_name=str(metadata.get("file_name", "")),
            chunk_index=int(metadata.get("chunk_index", 0) or 0),
            page_number=int(metadata["page_number"]) if metadata.get("page_number") else None,
            heading_path=self._loads_list(metadata.get("heading_path")),
            metadata=self._loads_dict(metadata.get("metadata")),
            text=text,
        )

    def _loads_list(self, value) -> list[str]:
        if not value:
            return []
        if isinstance(value, list):
            return [str(item) for item in value]
        try:
            loaded = json.loads(value)
            return [str(item) for item in loaded] if isinstance(loaded, list) else []
        except Exception:
            return []

    def _loads_dict(self, value) -> dict:
        if not value:
            return {}
        if isinstance(value, dict):
            return value
        try:
            loaded = json.loads(value)
            return loaded if isinstance(loaded, dict) else {}
        except Exception:
            return {}


class PgVectorStore(BaseVectorStore):
    def __init__(self, dsn: str, table_name: str = "rag_chunks", dimension: int = 1536):
        if not dsn:
            raise ValueError("PGVECTOR_DSN is required when VECTOR_STORE=pgvector")
        try:
            import psycopg
            from pgvector.psycopg import register_vector
        except ImportError as exc:
            raise RuntimeError("Install psycopg[binary] and pgvector to use PgVectorStore") from exc

        self.psycopg = psycopg
        self.table_name = self._validate_identifier(table_name)
        self.dimension = dimension
        self.conn = psycopg.connect(dsn)
        register_vector(self.conn)
        self.chunks: dict[str, Chunk] = {}
        self.embeddings: dict[str, list[float]] = {}
        self._ensure_table()

    def add_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings length mismatch")
        with self.conn.cursor() as cur:
            for chunk, embedding in zip(chunks, embeddings):
                cur.execute(
                    f"""
                    INSERT INTO {self.table_name}
                    (chunk_id, document_id, file_name, chunk_index, page_number, heading_path, metadata, text, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (chunk_id) DO UPDATE SET
                      text = EXCLUDED.text,
                      embedding = EXCLUDED.embedding,
                      metadata = EXCLUDED.metadata
                    """,
                    (
                        chunk.chunk_id,
                        chunk.document_id,
                        chunk.file_name,
                        chunk.chunk_index,
                        chunk.page_number,
                        json.dumps(chunk.heading_path, ensure_ascii=False),
                        json.dumps(chunk.metadata, ensure_ascii=False),
                        chunk.text,
                        embedding,
                    ),
                )
                self.chunks[chunk.chunk_id] = chunk
                self.embeddings[chunk.chunk_id] = embedding
        self.conn.commit()

    def search(self, query_embedding: list[float], top_k: int = 5) -> list[dict]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT chunk_id, 1 - (embedding <=> %s) AS vector_score
                FROM {self.table_name}
                ORDER BY embedding <=> %s
                LIMIT %s
                """,
                (query_embedding, query_embedding, top_k),
            )
            rows = cur.fetchall()
        return [
            {"chunk": self.chunks[chunk_id], "vector_score": max(0.0, float(score or 0))}
            for chunk_id, score in rows
            if chunk_id in self.chunks
        ]

    def delete_by_document_id(self, document_id: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(f"DELETE FROM {self.table_name} WHERE document_id = %s", (document_id,))
        self.conn.commit()
        ids = [chunk_id for chunk_id, chunk in self.chunks.items() if chunk.document_id == document_id]
        for chunk_id in ids:
            self.chunks.pop(chunk_id, None)
            self.embeddings.pop(chunk_id, None)

    def _ensure_table(self) -> None:
        with self.conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                  chunk_id TEXT PRIMARY KEY,
                  document_id TEXT NOT NULL,
                  file_name TEXT NOT NULL,
                  chunk_index INTEGER NOT NULL,
                  page_number INTEGER,
                  heading_path JSONB,
                  metadata JSONB,
                  text TEXT NOT NULL,
                  embedding vector({self.dimension}) NOT NULL
                )
                """
            )
            cur.execute(f"CREATE INDEX IF NOT EXISTS {self.table_name}_document_id_idx ON {self.table_name}(document_id)")
        self.conn.commit()

    def _validate_identifier(self, identifier: str) -> str:
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", identifier):
            raise ValueError("PGVECTOR_TABLE must be a simple SQL identifier")
        return identifier
