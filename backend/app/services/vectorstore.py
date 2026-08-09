from __future__ import annotations

import math
import json
import re
import hashlib
from abc import ABC, abstractmethod
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from threading import RLock
from typing import Iterable, Optional

from app.models.domain import Chunk
from app.services.text_utils import tokenize


class BaseVectorStore(ABC):
    supports_persistent_sparse = False
    @abstractmethod
    def add_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        raise NotImplementedError

    @abstractmethod
    def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        *,
        document_ids: Optional[list[str]] = None,
        knowledge_base_ids: Optional[list[str]] = None,
        modalities: Optional[list[str]] = None,
        candidate_count: Optional[int] = None,
        ef_search: Optional[int] = None,
        exact_threshold: int = 2_000,
    ) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def delete_by_document_id(self, document_id: str) -> None:
        raise NotImplementedError

    def health(self) -> bool:
        return True

    def list_chunks(
        self,
        *,
        document_ids: Optional[list[str]] = None,
        knowledge_base_ids: Optional[list[str]] = None,
        modalities: Optional[list[str]] = None,
        limit: Optional[int] = None,
    ) -> list[Chunk]:
        chunks = getattr(self, "chunks", {})
        rows = [
            chunk
            for chunk in chunks.values()
            if _chunk_matches_filters(
                chunk,
                document_ids=document_ids,
                knowledge_base_ids=knowledge_base_ids,
                modalities=modalities,
            )
        ]
        return rows[: max(0, int(limit))] if limit is not None else rows

    def count_chunks(
        self,
        *,
        document_ids: Optional[list[str]] = None,
        knowledge_base_ids: Optional[list[str]] = None,
        modalities: Optional[list[str]] = None,
    ) -> int:
        return len(
            self.list_chunks(
                document_ids=document_ids,
                knowledge_base_ids=knowledge_base_ids,
                modalities=modalities,
            )
        )

    def has_document(self, document_id: str) -> bool:
        return self.count_chunks(document_ids=[document_id]) > 0

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        chunks = getattr(self, "chunks", {})
        return chunks.get(chunk_id)

    def context_chunks(self, chunk_id: str, window: int = 1) -> list[Chunk]:
        leaf = self.get_chunk(chunk_id)
        if leaf is None:
            return []
        radius = max(0, min(int(window), 3))
        return [
            chunk
            for chunk in self.list_chunks(document_ids=[leaf.document_id])
            if abs(chunk.chunk_index - leaf.chunk_index) <= radius
        ]

    def sparse_search(
        self,
        query_tokens: Iterable[str],
        *,
        top_k: int,
        document_ids: Optional[list[str]] = None,
        knowledge_base_ids: Optional[list[str]] = None,
        modalities: Optional[list[str]] = None,
    ) -> list[dict]:
        raise NotImplementedError("Persistent sparse search is not supported")

    def chunks_by_element_ids(
        self,
        element_ids: Iterable[str],
        *,
        document_ids: Optional[list[str]] = None,
        knowledge_base_ids: Optional[list[str]] = None,
        modalities: Optional[list[str]] = None,
        limit: int = 100,
    ) -> list[Chunk]:
        selected = _normalized_filter(element_ids)
        if not selected:
            return []
        return [
            chunk
            for chunk in self.list_chunks(
                document_ids=document_ids,
                knowledge_base_ids=knowledge_base_ids,
                modalities=modalities,
            )
            if selected.intersection(chunk.element_ids)
        ][: max(0, int(limit))]


def _normalized_filter(values: Optional[Iterable[str]]) -> set[str]:
    return {str(value) for value in (values or []) if str(value)}


