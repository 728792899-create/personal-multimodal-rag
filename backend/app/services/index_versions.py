from __future__ import annotations

import json
import math
import re
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Literal, Optional

from app.services.vectorstore import versioned_pgvector_table_name


IndexStatus = Literal["candidate", "stable", "active", "rollback", "failed"]
REQUIRED_VALIDATIONS = (
    "document_count_matches",
    "chunk_count_matches",
    "content_hashes_match",
    "embedding_model_matches",
    "embedding_dimension_matches",
    "parser_version_matches",
    "chunker_version_matches",
    "no_empty_vectors",
    "no_non_finite_vectors",
    "no_duplicate_chunk_ids",
    "citations_resolvable",
    "hnsw_recall_passed",
    "cost_projection_within_15_percent",
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _validate_index_id(index_id: str) -> str:
    value = str(index_id).strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", value):
        raise ValueError("index_id must contain only letters, numbers, '.', '_' or '-'")
    return value


def _validate_table_name(table_name: str) -> str:
    value = str(table_name).strip()
    if not re.fullmatch(r"rag_chunks_v2_[A-Za-z0-9_]+", value):
        raise ValueError("index table must use a safe rag_chunks_v2_* identifier")
    if len(value) > 63:
        raise ValueError("index table name exceeds PostgreSQL's 63-byte identifier limit")
    return value


@dataclass(frozen=True)
class IndexVersion:
    index_id: str
    table_name: str
    status: IndexStatus
    embedding_provider: str
    embedding_model: str
    embedding_dimension: int
    parser_version: str
    chunker_version: str
    source_index_id: str
    validation: dict
    metrics: dict
    created_at: str
    updated_at: str
    activated_at: str

    def model_dump(self) -> dict:
        return asdict(self)


class IndexVersionRegistry:
    """Independent index control-plane registry for SQLite or PostgreSQL.

    The active index pointer and status changes share one transaction. This
    registry intentionally does not depend on ``DocumentRegistry`` so index
    cutovers cannot be coupled to document metadata migrations.
    """

    def __init__(self, dsn_or_path: str, *, workspace_id: str = "default"):
        if not dsn_or_path:
            raise ValueError("Index registry DSN or SQLite path is required")
        self.target = dsn_or_path
        self.workspace_id = workspace_id or "default"
        self.dialect = (
            "postgres"
            if dsn_or_path.startswith(("postgresql://", "postgres://"))
            else "sqlite"
        )
        self._lock = threading.RLock()
        self._sqlite: sqlite3.Connection | None = None
        if self.dialect == "sqlite":
            if dsn_or_path != ":memory:":
                path = Path(dsn_or_path)
                path.parent.mkdir(parents=True, exist_ok=True)
            self._sqlite = sqlite3.connect(
                dsn_or_path,
                timeout=15,
                check_same_thread=False,
            )
            self._sqlite.row_factory = sqlite3.Row
            self._sqlite.execute("PRAGMA busy_timeout = 15000")
            if dsn_or_path != ":memory:":
                self._sqlite.execute("PRAGMA journal_mode = WAL")
        self._ensure_schema()

    def register_candidate(
        self,
        *,
        index_id: str,
        table_name: str = "",
        embedding_provider: str = "openai",
        embedding_model: str = "text-embedding-3-large",
        embedding_dimension: int = 1536,
        parser_version: str,
        chunker_version: str = "structure-v2",
        source_index_id: str = "",
    ) -> IndexVersion:
        index_id = _validate_index_id(index_id)
        table_name = _validate_table_name(
            table_name or versioned_pgvector_table_name(index_id)
        )
        embedding_provider = str(embedding_provider).strip().lower()
        embedding_model = str(embedding_model).strip()
        if embedding_provider != "openai":
            raise ValueError("Retrieval v2 indexes must use the OpenAI embedding provider")
        if embedding_model != "text-embedding-3-large":
            raise ValueError(
                "Retrieval v2 indexes must use text-embedding-3-large"
            )
        if int(embedding_dimension) != 1536:
            raise ValueError("Retrieval v2 index dimensions must be 1536")
        now = _utcnow()
        with self._transaction() as connection:
            try:
                self._execute(
                    connection,
                    """
                    INSERT INTO rag_index_versions
                      (index_id, table_name, status, embedding_provider,
                       embedding_model, embedding_dimension, parser_version,
                       chunker_version, source_index_id, validation, metrics,
                       created_at, updated_at, activated_at)
                    VALUES (?, ?, 'candidate', ?, ?, ?, ?, ?, ?, '{}', '{}', ?, ?, '')
                    """,
                    (
                        index_id,
                        table_name,
                        embedding_provider,
                        embedding_model,
                        int(embedding_dimension),
                        parser_version,
                        chunker_version,
                        source_index_id,
                        now,
                        now,
                    ),
                )
            except Exception as exc:
                if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                    raise ValueError(f"Index version already exists: {index_id}") from exc
                raise
        return self.get(index_id)  # type: ignore[return-value]

    def get(self, index_id: str) -> IndexVersion | None:
        with self._connection() as connection:
            row = self._fetchone(
                self._execute(
                    connection,
                    "SELECT * FROM rag_index_versions WHERE index_id = ?",
                    (_validate_index_id(index_id),),
                )
            )
        return self._record(row) if row else None

    def list(self, *, limit: int = 100) -> list[IndexVersion]:
        with self._connection() as connection:
            rows = self._fetchall(
                self._execute(
                    connection,
                    """
                    SELECT * FROM rag_index_versions
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (max(1, min(int(limit), 500)),),
                )
            )
        return [self._record(row) for row in rows]

    def record_validation(
        self,
        index_id: str,
        checklist: dict[str, bool],
        *,
        metrics: Optional[dict] = None,
    ) -> IndexVersion:
        index_id = _validate_index_id(index_id)
        normalized = {str(key): bool(value) for key, value in checklist.items()}
        with self._transaction() as connection:
            index = self._locked_index(connection, index_id)
            if index.status not in {"candidate", "stable"}:
                raise ValueError("Only candidate or stable indexes can be validated")
            self._execute(
                connection,
                """
                UPDATE rag_index_versions
                SET validation = ?, metrics = ?, updated_at = ?
                WHERE index_id = ?
                """,
                (
                    json.dumps(normalized, ensure_ascii=False, sort_keys=True),
                    json.dumps(metrics or {}, ensure_ascii=False, sort_keys=True),
                    _utcnow(),
                    index.index_id,
                ),
            )
        return self._required(index.index_id)

    def record_metrics(self, index_id: str, metrics: dict, *, merge: bool = True) -> IndexVersion:
        index_id = _validate_index_id(index_id)
        with self._transaction() as connection:
            index = self._locked_index(connection, index_id)
            if index.status == "active":
                raise ValueError("Metrics for an active index are immutable")
            payload = {**index.metrics, **metrics} if merge else dict(metrics)
            self._execute(
                connection,
                "UPDATE rag_index_versions SET metrics = ?, updated_at = ? WHERE index_id = ?",
                (
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    _utcnow(),
                    index.index_id,
                ),
            )
        return self._required(index.index_id)

    def validation_errors(self, index_id: str) -> list[str]:
        validation = self._required(index_id).validation
        return [name for name in REQUIRED_VALIDATIONS if validation.get(name) is not True]

    def activation_errors(self, index_id: str) -> list[str]:
        """Return evidence-level reasons an index cannot be active or a rollback target."""

        return self._activation_errors(self._required(index_id))

    def is_activation_ready(self, index_id: str) -> bool:
        return not self.activation_errors(index_id)

    def promote(self, index_id: str) -> IndexVersion:
        index_id = _validate_index_id(index_id)
        with self._transaction() as connection:
            index = self._locked_index(connection, index_id)
            if index.status not in {"candidate", "stable"}:
                raise ValueError("Only candidate indexes can be promoted")
            errors = self._activation_errors(index)
            if errors:
                raise ValueError(f"Index is not activation-ready: {', '.join(errors)}")
            self._execute(
                connection,
                """
                UPDATE rag_index_versions
                SET status = 'stable', updated_at = ? WHERE index_id = ?
                """,
                (_utcnow(), index.index_id),
            )
        return self._required(index.index_id)

    def active(self) -> IndexVersion | None:
        with self._connection() as connection:
            state = self._fetchone(
                self._execute(
                    connection,
                    "SELECT active_index_id FROM rag_index_state WHERE workspace_id = ?",
                    (self.workspace_id,),
                )
            )
        active_id = str(state["active_index_id"] or "") if state else ""
        return self.get(active_id) if active_id else None

    def state(self) -> dict:
        with self._connection() as connection:
            row = self._fetchone(
                self._execute(
                    connection,
                    "SELECT * FROM rag_index_state WHERE workspace_id = ?",
                    (self.workspace_id,),
                )
            )
        return dict(row) if row else {}

    def activate(self, index_id: str) -> IndexVersion:
        index_id = _validate_index_id(index_id)
        now = _utcnow()
        with self._transaction(lock_state=True) as connection:
            state = self._state_row(connection)
            target = self._locked_index(connection, index_id)
            if target.status not in {"stable", "active"}:
                raise ValueError("Only a validated stable index can be activated")
            target_errors = self._activation_errors(target)
            if target_errors:
                raise ValueError(
                    "Activation target is not activation-ready: "
                    + ", ".join(target_errors)
                )
            current_id = str(state["active_index_id"] or "")
            if current_id == target.index_id:
                return target
            if not current_id:
                # Establish the first fully-built baseline. This is not a
                # cutover: there is deliberately no previous rollback target.
                # A later activation must preserve this snapshot as previous.
                if target.status != "stable":
                    raise ValueError("Initial active baseline must be a stable index")
            else:
                current = self._locked_index(connection, current_id)
                current_errors = self._activation_errors(current)
                if current_errors:
                    raise ValueError(
                        "Current rollback snapshot is not activation-ready: "
                        + ", ".join(current_errors)
                    )
                self._execute(
                    connection,
                    """
                    UPDATE rag_index_versions SET status = 'stable', updated_at = ?
                    WHERE index_id = ? AND status = 'active'
                    """,
                    (now, current_id),
                )
            self._execute(
                connection,
                """
                UPDATE rag_index_versions
                SET status = 'active', activated_at = ?, updated_at = ?
                WHERE index_id = ?
                """,
                (now, now, target.index_id),
            )
            self._execute(
                connection,
                """
                UPDATE rag_index_state
                SET active_index_id = ?, previous_index_id = ?,
                    generation = generation + 1, updated_at = ?
                WHERE workspace_id = ?
                """,
                (target.index_id, current_id, now, self.workspace_id),
            )
        return self._required(target.index_id)

    def rollback(self) -> IndexVersion:
        now = _utcnow()
        target_id = ""
        with self._transaction(lock_state=True) as connection:
            state = self._state_row(connection)
            current_id = str(state["active_index_id"] or "")
            target_id = str(state["previous_index_id"] or "")
            if not current_id or not target_id:
                raise ValueError("No previous stable index is available for rollback")
            target_record = self._locked_index(connection, target_id)
            if target_record.status not in {"stable", "rollback"}:
                raise ValueError("Rollback target is not a stable index")
            target_errors = self._activation_errors(target_record)
            if target_errors:
                raise ValueError(
                    "Rollback target is not activation-ready: "
                    + ", ".join(target_errors)
                )
            self._execute(
                connection,
                """
                UPDATE rag_index_versions SET status = 'rollback', updated_at = ?
                WHERE index_id = ?
                """,
                (now, current_id),
            )
            self._execute(
                connection,
                """
                UPDATE rag_index_versions
                SET status = 'active', activated_at = ?, updated_at = ?
                WHERE index_id = ?
                """,
                (now, now, target_id),
            )
            self._execute(
                connection,
                """
                UPDATE rag_index_state
                SET active_index_id = ?, previous_index_id = ?,
                    generation = generation + 1, updated_at = ?
                WHERE workspace_id = ?
                """,
                (target_id, current_id, now, self.workspace_id),
            )
        return self._required(target_id)

    def mark_failed(self, index_id: str, *, metrics: Optional[dict] = None) -> IndexVersion:
        index = self._required(index_id)
        if index.status == "active":
            raise ValueError("An active index cannot be marked failed")
        with self._transaction() as connection:
            self._execute(
                connection,
                """
                UPDATE rag_index_versions SET status = 'failed', metrics = ?, updated_at = ?
                WHERE index_id = ?
                """,
                (
                    json.dumps(metrics or index.metrics, ensure_ascii=False, sort_keys=True),
                    _utcnow(),
                    index.index_id,
                ),
            )
        return self._required(index.index_id)

    def close(self) -> None:
        if self._sqlite is not None:
            self._sqlite.close()
            self._sqlite = None

    def _required(self, index_id: str) -> IndexVersion:
        record = self.get(index_id)
        if record is None:
            raise ValueError(f"Index version does not exist: {index_id}")
        return record

    def _locked_index(self, connection, index_id: str) -> IndexVersion:
        row = self._fetchone(
            self._execute(
                connection,
                "SELECT * FROM rag_index_versions WHERE index_id = ?"
                + (" FOR UPDATE" if self.dialect == "postgres" else ""),
                (_validate_index_id(index_id),),
            )
        )
        if row is None:
            raise ValueError(f"Index version does not exist: {index_id}")
        return self._record(row)

    def _state_row(self, connection):
        row = self._fetchone(
            self._execute(
                connection,
                "SELECT * FROM rag_index_state WHERE workspace_id = ?"
                + (" FOR UPDATE" if self.dialect == "postgres" else ""),
                (self.workspace_id,),
            )
        )
        if row is None:
            raise RuntimeError("Index registry state row is missing")
        return row

    @contextmanager
    def _connection(self):
        if self.dialect == "postgres":
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise RuntimeError("Install psycopg[binary] for PostgreSQL index registry") from exc
            connection = psycopg.connect(self.target, row_factory=dict_row)
            try:
                yield connection
            finally:
                connection.close()
            return
        if self._sqlite is None:
            raise RuntimeError("Index registry is closed")
        with self._lock:
            yield self._sqlite

    @contextmanager
    def _transaction(self, *, lock_state: bool = False):
        del lock_state
        with self._connection() as connection:
            try:
                if self.dialect == "sqlite":
                    connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def _execute(self, connection, sql: str, params: tuple = ()):
        if self.dialect == "postgres":
            sql = sql.replace("?", "%s")
        return connection.execute(sql, params)

    @staticmethod
    def _fetchone(cursor):
        return cursor.fetchone()

    @staticmethod
    def _fetchall(cursor):
        return cursor.fetchall()

    @staticmethod
    def _record(row) -> IndexVersion:
        payload = dict(row)
        for field in ("validation", "metrics"):
            value = payload.get(field)
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    value = {}
            payload[field] = value if isinstance(value, dict) else {}
        payload["embedding_dimension"] = int(payload["embedding_dimension"])
        return IndexVersion(**payload)

    @staticmethod
    def _is_v1_cloud_snapshot(index: IndexVersion) -> bool:
        return (
            index.embedding_provider.strip().lower() == "openai"
            and index.embedding_model.strip() == "text-embedding-3-large"
            and index.embedding_dimension == 1536
        )

    @classmethod
    def _activation_errors(cls, index: IndexVersion) -> list[str]:
        errors = [
            f"validation.{name}"
            for name in REQUIRED_VALIDATIONS
            if index.validation.get(name) is not True
        ]
        if not cls._is_v1_cloud_snapshot(index):
            errors.append("embedding_configuration")

        metrics = index.metrics if isinstance(index.metrics, dict) else {}

        def positive_integer(name: str) -> int | None:
            value = metrics.get(name)
            if isinstance(value, bool):
                return None
            try:
                normalized = int(value)
            except (TypeError, ValueError):
                return None
            return normalized if normalized > 0 else None

        document_count = positive_integer("document_count")
        expected_document_count = positive_integer("expected_document_count")
        chunk_count = positive_integer("chunk_count")
        expected_chunk_count = positive_integer("expected_chunk_count")
        content_hash_count = positive_integer("content_hash_count")
        distinct_chunk_count = positive_integer("distinct_chunk_count")
        if document_count is None:
            errors.append("metrics.document_count")
        if expected_document_count is None or expected_document_count != document_count:
            errors.append("metrics.expected_document_count")
        if chunk_count is None:
            errors.append("metrics.chunk_count")
        if expected_chunk_count is None or expected_chunk_count != chunk_count:
            errors.append("metrics.expected_chunk_count")
        if content_hash_count is None:
            errors.append("metrics.content_hash_count")
        if distinct_chunk_count is None or distinct_chunk_count != chunk_count:
            errors.append("metrics.distinct_chunk_count")
        for name in ("empty_citation_text", "empty_embedding_text", "non_finite_vectors"):
            value = metrics.get(name)
            if isinstance(value, bool) or value != 0:
                errors.append(f"metrics.{name}")

        hnsw = metrics.get("hnsw")
        if not isinstance(hnsw, dict) or hnsw.get("passed") is not True:
            errors.append("metrics.hnsw.passed")
        else:
            recalls = hnsw.get("recall_by_ef_search")
            recalls = recalls if isinstance(recalls, dict) else {}
            try:
                if isinstance(hnsw.get("sample_count"), bool) or isinstance(
                    hnsw.get("selected_ef_search"), bool
                ):
                    raise ValueError
                sample_count = int(hnsw.get("sample_count"))
                selected_ef_search = int(hnsw.get("selected_ef_search"))
                recall = float(recalls.get(str(selected_ef_search)))
            except (TypeError, ValueError):
                sample_count = 0
                selected_ef_search = 0
                recall = 0.0
            if sample_count <= 0:
                errors.append("metrics.hnsw.sample_count")
            if selected_ef_search <= 0:
                errors.append("metrics.hnsw.selected_ef_search")
            if not math.isfinite(recall) or recall < 0.98:
                errors.append("metrics.hnsw.recall")

        cost_gate = metrics.get("cost_gate")
        if not isinstance(cost_gate, dict) or cost_gate.get("passed") is not True:
            errors.append("metrics.cost_gate.passed")
        else:
            try:
                if isinstance(cost_gate.get("projected_input_tokens"), bool) or isinstance(
                    cost_gate.get("actual_input_tokens"), bool
                ):
                    raise ValueError
                projected = int(cost_gate.get("projected_input_tokens"))
                actual = int(cost_gate.get("actual_input_tokens"))
                variance = float(cost_gate.get("variance"))
                threshold = float(cost_gate.get("threshold"))
            except (TypeError, ValueError):
                projected = actual = 0
                variance = threshold = 1.0
            if projected <= 0:
                errors.append("metrics.cost_gate.projected_input_tokens")
            if actual <= 0:
                errors.append("metrics.cost_gate.actual_input_tokens")
            if not math.isfinite(variance) or variance < 0 or variance > 0.15:
                errors.append("metrics.cost_gate.variance")
            if not math.isfinite(threshold) or threshold <= 0 or threshold > 0.15:
                errors.append("metrics.cost_gate.threshold")

        return list(dict.fromkeys(errors))

    def _ensure_schema(self) -> None:
        statements = (
            """
            CREATE TABLE IF NOT EXISTS rag_index_versions (
              index_id TEXT PRIMARY KEY,
              table_name TEXT NOT NULL UNIQUE,
              status TEXT NOT NULL CHECK (
                status IN ('candidate', 'stable', 'active', 'rollback', 'failed')
              ),
              embedding_provider TEXT NOT NULL,
              embedding_model TEXT NOT NULL,
              embedding_dimension INTEGER NOT NULL,
              parser_version TEXT NOT NULL,
              chunker_version TEXT NOT NULL,
              source_index_id TEXT NOT NULL DEFAULT '',
              validation TEXT NOT NULL DEFAULT '{}',
              metrics TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              activated_at TEXT NOT NULL DEFAULT ''
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS rag_index_state (
              workspace_id TEXT PRIMARY KEY,
              active_index_id TEXT NOT NULL DEFAULT '',
              previous_index_id TEXT NOT NULL DEFAULT '',
              generation INTEGER NOT NULL DEFAULT 0,
              updated_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_rag_index_versions_status ON rag_index_versions(status)",
        )
        with self._transaction() as connection:
            for statement in statements:
                self._execute(connection, statement)
            self._execute(
                connection,
                """
                INSERT INTO rag_index_state
                  (workspace_id, active_index_id, previous_index_id, generation, updated_at)
                VALUES (?, '', '', 0, ?)
                ON CONFLICT (workspace_id) DO NOTHING
                """,
                (self.workspace_id, _utcnow()),
            )