def _chunk_matches_filters(
    chunk: Chunk,
    *,
    document_ids: Optional[list[str]],
    knowledge_base_ids: Optional[list[str]],
    modalities: Optional[list[str]],
) -> bool:
    document_filter = _normalized_filter(document_ids)
    knowledge_base_filter = _normalized_filter(knowledge_base_ids)
    modality_filter = _normalized_filter(modalities)
    return (
        (not document_filter or chunk.document_id in document_filter)
        and (
            not knowledge_base_filter
            or str(chunk.metadata.get("knowledge_base_id") or "default")
            in knowledge_base_filter
        )
        and (not modality_filter or chunk.modality in modality_filter)
    )


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

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        *,
        document_ids: Optional[list[str]] = None,
        knowledge_base_ids: Optional[list[str]] = None,
        modalities: Optional[list[str]] = None,
        candidate_count: Optional[int] = None,
        ef_search: Optional[int] = None,
        exact_threshold: int = 2_000,
    ) -> list[dict]:
        del ef_search, exact_threshold
        requested = max(1, int(candidate_count or top_k))
        scored = [
            {
                "chunk": chunk,
                "vector_score": self._cosine(query_embedding, self.embeddings[chunk_id]),
            }
            for chunk_id, chunk in self.chunks.items()
            if _chunk_matches_filters(
                chunk,
                document_ids=document_ids,
                knowledge_base_ids=knowledge_base_ids,
                modalities=modalities,
            )
        ]
        return sorted(scored, key=lambda item: item["vector_score"], reverse=True)[:requested]

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

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        *,
        document_ids: Optional[list[str]] = None,
        knowledge_base_ids: Optional[list[str]] = None,
        modalities: Optional[list[str]] = None,
        candidate_count: Optional[int] = None,
        ef_search: Optional[int] = None,
        exact_threshold: int = 2_000,
    ) -> list[dict]:
        del ef_search, exact_threshold
        matching = self.list_chunks(
            document_ids=document_ids,
            knowledge_base_ids=knowledge_base_ids,
            modalities=modalities,
        )
        if not matching:
            return []
        requested = max(1, int(candidate_count or top_k))
        where = self._where_filter(
            document_ids=document_ids,
            knowledge_base_ids=knowledge_base_ids,
            modalities=modalities,
        )
        query = {
            "query_embeddings": [query_embedding],
            "n_results": min(requested, len(matching)),
        }
        if where:
            query["where"] = where
        result = self.collection.query(**query)
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

    def health(self) -> bool:
        return bool(self.client.heartbeat())

    def _metadata(self, chunk: Chunk) -> dict:
        return {
            "document_id": chunk.document_id,
            "knowledge_base_id": str(chunk.metadata.get("knowledge_base_id") or "default"),
            "modality": chunk.modality,
            "file_name": chunk.file_name,
            "chunk_index": chunk.chunk_index,
            "page_number": chunk.page_number or 0,
            "heading_path": json.dumps(chunk.heading_path, ensure_ascii=False),
            "metadata": json.dumps(chunk.metadata, ensure_ascii=False),
        }

    def _where_filter(
        self,
        *,
        document_ids: Optional[list[str]],
        knowledge_base_ids: Optional[list[str]],
        modalities: Optional[list[str]],
    ) -> dict:
        clauses: list[dict] = []
        for field, values in (
            ("document_id", document_ids),
            ("knowledge_base_id", knowledge_base_ids),
            ("modality", modalities),
        ):
            selected = sorted(_normalized_filter(values))
            if selected:
                clauses.append({field: {"$in": selected}})
        if not clauses:
            return {}
        return clauses[0] if len(clauses) == 1 else {"$and": clauses}

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


def versioned_pgvector_table_name(index_version: str, prefix: str = "rag_chunks_v2") -> str:
    """Create a deterministic, injection-safe PostgreSQL table name.

    Human-readable index ids are deliberately not interpolated directly into
    SQL. The short hash also keeps distinct ids that normalize to the same slug
    from colliding.
    """

    cleaned = re.sub(r"[^a-z0-9]+", "_", str(index_version).lower()).strip("_")
    cleaned = (cleaned or "index")[:28]
    digest = hashlib.sha256(str(index_version).encode("utf-8")).hexdigest()[:10]
    table_name = f"{prefix}_{cleaned}_{digest}"
    if len(table_name) > 63:
        table_name = f"{prefix[:40]}_{digest}"
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", table_name):
        raise ValueError("Unable to derive a safe pgvector table name")
    return table_name


class PgVectorStore(BaseVectorStore):
    """PostgreSQL/pgvector store that keeps vectors and chunks in PostgreSQL.

    Unlike the legacy implementation, construction does not hydrate all chunk
    text or any embeddings into the application process. Callers use
    ``list_chunks`` when they explicitly need lexical-index source rows, and
    filtered vector search is pushed down to PostgreSQL.
    """

    supports_persistent_sparse = True

    def __init__(
        self,
        dsn: str,
        table_name: str = "rag_chunks_v2_initial",
        dimension: int = 1536,
        *,
        index_version: str = "",
        create_hnsw: bool = True,
        hnsw_m: int = 16,
        hnsw_ef_construction: int = 128,
        default_ef_search: int = 80,
        exact_filter_threshold: int = 2_000,
        ensure_schema: bool = True,
    ):
        if not dsn:
            raise ValueError("PGVECTOR_DSN is required when VECTOR_STORE=pgvector")
        try:
            import psycopg
            from pgvector.psycopg import register_vector
        except ImportError as exc:
            raise RuntimeError("Install psycopg[binary] and pgvector to use PgVectorStore") from exc

        self.psycopg = psycopg
        self._dsn = dsn
        self._register_vector = register_vector
        if index_version:
            table_name = versioned_pgvector_table_name(index_version)
        self.table_name = self._validate_identifier(table_name)
        self.postings_table_name = self._related_identifier("postings")
        self.dimension = max(1, int(dimension))
        self.index_version = index_version or self.table_name
        self.hnsw_m = max(2, min(int(hnsw_m), 100))
        self.hnsw_ef_construction = max(4, min(int(hnsw_ef_construction), 1_000))
        self.default_ef_search = max(1, min(int(default_ef_search), 1_000))
        self.exact_filter_threshold = max(0, int(exact_filter_threshold))
        # Compatibility only. PostgreSQL is the source of truth and these maps
        # are intentionally never hydrated or populated.
        self.chunks: dict[str, Chunk] = {}
        self.embeddings: dict[str, list[float]] = {}
        self.last_sparse_search_stats = {
            "query_terms": 0,
            "posting_visits": 0,
            "evaluated_chunks": 0,
            "total_chunks": 0,
        }
        if ensure_schema:
            self._ensure_table(create_hnsw=create_hnsw)

    def add_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings length mismatch")
        if any(len(embedding) != self.dimension for embedding in embeddings):
            actual = len(embeddings[0]) if embeddings else 0
            raise ValueError(
                f"Pgvector embedding dimension mismatch: expected {self.dimension}, got {actual}"
            )
        with self._connection() as connection:
            with connection.cursor() as cur:
                for chunk, embedding in zip(chunks, embeddings):
                    knowledge_base_id = str(
                        chunk.metadata.get("knowledge_base_id") or "default"
                    )
                    embedding_text = str(
                        chunk.metadata.get("embedding_text") or chunk.text
                    )
                    token_counts = Counter(tokenize(embedding_text))
                    token_count = sum(token_counts.values())
                    content_hash = str(chunk.metadata.get("content_hash") or "")
                    stored_metadata = {
                        **chunk.metadata,
                        "_chunk_element_ids": chunk.element_ids,
                        "_chunk_modality": chunk.modality,
                        "_chunk_parent_element_id": chunk.parent_element_id,
                    }
                    cur.execute(
                        f"""
                        INSERT INTO {self.table_name}
                        (chunk_id, document_id, knowledge_base_id, modality,
                         file_name, chunk_index, page_number, heading_path,
                         metadata, text, embedding_text, content_hash, token_count, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (chunk_id) DO UPDATE SET
                          document_id = EXCLUDED.document_id,
                          knowledge_base_id = EXCLUDED.knowledge_base_id,
                          modality = EXCLUDED.modality,
                          file_name = EXCLUDED.file_name,
                          chunk_index = EXCLUDED.chunk_index,
                          page_number = EXCLUDED.page_number,
                          heading_path = EXCLUDED.heading_path,
                          text = EXCLUDED.text,
                          embedding_text = EXCLUDED.embedding_text,
                          content_hash = EXCLUDED.content_hash,
                          token_count = EXCLUDED.token_count,
                          embedding = EXCLUDED.embedding,
                          metadata = EXCLUDED.metadata
                        """,
                        (
                            chunk.chunk_id,
                            chunk.document_id,
                            knowledge_base_id,
                            chunk.modality,
                            chunk.file_name,
                            chunk.chunk_index,
                            chunk.page_number,
                            json.dumps(chunk.heading_path, ensure_ascii=False),
                            json.dumps(stored_metadata, ensure_ascii=False),
                            chunk.text,
                            embedding_text,
                            content_hash,
                            token_count,
                            embedding,
                        ),
                    )
                    cur.execute(
                        f"DELETE FROM {self.postings_table_name} WHERE chunk_id = %s",
                        (chunk.chunk_id,),
                    )
                    for term, frequency in token_counts.items():
                        cur.execute(
                            f"""
                            INSERT INTO {self.postings_table_name}
                              (term, chunk_id, document_id, knowledge_base_id,
                               modality, term_frequency, chunk_length)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                term,
                                chunk.chunk_id,
                                chunk.document_id,
                                knowledge_base_id,
                                chunk.modality,
                                int(frequency),
                                token_count,
                            ),
                        )
            connection.commit()

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        *,
        document_ids: Optional[list[str]] = None,
        knowledge_base_ids: Optional[list[str]] = None,
        modalities: Optional[list[str]] = None,
        candidate_count: Optional[int] = None,
        ef_search: Optional[int] = None,
        exact_threshold: int = 2_000,
    ) -> list[dict]:
        if hasattr(self, "dimension") and len(query_embedding) != self.dimension:
            raise ValueError(
                f"Query embedding dimension mismatch: expected {self.dimension}, got {len(query_embedding)}"
            )
        requested = max(1, int(candidate_count or top_k))
        where_sql, filter_params = self._filter_sql(
            document_ids=document_ids,
            knowledge_base_ids=knowledge_base_ids,
            modalities=modalities,
        )
        selected_ef_search = min(
            1_000,
            max(
                requested,
                int(ef_search or getattr(self, "default_ef_search", 80)),
            ),
        )
        threshold = max(
            0,
            int(
                exact_threshold
                if exact_threshold is not None
                else getattr(self, "exact_filter_threshold", 2_000)
            ),
        )
        with self._connection() as connection:
            with connection.cursor() as cur:
                use_exact = False
                if where_sql and threshold:
                    cur.execute(
                        f"SELECT COUNT(*) FROM {self.table_name}{where_sql}",
                        tuple(filter_params),
                    )
                    count_row = cur.fetchone()
                    use_exact = bool(count_row and int(count_row[0] or 0) <= threshold)
                if use_exact:
                    cur.execute("SET LOCAL enable_indexscan = off")
                    cur.execute("SET LOCAL enable_bitmapscan = off")
                else:
                    cur.execute(
                        "SELECT set_config('hnsw.ef_search', %s, true)",
                        (str(selected_ef_search),),
                    )
                    cur.execute(
                        "SELECT set_config('hnsw.iterative_scan', 'strict_order', true)"
                    )
                cur.execute(
                    f"""
                    SELECT chunk_id, document_id, file_name, chunk_index,
                           page_number, heading_path, metadata, text,
                           1 - (embedding <=> %s) AS vector_score
                    FROM {self.table_name}
                    {where_sql}
                    ORDER BY embedding <=> %s
                    LIMIT %s
                    """,
                    (
                        query_embedding,
                        *filter_params,
                        query_embedding,
                        requested,
                    ),
                )
                rows = cur.fetchall()
        return [
            {
                "chunk": self._chunk_from_row(row),
                "vector_score": max(0.0, float(row[8] or 0)),
            }
            for row in rows
        ]

    def list_chunks(
        self,
        *,
        document_ids: Optional[list[str]] = None,
        knowledge_base_ids: Optional[list[str]] = None,
        modalities: Optional[list[str]] = None,
        limit: Optional[int] = None,
    ) -> list[Chunk]:
        where_sql, filter_params = self._filter_sql(
            document_ids=document_ids,
            knowledge_base_ids=knowledge_base_ids,
            modalities=modalities,
        )
        limit_sql = ""
        params = list(filter_params)
        if limit is not None:
            limit_sql = " LIMIT %s"
            params.append(max(0, int(limit)))
        with self._connection() as connection:
            with connection.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT chunk_id, document_id, file_name, chunk_index,
                           page_number, heading_path, metadata, text
                    FROM {self.table_name}{where_sql}
                    ORDER BY document_id, chunk_index{limit_sql}
                    """,
                    tuple(params),
                )
                rows = cur.fetchall()
        return [self._chunk_from_row(row) for row in rows]

    def document_index_signature(self, document_id: str) -> dict:
        with self._connection() as connection:
            with connection.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT chunk_id, content_hash,
                           metadata ->> 'parser_version' AS parser_version,
                           metadata ->> 'chunker_version' AS chunker_version,
                           metadata ->> 'embedding_provider' AS embedding_provider,
                           metadata ->> 'embedding_model' AS embedding_model,
                           metadata ->> 'embedding_dimension' AS embedding_dimension,
                           metadata ->> 'index_version' AS index_version
                    FROM {self.table_name}
                    WHERE document_id = %s ORDER BY chunk_id
                    """,
                    (document_id,),
                )
                rows = cur.fetchall()
        return {
            "chunk_ids": [str(row[0]) for row in rows],
            "content_hashes": sorted({str(row[1] or "") for row in rows}),
            "parser_versions": sorted({str(row[2] or "") for row in rows}),
            "chunker_versions": sorted({str(row[3] or "") for row in rows}),
            "embedding_providers": sorted({str(row[4] or "") for row in rows}),
            "embedding_models": sorted({str(row[5] or "") for row in rows}),
            "embedding_dimensions": sorted({str(row[6] or "") for row in rows}),
            "index_versions": sorted({str(row[7] or "") for row in rows}),
        }

    def chunks_by_element_ids(
        self,
        element_ids: Iterable[str],
        *,
        document_ids: Optional[list[str]] = None,
        knowledge_base_ids: Optional[list[str]] = None,
        modalities: Optional[list[str]] = None,
        limit: int = 100,
    ) -> list[Chunk]:
        selected = sorted(_normalized_filter(element_ids))
        if not selected:
            return []
        filter_sql, filter_params = self._filter_sql(
            document_ids=document_ids,
            knowledge_base_ids=knowledge_base_ids,
            modalities=modalities,
        )
        filters = (
            " AND " + filter_sql.removeprefix(" WHERE ") if filter_sql else ""
        )
        with self._connection() as connection:
            with connection.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT chunk_id, document_id, file_name, chunk_index,
                           page_number, heading_path, metadata, text
                    FROM {self.table_name}
                    WHERE COALESCE(
                      metadata -> '_chunk_element_ids',
                      metadata -> 'element_ids',
                      '[]'::jsonb
                    ) ?| %s{filters}
                    ORDER BY document_id, chunk_index
                    LIMIT %s
                    """,
                    (selected, *filter_params, max(0, min(int(limit), 1_000))),
                )
                rows = cur.fetchall()
        return [self._chunk_from_row(row) for row in rows]

    def count_chunks(
        self,
        *,
        document_ids: Optional[list[str]] = None,
        knowledge_base_ids: Optional[list[str]] = None,
        modalities: Optional[list[str]] = None,
    ) -> int:
        where_sql, params = self._filter_sql(
            document_ids=document_ids,
            knowledge_base_ids=knowledge_base_ids,
            modalities=modalities,
        )
        with self._connection() as connection:
            with connection.cursor() as cur:
                cur.execute(
                    f"SELECT COUNT(*) FROM {self.table_name}{where_sql}",
                    tuple(params),
                )
                row = cur.fetchone()
        return int(row[0] or 0) if row else 0

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        with self._connection() as connection:
            with connection.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT chunk_id, document_id, file_name, chunk_index,
                           page_number, heading_path, metadata, text
                    FROM {self.table_name} WHERE chunk_id = %s
                    """,
                    (chunk_id,),
                )
                row = cur.fetchone()
        return self._chunk_from_row(row) if row else None

    def context_chunks(self, chunk_id: str, window: int = 1) -> list[Chunk]:
        radius = max(0, min(int(window), 3))
        with self._connection() as connection:
            with connection.cursor() as cur:
                cur.execute(
                    f"SELECT document_id, chunk_index FROM {self.table_name} "
                    "WHERE chunk_id = %s",
                    (chunk_id,),
                )
                leaf = cur.fetchone()
                if not leaf:
                    return []
                cur.execute(
                    f"""
                    SELECT chunk_id, document_id, file_name, chunk_index,
                           page_number, heading_path, metadata, text
                    FROM {self.table_name}
                    WHERE document_id = %s AND chunk_index BETWEEN %s AND %s
                    ORDER BY chunk_index
                    """,
                    (
                        str(leaf[0]),
                        int(leaf[1]) - radius,
                        int(leaf[1]) + radius,
                    ),
                )
                rows = cur.fetchall()
        return [self._chunk_from_row(row) for row in rows]

    def sparse_search(
        self,
        query_tokens: Iterable[str],
        *,
        top_k: int,
        document_ids: Optional[list[str]] = None,
        knowledge_base_ids: Optional[list[str]] = None,
        modalities: Optional[list[str]] = None,
    ) -> list[dict]:
        terms = list(dict.fromkeys(str(term) for term in query_tokens if str(term)))
        requested = max(0, int(top_k))
        if not terms or not requested:
            self.last_sparse_search_stats = {
                "query_terms": len(terms),
                "posting_visits": 0,
                "evaluated_chunks": 0,
                "total_chunks": self.count_chunks(
                    document_ids=document_ids,
                    knowledge_base_ids=knowledge_base_ids,
                    modalities=modalities,
                ),
            }
            return []
        corpus_where, corpus_params = self._filter_sql(
            document_ids=document_ids,
            knowledge_base_ids=knowledge_base_ids,
            modalities=modalities,
            alias="c",
        )
        posting_where, posting_params = self._filter_sql(
            document_ids=document_ids,
            knowledge_base_ids=knowledge_base_ids,
            modalities=modalities,
            alias="p",
        )
        posting_filters = (
            " AND " + posting_where.removeprefix(" WHERE ")
            if posting_where
            else ""
        )
        with self._connection() as connection:
            with connection.cursor() as cur:
                cur.execute(
                    f"""
                    WITH corpus AS (
                      SELECT COUNT(*)::DOUBLE PRECISION AS total_chunks,
                             GREATEST(COALESCE(AVG(c.token_count), 0), 1)::DOUBLE PRECISION AS avg_len
                      FROM {self.table_name} c{corpus_where}
                    ),
                    term_df AS (
                      SELECT p.term, COUNT(*)::DOUBLE PRECISION AS df
                      FROM {self.postings_table_name} p
                      WHERE p.term = ANY(%s){posting_filters}
                      GROUP BY p.term
                    ),
                    scored AS (
                      SELECT p.chunk_id,
                             SUM(
                               LN(1 + (corpus.total_chunks - term_df.df + 0.5)
                                 / (term_df.df + 0.5))
                               * (p.term_frequency * 2.5)
                                 / (p.term_frequency + 1.5
                                   * (0.25 + 0.75 * p.chunk_length / corpus.avg_len))
                             ) AS bm25_score,
                             ARRAY_AGG(DISTINCT p.term ORDER BY p.term) AS matched_terms
                      FROM {self.postings_table_name} p
                      JOIN term_df ON term_df.term = p.term
                      CROSS JOIN corpus
                      WHERE p.term = ANY(%s){posting_filters}
                      GROUP BY p.chunk_id
                    )
                    SELECT c.chunk_id, c.document_id, c.file_name, c.chunk_index,
                           c.page_number, c.heading_path, c.metadata, c.text,
                           scored.bm25_score, scored.matched_terms,
                           (SELECT COALESCE(SUM(df), 0) FROM term_df) AS posting_visits,
                           COUNT(*) OVER () AS evaluated_chunks,
                           (SELECT total_chunks FROM corpus) AS total_chunks
                    FROM scored
                    JOIN {self.table_name} c ON c.chunk_id = scored.chunk_id
                    ORDER BY scored.bm25_score DESC, c.chunk_id
                    LIMIT %s
                    """,
                    (
                        *corpus_params,
                        terms,
                        *posting_params,
                        terms,
                        *posting_params,
                        requested,
                    ),
                )
                rows = cur.fetchall()
        if rows:
            self.last_sparse_search_stats = {
                "query_terms": len(terms),
                "posting_visits": int(rows[0][10] or 0),
                "evaluated_chunks": int(rows[0][11] or 0),
                "total_chunks": int(rows[0][12] or 0),
            }
        else:
            self.last_sparse_search_stats = {
                "query_terms": len(terms),
                "posting_visits": 0,
                "evaluated_chunks": 0,
                "total_chunks": self.count_chunks(
                    document_ids=document_ids,
                    knowledge_base_ids=knowledge_base_ids,
                    modalities=modalities,
                ),
            }
        return [
            {
                "chunk": self._chunk_from_row(row),
                "bm25_score": float(row[8] or 0),
                "matched_terms": [str(term) for term in (row[9] or [])],
            }
            for row in rows
        ]

    def delete_by_document_id(self, document_id: str) -> None:
        with self._connection() as connection:
            with connection.cursor() as cur:
                cur.execute(f"DELETE FROM {self.table_name} WHERE document_id = %s", (document_id,))
            connection.commit()

    def health(self) -> bool:
        with self._connection() as connection:
            with connection.cursor() as cur:
                cur.execute("SELECT 1")
                row = cur.fetchone()
        return bool(row and int(row[0]) == 1)

    def ensure_hnsw_index(self) -> None:
        if self.dimension > 2_000:
            raise ValueError("pgvector HNSW vector indexes support at most 2000 dimensions")
        index_name = self._related_identifier("embedding_hnsw_idx")
        with self._connection() as connection:
            with connection.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS {index_name}
                    ON {self.table_name}
                    USING hnsw (embedding vector_cosine_ops)
                    WITH (m = {self.hnsw_m}, ef_construction = {self.hnsw_ef_construction})
                    """
                )
            connection.commit()

    def validate_index(self) -> dict:
        with self._connection() as connection:
            with connection.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT COUNT(*) AS chunk_count,
                           COUNT(DISTINCT chunk_id) AS distinct_chunk_count,
                           COUNT(DISTINCT document_id) AS document_count,
                           COUNT(*) FILTER (WHERE text = '') AS empty_citation_text,
                           COUNT(*) FILTER (
                             WHERE embedding_text = '' OR vector_norm(embedding) = 0
                           ) AS empty_embedding_text,
                           COUNT(*) FILTER (
                             WHERE embedding::text ~* '(NaN|Infinity)'
                           ) AS non_finite_vectors
                    FROM {self.table_name}
                    """
                )
                row = cur.fetchone()
        chunk_count = int(row[0] or 0) if row else 0
        return {
            "chunk_count": chunk_count,
            "distinct_chunk_count": int(row[1] or 0) if row else 0,
            "document_count": int(row[2] or 0) if row else 0,
            "empty_citation_text": int(row[3] or 0) if row else 0,
            "empty_embedding_text": int(row[4] or 0) if row else 0,
            "non_finite_vectors": int(row[5] or 0) if row else 0,
            "no_duplicate_chunk_ids": bool(row and int(row[1] or 0) == chunk_count),
            "no_empty_vectors": bool(row and int(row[4] or 0) == 0),
            "no_non_finite_vectors": bool(row and int(row[5] or 0) == 0),
        }

    def content_hashes(self) -> set[str]:
        with self._connection() as connection:
            with connection.cursor() as cur:
                cur.execute(
                    f"SELECT DISTINCT content_hash FROM {self.table_name} "
                    "WHERE content_hash <> ''"
                )
                rows = cur.fetchall()
        return {str(row[0]) for row in rows if row and row[0]}

    def benchmark_hnsw_recall(
        self,
        *,
        sample_size: int = 100,
        top_k: int = 50,
        ef_search_values: tuple[int, ...] = (40, 80, 120, 200),
    ) -> dict:
        """Compare HNSW neighbors with exact cosine search on sampled vectors."""

        sample_size = max(1, min(int(sample_size), 500))
        top_k = max(1, min(int(top_k), 200))
        values = tuple(
            sorted({max(top_k, min(int(value), 1_000)) for value in ef_search_values})
        )
        with self._connection() as connection:
            with connection.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT chunk_id, embedding FROM {self.table_name}
                    ORDER BY md5(chunk_id) LIMIT %s
                    """,
                    (sample_size,),
                )
                samples = cur.fetchall()
                recall_totals = {value: 0.0 for value in values}
                for _, query_embedding in samples:
                    cur.execute("SET LOCAL enable_indexscan = off")
                    cur.execute("SET LOCAL enable_bitmapscan = off")
                    cur.execute(
                        f"""
                        SELECT chunk_id FROM {self.table_name}
                        ORDER BY embedding <=> %s LIMIT %s
                        """,
                        (query_embedding, top_k),
                    )
                    exact = {str(row[0]) for row in cur.fetchall()}
                    cur.execute("SET LOCAL enable_indexscan = on")
                    cur.execute("SET LOCAL enable_bitmapscan = on")
                    for value in values:
                        cur.execute(
                            "SELECT set_config('hnsw.ef_search', %s, true)",
                            (str(value),),
                        )
                        cur.execute(
                            f"""
                            SELECT chunk_id FROM {self.table_name}
                            ORDER BY embedding <=> %s LIMIT %s
                            """,
                            (query_embedding, top_k),
                        )
                        approximate = {str(row[0]) for row in cur.fetchall()}
                        denominator = max(1, len(exact))
                        recall_totals[value] += len(exact & approximate) / denominator
        sample_count = len(samples)
        recalls = {
            str(value): round(total / max(1, sample_count), 6)
            for value, total in recall_totals.items()
        }
        passing = [int(value) for value, recall in recalls.items() if recall >= 0.98]
        return {
            "sample_count": sample_count,
            "top_k": top_k,
            "recall_by_ef_search": recalls,
            "selected_ef_search": min(passing) if passing else None,
            "passed": bool(samples) and bool(passing),
        }

    def _ensure_table(self, *, create_hnsw: bool = True) -> None:
        with self._connection() as connection:
            with connection.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
                version_row = cur.fetchone()
                if version_row and self._version_tuple(str(version_row[0])) < (0, 8, 0):
                    raise RuntimeError("pgvector >= 0.8.0 is required for Retrieval v2")
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.table_name} (
                      chunk_id TEXT PRIMARY KEY,
                      document_id TEXT NOT NULL,
                      knowledge_base_id TEXT NOT NULL DEFAULT 'default',
                      modality TEXT NOT NULL DEFAULT 'text',
                      file_name TEXT NOT NULL,
                      chunk_index INTEGER NOT NULL,
                      page_number INTEGER,
                      heading_path JSONB,
                      metadata JSONB,
                      text TEXT NOT NULL,
                      embedding_text TEXT NOT NULL,
                      content_hash TEXT NOT NULL DEFAULT '',
                      token_count INTEGER NOT NULL DEFAULT 0,
                      embedding vector({self.dimension}) NOT NULL
                    )
                    """
                )
                cur.execute(
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS "
                    "knowledge_base_id TEXT NOT NULL DEFAULT 'default'"
                )
                cur.execute(
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS "
                    "modality TEXT NOT NULL DEFAULT 'text'"
                )
                cur.execute(
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS "
                    "embedding_text TEXT NOT NULL DEFAULT ''"
                )
                cur.execute(
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS "
                    "content_hash TEXT NOT NULL DEFAULT ''"
                )
                cur.execute(
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS "
                    "token_count INTEGER NOT NULL DEFAULT 0"
                )
                cur.execute(
                    f"UPDATE {self.table_name} SET embedding_text = text "
                    "WHERE embedding_text = ''"
                )
                cur.execute(
                    """
                    SELECT format_type(attribute.atttypid, attribute.atttypmod)
                    FROM pg_attribute attribute
                    WHERE attribute.attrelid = %s::regclass
                      AND attribute.attname = 'embedding'
                      AND NOT attribute.attisdropped
                    """,
                    (self.table_name,),
                )
                dimension_row = cur.fetchone()
                if dimension_row and str(dimension_row[0]) != f"vector({self.dimension})":
                    raise ValueError(
                        "Pgvector table dimension mismatch: "
                        f"stored {dimension_row[0]}, expected vector({self.dimension})"
                    )
                cur.execute(
                    f"CREATE INDEX IF NOT EXISTS {self._related_identifier('document_id_idx')} "
                    f"ON {self.table_name}(document_id)"
                )
                cur.execute(
                    f"CREATE INDEX IF NOT EXISTS {self._related_identifier('kb_modality_idx')} "
                    f"ON {self.table_name}(knowledge_base_id, modality)"
                )
                cur.execute(
                    f"CREATE INDEX IF NOT EXISTS {self._related_identifier('kb_document_idx')} "
                    f"ON {self.table_name}(knowledge_base_id, document_id)"
                )
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.postings_table_name} (
                      term TEXT NOT NULL,
                      chunk_id TEXT NOT NULL REFERENCES {self.table_name}(chunk_id)
                        ON DELETE CASCADE,
                      document_id TEXT NOT NULL,
                      knowledge_base_id TEXT NOT NULL,
                      modality TEXT NOT NULL,
                      term_frequency INTEGER NOT NULL,
                      chunk_length INTEGER NOT NULL,
                      PRIMARY KEY (term, chunk_id)
                    )
                    """
                )
                cur.execute(
                    f"CREATE INDEX IF NOT EXISTS {self._related_identifier('postings_chunk_idx')} "
                    f"ON {self.postings_table_name}(chunk_id)"
                )
                cur.execute(
                    f"CREATE INDEX IF NOT EXISTS {self._related_identifier('postings_kb_term_idx')} "
                    f"ON {self.postings_table_name}(knowledge_base_id, term)"
                )
            connection.commit()
        if create_hnsw:
            self.ensure_hnsw_index()

    def _load_existing(self) -> None:
        """Legacy explicit hydration hook; never called during construction."""

        self.chunks = {chunk.chunk_id: chunk for chunk in self.list_chunks()}

    def _filter_sql(
        self,
        *,
        document_ids: Optional[list[str]],
        knowledge_base_ids: Optional[list[str]],
        modalities: Optional[list[str]],
        alias: str = "",
    ) -> tuple[str, list[list[str]]]:
        clauses: list[str] = []
        params: list[list[str]] = []
        for column, values in (
            ("document_id", document_ids),
            ("knowledge_base_id", knowledge_base_ids),
            ("modality", modalities),
        ):
            selected = sorted(_normalized_filter(values))
            if selected:
                qualified = f"{alias}.{column}" if alias else column
                clauses.append(f"{qualified} = ANY(%s)")
                params.append(selected)
        return (f" WHERE {' AND '.join(clauses)}" if clauses else "", params)

    @contextmanager
    def _connection(self):
        """Use operation-scoped connections so a database restart is recoverable."""

        if hasattr(self, "_dsn"):
            connection = self.psycopg.connect(self._dsn)
            self._register_vector(connection)
            try:
                yield connection
            finally:
                connection.close()
            return

        # Test doubles constructed with ``__new__`` can still inject ``conn``.
        yield self.conn

    def _validate_identifier(self, identifier: str) -> str:
        if len(identifier) > 63 or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", identifier):
            raise ValueError("PGVECTOR_TABLE must be a simple SQL identifier")
        return identifier

    def _related_identifier(self, suffix: str) -> str:
        candidate = f"{self.table_name}_{suffix}"
        if len(candidate) <= 63:
            return self._validate_identifier(candidate)
        digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:10]
        return self._validate_identifier(f"{candidate[:52]}_{digest}")

    @staticmethod
    def _version_tuple(value: str) -> tuple[int, int, int]:
        parts = [int(item) for item in re.findall(r"\d+", value)[:3]]
        return tuple((parts + [0, 0, 0])[:3])  # type: ignore[return-value]

    @staticmethod
    def _chunk_from_row(row) -> Chunk:
        heading_path = row[5] if isinstance(row[5], list) else []
        metadata = row[6] if isinstance(row[6], dict) else {}
        element_ids = metadata.get("_chunk_element_ids")
        if not isinstance(element_ids, list):
            element_ids = metadata.get("element_ids")
        if not isinstance(element_ids, list):
            element_ids = []
        modality = str(
            metadata.get("_chunk_modality")
            or metadata.get("modality")
            or "text"
        )
        parent_element_id = (
            metadata.get("_chunk_parent_element_id")
            or (element_ids[0] if element_ids else None)
        )
        public_metadata = {
            key: value
            for key, value in metadata.items()
            if not str(key).startswith("_chunk_")
        }
        return Chunk(
            chunk_id=str(row[0]),
            document_id=str(row[1]),
            file_name=str(row[2]),
            chunk_index=int(row[3]),
            page_number=int(row[4]) if row[4] is not None else None,
            heading_path=[str(item) for item in heading_path],
            element_ids=[str(item) for item in element_ids],
            modality=modality,
            parent_element_id=(
                str(parent_element_id) if parent_element_id is not None else None
            ),
            metadata=public_metadata,
            text=str(row[7]),
        )


class VersionedPgVectorStore(BaseVectorStore):
    """Resolve the active registry pointer and pin it for a request context."""

    supports_persistent_sparse = True

    def __init__(
        self,
        dsn: str,
        index_registry,
        *,
        fallback_table: str = "rag_chunks_v2_initial",
        dimension: int = 1536,
    ):
        self.dsn = dsn
        self.index_registry = index_registry
        self.fallback_table = fallback_table
        self.dimension = dimension
        self.chunks: dict[str, Chunk] = {}
        self.embeddings: dict[str, list[float]] = {}
        self._cache: dict[str, PgVectorStore] = {}
        self._lock = RLock()
        self._pinned: ContextVar[PgVectorStore | None] = ContextVar(
            f"rag_active_index_{id(self)}", default=None
        )
        # Create only the physical staging table. It is intentionally not
        # registered or served until a rebuild has produced validation evidence.
        self._cache[fallback_table] = PgVectorStore(
            dsn,
            table_name=fallback_table,
            dimension=dimension,
            ensure_schema=True,
        )

    @contextmanager
    def pin_index(self):
        existing = self._pinned.get()
        if existing is not None:
            yield existing
            return
        store = self._resolve_store()
        token = self._pinned.set(store)
        try:
            yield store
        finally:
            self._pinned.reset(token)

    @property
    def table_name(self) -> str:
        return self._store().table_name

    @property
    def index_version(self) -> str:
        pinned = self._pinned.get()
        if pinned is not None:
            return pinned.index_version
        active = self.index_registry.active()
        return active.index_id if active else ""

    @property
    def last_sparse_search_stats(self) -> dict:
        return self._store().last_sparse_search_stats

    def add_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        self._store().add_chunks(chunks, embeddings)

    def search(self, query_embedding: list[float], top_k: int = 5, **kwargs) -> list[dict]:
        return self._store().search(query_embedding, top_k=top_k, **kwargs)

    def sparse_search(self, query_tokens: Iterable[str], *, top_k: int, **kwargs) -> list[dict]:
        return self._store().sparse_search(query_tokens, top_k=top_k, **kwargs)

    def list_chunks(self, **kwargs) -> list[Chunk]:
        return self._store().list_chunks(**kwargs)

    def count_chunks(self, **kwargs) -> int:
        return self._store().count_chunks(**kwargs)

    def has_document(self, document_id: str) -> bool:
        return self._store().has_document(document_id)

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        return self._store().get_chunk(chunk_id)

    def context_chunks(self, chunk_id: str, window: int = 1) -> list[Chunk]:
        return self._store().context_chunks(chunk_id, window)

    def document_index_signature(self, document_id: str) -> dict:
        return self._store().document_index_signature(document_id)

    def chunks_by_element_ids(self, element_ids: Iterable[str], **kwargs) -> list[Chunk]:
        return self._store().chunks_by_element_ids(element_ids, **kwargs)

    def delete_by_document_id(self, document_id: str) -> None:
        self._store().delete_by_document_id(document_id)

    def health(self) -> bool:
        active = self.index_registry.active()
        if active is None:
            return False
        is_ready = getattr(self.index_registry, "is_activation_ready", None)
        if callable(is_ready) and not is_ready(active.index_id):
            return False
        return self._store().health()

    def _store(self) -> PgVectorStore:
        return self._pinned.get() or self._resolve_store()

    def _resolve_store(self) -> PgVectorStore:
        active = self.index_registry.active()
        if active is None:
            raise RuntimeError(
                "No validated active index is registered; build and validate the initial snapshot first"
            )
        table_name = active.table_name
        with self._lock:
            if table_name not in self._cache:
                hnsw_metrics = (
                    active.metrics.get("hnsw", {})
                    if isinstance(active.metrics, dict)
                    else {}
                )
                selected_ef_search = int(
                    hnsw_metrics.get("selected_ef_search") or 80
                )
                store = PgVectorStore(
                    self.dsn,
                    table_name=table_name,
                    dimension=active.embedding_dimension,
                    default_ef_search=selected_ef_search,
                    ensure_schema=False,
                )
                store.index_version = active.index_id
                self._cache[table_name] = store
            return self._cache[table_name]
