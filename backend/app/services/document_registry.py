from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

from app.models.domain import Document, DocumentElement
from app.services.safe_logging import redact_private_metadata


DEFAULT_KNOWLEDGE_BASE_ID = "default"
DEFAULT_KNOWLEDGE_BASE_NAME = "默认知识库"


def _utcnow() -> str:
    return datetime.utcnow().isoformat(timespec="microseconds")


class DocumentRegistry:
    """Durable local registry with idempotent SQLite migrations.

    File-backed registries open a connection per operation so API and worker
    threads never share a connection. In-memory registries use a private shared
    SQLite URI plus a keeper connection to preserve test compatibility.
    """

    CURRENT_SCHEMA_VERSION = 5

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._keeper: sqlite3.Connection | None = None
        if db_path == ":memory:":
            self._connect_target = f"file:rag-{uuid.uuid4().hex}?mode=memory&cache=shared"
            self._connect_uri = True
            self._keeper = self._new_connection()
        else:
            path = Path(db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._connect_target = str(path)
            self._connect_uri = False
            self._backup_before_migration(path)
        self._ensure_schema()

    def _new_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._connect_target,
            uri=self._connect_uri,
            timeout=15,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")
        if self.db_path != ":memory:":
            connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        # SQLite is the single-instance fact store. Serializing short local
        # transactions avoids shared-memory table locks between the API and
        # background worker while retaining one connection per operation.
        with self._lock:
            connection = self._new_connection()
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Expose a short SQLite transaction to split domain repositories."""

        with self._connection() as connection:
            yield connection

    def close(self) -> None:
        if self._keeper is not None:
            self._keeper.close()
            self._keeper = None

    @property
    def schema_version(self) -> int:
        with self._connection() as connection:
            row = connection.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
        return int(row["version"] or 0)

    # Documents -----------------------------------------------------------------

    def save_document(self, document: Document) -> None:
        knowledge_base_id = str(document.metadata.get("knowledge_base_id") or DEFAULT_KNOWLEDGE_BASE_ID)
        document.metadata["knowledge_base_id"] = knowledge_base_id
        document.metadata.setdefault("chunker_version", "paragraph-v1")
        document.metadata.setdefault("index_version", "hybrid-v1")
        with self._connection() as connection:
            self._assert_knowledge_base(connection, knowledge_base_id)
            connection.execute(
                """
                INSERT INTO documents (document_id, knowledge_base_id, content_hash, index_version, payload)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                  knowledge_base_id = excluded.knowledge_base_id,
                  content_hash = excluded.content_hash,
                  index_version = excluded.index_version,
                  payload = excluded.payload
                """,
                (
                    document.document_id,
                    knowledge_base_id,
                    str(document.metadata.get("content_hash") or ""),
                    str(document.metadata.get("index_version") or "hybrid-v1"),
                    document.model_dump_json(),
                ),
            )
            self._replace_document_elements(connection, document)

    def load_documents(self, knowledge_base_ids: list[str] | None = None) -> list[Document]:
        with self._connection() as connection:
            if knowledge_base_ids:
                placeholders = ",".join("?" for _ in knowledge_base_ids)
                rows = connection.execute(
                    f"SELECT payload FROM documents WHERE knowledge_base_id IN ({placeholders}) ORDER BY document_id",
                    tuple(knowledge_base_ids),
                ).fetchall()
            else:
                rows = connection.execute("SELECT payload FROM documents ORDER BY document_id").fetchall()
        return [Document.model_validate_json(row["payload"]) for row in rows]

    def get_document(self, document_id: str) -> Document | None:
        with self._connection() as connection:
            row = connection.execute("SELECT payload FROM documents WHERE document_id = ?", (document_id,)).fetchone()
        return Document.model_validate_json(row["payload"]) if row else None

    def find_by_content_hash(self, content_hash: str, knowledge_base_id: str | None = None) -> Document | None:
        if not content_hash:
            return None
        with self._connection() as connection:
            if knowledge_base_id:
                row = connection.execute(
                    "SELECT payload FROM documents WHERE content_hash = ? AND knowledge_base_id = ? LIMIT 1",
                    (content_hash, knowledge_base_id),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT payload FROM documents WHERE content_hash = ? LIMIT 1",
                    (content_hash,),
                ).fetchone()
        return Document.model_validate_json(row["payload"]) if row else None

    def update_document_status(self, document_id: str, status: str, error: str = "") -> Document | None:
        document = self.get_document(document_id)
        if not document:
            return None
        document.metadata["index_status"] = status
        document.metadata["index_error"] = error
        self.save_document(document)
        return document

    def delete_document(self, document_id: str) -> None:
        with self._connection() as connection:
            connection.execute("DELETE FROM documents WHERE document_id = ?", (document_id,))

    # Multimodal elements and assets -------------------------------------------

    def list_document_elements(self, document_id: str) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM document_elements WHERE document_id = ? ORDER BY element_order",
                (document_id,),
            ).fetchall()
        return [self._element_payload(DocumentElement.model_validate_json(row["payload"])) for row in rows]

    def create_asset(
        self,
        *,
        knowledge_base_id: str,
        kind: str,
        object_key: str,
        original_name: str,
        media_type: str,
        sha256: str,
        size_bytes: int,
        document_id: str | None = None,
        metadata: dict | None = None,
        expires_at: str = "",
        asset_id: str | None = None,
    ) -> dict:
        stored_id = asset_id or str(uuid.uuid4())
        created_at = _utcnow()
        with self._connection() as connection:
            self._assert_knowledge_base(connection, knowledge_base_id)
            if document_id and not connection.execute(
                "SELECT 1 FROM documents WHERE document_id = ?", (document_id,)
            ).fetchone():
                raise ValueError("Document not found")
            connection.execute(
                """
                INSERT INTO assets
                  (asset_id, document_id, knowledge_base_id, kind, object_key,
                   original_name, media_type, sha256, size_bytes, metadata,
                   expires_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stored_id, document_id, knowledge_base_id, kind, object_key,
                    original_name[:240], media_type[:120], sha256, max(0, int(size_bytes)),
                    json.dumps(metadata or {}, ensure_ascii=False), expires_at, created_at,
                ),
            )
        return self.get_asset(stored_id) or {}

    def get_asset(self, asset_id: str, *, include_private: bool = False) -> dict | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM assets WHERE asset_id = ?", (asset_id,)).fetchone()
        return self._asset_payload(row, include_private=include_private) if row else None

    def list_assets(
        self,
        *,
        document_id: str | None = None,
        kind: str | None = None,
        include_private: bool = False,
    ) -> list[dict]:
        clauses: list[str] = []
        params: list[str] = []
        if document_id is not None:
            clauses.append("document_id = ?")
            params.append(document_id)
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connection() as connection:
            rows = connection.execute(f"SELECT * FROM assets{where} ORDER BY created_at", tuple(params)).fetchall()
        return [self._asset_payload(row, include_private=include_private) for row in rows]

    def link_asset(self, asset_id: str, document_id: str) -> dict | None:
        with self._connection() as connection:
            if not connection.execute("SELECT 1 FROM documents WHERE document_id = ?", (document_id,)).fetchone():
                raise ValueError("Document not found")
            cursor = connection.execute(
                "UPDATE assets SET document_id = ? WHERE asset_id = ?",
                (document_id, asset_id),
            )
        return self.get_asset(asset_id) if cursor.rowcount else None

    def delete_asset(self, asset_id: str) -> dict | None:
        asset = self.get_asset(asset_id, include_private=True)
        if not asset:
            return None
        with self._connection() as connection:
            connection.execute("DELETE FROM assets WHERE asset_id = ?", (asset_id,))
        return asset

    def asset_reference_count(self, object_key: str) -> int:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM assets WHERE object_key = ?",
                (object_key,),
            ).fetchone()
        return int(row["count"] if row else 0)

    def create_parser_run(
        self,
        *,
        document_id: str,
        provider: str,
        parser: str,
        status: str,
        payload: dict | None = None,
        job_id: str = "",
    ) -> dict:
        run_id = str(uuid.uuid4())
        created_at = _utcnow()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO parser_runs
                  (run_id, document_id, job_id, provider, parser, status, payload, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, document_id, job_id, provider, parser, status, json.dumps(payload or {}, ensure_ascii=False), created_at, created_at),
            )
        return self.list_parser_runs(document_id)[0]

    def list_parser_runs(self, document_id: str) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM parser_runs WHERE document_id = ? ORDER BY created_at DESC",
                (document_id,),
            ).fetchall()
        return [self._parser_run_payload(row) for row in rows]

    def get_enrichment_cache(self, cache_key: str) -> dict | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload FROM enrichment_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def set_enrichment_cache(
        self,
        cache_key: str,
        *,
        provider: str,
        model: str,
        prompt_version: str,
        payload: dict,
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO enrichment_cache
                  (cache_key, provider, model, prompt_version, payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                  provider = excluded.provider, model = excluded.model,
                  prompt_version = excluded.prompt_version, payload = excluded.payload,
                  created_at = excluded.created_at
                """,
                (cache_key, provider, model, prompt_version, json.dumps(payload, ensure_ascii=False), _utcnow()),
            )

    # Knowledge bases -----------------------------------------------------------

    def create_knowledge_base(self, name: str, description: str = "") -> dict:
        cleaned = " ".join(name.split()).strip()
        if not cleaned:
            raise ValueError("Knowledge base name is required")
        knowledge_base_id = str(uuid.uuid4())
        created_at = _utcnow()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO knowledge_bases
                  (knowledge_base_id, name, description, is_default, created_at, updated_at)
                VALUES (?, ?, ?, 0, ?, ?)
                """,
                (knowledge_base_id, cleaned[:120], description.strip()[:500], created_at, created_at),
            )
        return self.get_knowledge_base(knowledge_base_id) or {}

    def get_knowledge_base(self, knowledge_base_id: str) -> dict | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT kb.*, COUNT(d.document_id) AS document_count
                FROM knowledge_bases kb
                LEFT JOIN documents d ON d.knowledge_base_id = kb.knowledge_base_id
                WHERE kb.knowledge_base_id = ?
                GROUP BY kb.knowledge_base_id
                """,
                (knowledge_base_id,),
            ).fetchone()
        return self._knowledge_base_payload(row) if row else None

    def list_knowledge_bases(self) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT kb.*, COUNT(d.document_id) AS document_count
                FROM knowledge_bases kb
                LEFT JOIN documents d ON d.knowledge_base_id = kb.knowledge_base_id
                GROUP BY kb.knowledge_base_id
                ORDER BY kb.is_default DESC, kb.created_at ASC
                """
            ).fetchall()
        return [self._knowledge_base_payload(row) for row in rows]

    def update_knowledge_base(self, knowledge_base_id: str, name: str, description: str | None = None) -> dict | None:
        cleaned = " ".join(name.split()).strip()
        if not cleaned:
            raise ValueError("Knowledge base name is required")
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE knowledge_bases
                SET name = ?, description = COALESCE(?, description), updated_at = ?
                WHERE knowledge_base_id = ?
                """,
                (cleaned[:120], description.strip()[:500] if description is not None else None, _utcnow(), knowledge_base_id),
            )
        return self.get_knowledge_base(knowledge_base_id) if cursor.rowcount else None

    def delete_knowledge_base(self, knowledge_base_id: str, force: bool = False) -> bool:
        if knowledge_base_id == DEFAULT_KNOWLEDGE_BASE_ID:
            raise ValueError("The default knowledge base cannot be deleted")
        with self._connection() as connection:
            active_jobs = connection.execute(
                """
                SELECT COUNT(*) AS count FROM index_jobs
                WHERE knowledge_base_id = ? AND status IN ('queued', 'running', 'cancelling')
                """,
                (knowledge_base_id,),
            ).fetchone()
            if active_jobs and int(active_jobs["count"]):
                raise ValueError("Knowledge base has active index jobs; cancel them and wait before deletion")
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM documents WHERE knowledge_base_id = ?",
                (knowledge_base_id,),
            ).fetchone()
            if row and int(row["count"]) and not force:
                raise ValueError("Knowledge base contains documents; use force=true to delete it")
            jobs = connection.execute(
                "SELECT COUNT(*) AS count FROM index_jobs WHERE knowledge_base_id = ?",
                (knowledge_base_id,),
            ).fetchone()
            if jobs and int(jobs["count"]) and not force:
                raise ValueError("Knowledge base contains index jobs; use force=true to delete it")
            if force:
                connection.execute("DELETE FROM documents WHERE knowledge_base_id = ?", (knowledge_base_id,))
                connection.execute("DELETE FROM index_jobs WHERE knowledge_base_id = ?", (knowledge_base_id,))
            conversations = connection.execute(
                "SELECT conversation_id, knowledge_base_ids FROM conversations"
            ).fetchall()
            for conversation in conversations:
                current_ids = json.loads(conversation["knowledge_base_ids"])
                if knowledge_base_id not in current_ids:
                    continue
                selected = [item for item in current_ids if item != knowledge_base_id]
                if not selected:
                    selected = [DEFAULT_KNOWLEDGE_BASE_ID]
                connection.execute(
                    "UPDATE conversations SET knowledge_base_ids = ?, updated_at = ? WHERE conversation_id = ?",
                    (json.dumps(selected), _utcnow(), conversation["conversation_id"]),
                )
            cursor = connection.execute(
                "DELETE FROM knowledge_bases WHERE knowledge_base_id = ? AND is_default = 0",
                (knowledge_base_id,),
            )
        return cursor.rowcount > 0

    # Conversations -------------------------------------------------------------

    def create_conversation(
        self,
        title: str = "新会话",
        knowledge_base_ids: list[str] | None = None,
    ) -> dict:
        conversation_id = str(uuid.uuid4())
        created_at = _utcnow()
        selected = knowledge_base_ids or [DEFAULT_KNOWLEDGE_BASE_ID]
        with self._connection() as connection:
            for knowledge_base_id in selected:
                self._assert_knowledge_base(connection, knowledge_base_id)
            connection.execute(
                """
                INSERT INTO conversations
                  (conversation_id, title, knowledge_base_ids, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (conversation_id, title.strip()[:160] or "新会话", json.dumps(selected), created_at, created_at),
            )
        return self.get_conversation(conversation_id) or {}

    def get_conversation(self, conversation_id: str) -> dict | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT c.*, COUNT(m.message_id) AS message_count
                FROM conversations c
                LEFT JOIN conversation_messages m ON m.conversation_id = c.conversation_id
                WHERE c.conversation_id = ?
                GROUP BY c.conversation_id
                """,
                (conversation_id,),
            ).fetchone()
        return self._conversation_payload(row) if row else None

    def list_conversations(self, limit: int = 50) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT c.*, COUNT(m.message_id) AS message_count
                FROM conversations c
                LEFT JOIN conversation_messages m ON m.conversation_id = c.conversation_id
                GROUP BY c.conversation_id
                ORDER BY c.updated_at DESC
                LIMIT ?
                """,
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [self._conversation_payload(row) for row in rows]

    def update_conversation(
        self,
        conversation_id: str,
        *,
        title: str | None = None,
        knowledge_base_ids: list[str] | None = None,
    ) -> dict | None:
        current = self.get_conversation(conversation_id)
        if not current:
            return None
        next_title = current["title"] if title is None else (title.strip()[:160] or "新会话")
        next_ids = current["knowledge_base_ids"] if knowledge_base_ids is None else knowledge_base_ids
        if not next_ids:
            next_ids = [DEFAULT_KNOWLEDGE_BASE_ID]
        with self._connection() as connection:
            for knowledge_base_id in next_ids:
                self._assert_knowledge_base(connection, knowledge_base_id)
            connection.execute(
                """
                UPDATE conversations SET title = ?, knowledge_base_ids = ?, updated_at = ?
                WHERE conversation_id = ?
                """,
                (next_title, json.dumps(next_ids), _utcnow(), conversation_id),
            )
        return self.get_conversation(conversation_id)

    def delete_conversation(self, conversation_id: str) -> bool:
        with self._connection() as connection:
            cursor = connection.execute("DELETE FROM conversations WHERE conversation_id = ?", (conversation_id,))
        return cursor.rowcount > 0

    def save_conversation_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        status: str = "completed",
        metadata: dict | None = None,
        message_id: str | None = None,
    ) -> dict:
        if role not in {"user", "assistant", "system"}:
            raise ValueError("Unsupported conversation role")
        if not self.get_conversation(conversation_id):
            raise ValueError("Conversation not found")
        stored_id = message_id or str(uuid.uuid4())
        created_at = _utcnow()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO conversation_messages
                  (message_id, conversation_id, role, content, status, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(message_id) DO UPDATE SET
                  content = excluded.content, status = excluded.status,
                  metadata = excluded.metadata, updated_at = excluded.updated_at
                """,
                (stored_id, conversation_id, role, content, status, json.dumps(metadata or {}, ensure_ascii=False), created_at, created_at),
            )
            connection.execute("UPDATE conversations SET updated_at = ? WHERE conversation_id = ?", (created_at, conversation_id))
        return self.get_conversation_message(stored_id) or {}

    def get_conversation_message(self, message_id: str) -> dict | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM conversation_messages WHERE message_id = ?", (message_id,)).fetchone()
        return self._message_payload(row) if row else None

    def list_conversation_messages(self, conversation_id: str, limit: int = 200) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM conversation_messages WHERE conversation_id = ?
                ORDER BY created_at ASC LIMIT ?
                """,
                (conversation_id, max(1, min(limit, 1000))),
            ).fetchall()
        return [self._message_payload(row) for row in rows]

    def conversation_context(self, conversation_id: str, max_turns: int = 6, max_chars: int = 12_000) -> list[dict]:
        messages = self.list_conversation_messages(conversation_id, limit=max_turns * 4 + 20)
        selected = messages[-max_turns * 2 :]
        while selected and sum(len(item["content"]) for item in selected) > max_chars:
            selected.pop(0)
        return selected

    def conversation_metrics(self, limit: int = 200) -> dict:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT status, metadata FROM conversation_messages
                WHERE role = 'assistant' ORDER BY created_at DESC LIMIT ?
                """,
                (max(1, min(limit, 1000)),),
            ).fetchall()
        first_token_values: list[float] = []
        provider_errors = 0
        for row in rows:
            metadata = json.loads(row["metadata"])
            response = metadata.get("response") if isinstance(metadata.get("response"), dict) else {}
            performance = response.get("retrieval_trace", {}).get("performance", {}) if isinstance(response, dict) else {}
            if isinstance(performance.get("first_token_ms"), (int, float)):
                first_token_values.append(float(performance["first_token_ms"]))
            if row["status"] == "failed":
                provider_errors += 1
        return {
            "streamed_message_count": len(rows),
            "cancelled_count": sum(1 for row in rows if row["status"] == "cancelled"),
            "provider_error_count": provider_errors,
            "avg_first_token_ms": round(sum(first_token_values) / len(first_token_values), 2) if first_token_values else 0,
        }

    # Index jobs ----------------------------------------------------------------

    def create_index_job(
        self,
        *,
        source_type: str,
        source_name: str,
        payload: dict,
        knowledge_base_id: str = DEFAULT_KNOWLEDGE_BASE_ID,
        idempotency_key: str,
        max_attempts: int = 3,
    ) -> dict:
        created_at = _utcnow()
        with self._connection() as connection:
            self._assert_knowledge_base(connection, knowledge_base_id)
            existing = connection.execute(
                "SELECT * FROM index_jobs WHERE idempotency_key = ? ORDER BY created_at DESC LIMIT 1",
                (idempotency_key,),
            ).fetchone()
            if existing:
                return self._job_payload(existing, include_payload=True)
            job_id = str(uuid.uuid4())
            connection.execute(
                """
                INSERT INTO index_jobs (
                  job_id, source_type, source_name, payload, knowledge_base_id,
                  idempotency_key, status, stage, progress, attempts, max_attempts,
                  cancel_requested, next_attempt_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'queued', 'receive', 0, 0, ?, 0, ?, ?, ?)
                """,
                (
                    job_id, source_type, source_name[:240], json.dumps(payload, ensure_ascii=False),
                    knowledge_base_id, idempotency_key, max(1, min(max_attempts, 10)),
                    created_at, created_at, created_at,
                ),
            )
            row = connection.execute("SELECT * FROM index_jobs WHERE job_id = ?", (job_id,)).fetchone()
        return self._job_payload(row, include_payload=True)

    def get_index_job(self, job_id: str) -> dict | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM index_jobs WHERE job_id = ?", (job_id,)).fetchone()
        return self._job_payload(row) if row else None

    def list_index_jobs(self, limit: int = 50) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM index_jobs ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [self._job_payload(row) for row in rows]

    def claim_next_index_job(self, worker_id: str, lease_seconds: int = 60) -> dict | None:
        now = _utcnow()
        lease = (datetime.utcnow() + timedelta(seconds=max(0, lease_seconds))).isoformat(timespec="microseconds")
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT job_id FROM index_jobs
                WHERE status = 'queued' AND cancel_requested = 0 AND next_attempt_at <= ?
                ORDER BY created_at ASC LIMIT 1
                """,
                (now,),
            ).fetchone()
            if not row:
                return None
            cursor = connection.execute(
                """
                UPDATE index_jobs
                SET status = 'running', stage = 'validate', progress = MAX(progress, 5),
                    attempts = attempts + 1, worker_id = ?, lease_expires_at = ?,
                    started_at = COALESCE(started_at, ?), updated_at = ?
                WHERE job_id = ? AND status = 'queued'
                """,
                (worker_id, lease, now, now, row["job_id"]),
            )
            if not cursor.rowcount:
                return None
            claimed = connection.execute("SELECT * FROM index_jobs WHERE job_id = ?", (row["job_id"],)).fetchone()
        return self._job_payload(claimed, include_payload=True)

    def update_index_job(self, job_id: str, *, stage: str, progress: int) -> dict | None:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE index_jobs SET stage = ?, progress = ?, updated_at = ?
                WHERE job_id = ? AND status IN ('running', 'cancelling')
                """,
                (stage[:40], max(0, min(progress, 100)), _utcnow(), job_id),
            )
        return self.get_index_job(job_id) if cursor.rowcount else None

    def complete_index_job(self, job_id: str, document_id: str, *, deduped: bool = False) -> dict | None:
        completed_at = _utcnow()
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE index_jobs
                SET status = 'succeeded', stage = 'complete', progress = 100,
                    document_id = ?, deduped = ?, error_code = '', error_message = '',
                    worker_id = '', lease_expires_at = '', completed_at = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (document_id, int(deduped), completed_at, completed_at, job_id),
            )
        return self.get_index_job(job_id)

    def fail_index_job(self, job_id: str, error_code: str, error_message: str) -> dict | None:
        current = self.get_index_job(job_id)
        if not current:
            return None
        terminal = current["attempts"] >= current["max_attempts"] or current["cancel_requested"]
        status = "cancelled" if current["cancel_requested"] else ("failed" if terminal else "queued")
        delay = min(2 ** max(current["attempts"] - 1, 0), 30)
        next_attempt = (datetime.utcnow() + timedelta(seconds=delay)).isoformat(timespec="microseconds")
        completed_at = _utcnow() if status in {"failed", "cancelled"} else ""
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE index_jobs SET status = ?, stage = ?, error_code = ?, error_message = ?,
                    worker_id = '', lease_expires_at = '', next_attempt_at = ?,
                    completed_at = ?, updated_at = ? WHERE job_id = ?
                """,
                (status, status, error_code[:80], error_message[:500], next_attempt, completed_at, _utcnow(), job_id),
            )
        return self.get_index_job(job_id)

    def retry_index_job(self, job_id: str) -> dict | None:
        now = _utcnow()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE index_jobs SET status = 'queued', stage = 'receive', progress = 0,
                    attempts = 0, cancel_requested = 0, error_code = '', error_message = '',
                    worker_id = '', lease_expires_at = '', next_attempt_at = ?,
                    completed_at = '', updated_at = ?
                WHERE job_id = ? AND status IN ('failed', 'cancelled')
                """,
                (now, now, job_id),
            )
        return self.get_index_job(job_id) if cursor.rowcount else None

    def request_index_job_cancel(self, job_id: str) -> dict | None:
        current = self.get_index_job(job_id)
        if not current:
            return None
        if current["status"] in {"succeeded", "failed", "cancelled"}:
            return current
        next_status = "cancelling" if current["status"] == "running" else "cancelled"
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE index_jobs SET status = ?, stage = ?, cancel_requested = 1,
                    completed_at = CASE WHEN ? = 'cancelled' THEN ? ELSE completed_at END,
                    updated_at = ? WHERE job_id = ?
                """,
                (next_status, next_status, next_status, _utcnow(), _utcnow(), job_id),
            )
        return self.get_index_job(job_id)

    def complete_index_job_cancellation(self, job_id: str) -> dict | None:
        """Persist the terminal half of a cooperative worker cancellation."""

        completed_at = _utcnow()
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE index_jobs
                SET status = 'cancelled', stage = 'cancelled', cancel_requested = 1,
                    worker_id = '', lease_expires_at = '', completed_at = ?, updated_at = ?
                WHERE job_id = ? AND status IN ('queued', 'running', 'cancelling')
                """,
                (completed_at, completed_at, job_id),
            )
        return self.get_index_job(job_id)

    def recover_stale_index_jobs(self) -> int:
        now = _utcnow()
        with self._connection() as connection:
            cancelled = connection.execute(
                """
                UPDATE index_jobs
                SET status = 'cancelled', stage = 'cancelled', cancel_requested = 1,
                    worker_id = '', lease_expires_at = '', completed_at = ?, updated_at = ?
                WHERE status IN ('running', 'cancelling')
                  AND (status = 'cancelling' OR cancel_requested = 1)
                  AND lease_expires_at != '' AND lease_expires_at <= ?
                """,
                (now, now, now),
            )
            queued = connection.execute(
                """
                UPDATE index_jobs SET status = 'queued', stage = 'receive', worker_id = '',
                    lease_expires_at = '', next_attempt_at = ?, updated_at = ?
                WHERE status = 'running' AND cancel_requested = 0
                  AND lease_expires_at != '' AND lease_expires_at <= ?
                """,
                (now, now, now),
            )
        return cancelled.rowcount + queued.rowcount

    def make_index_job_available(self, job_id: str) -> None:
        with self._connection() as connection:
            connection.execute("UPDATE index_jobs SET next_attempt_at = ? WHERE job_id = ?", (_utcnow(), job_id))

    # Existing quality/history APIs --------------------------------------------

    def save_history(self, question: str, response: dict, knowledge_base_id: str = DEFAULT_KNOWLEDGE_BASE_ID) -> dict:
        history_id = str(uuid.uuid4())
        created_at = _utcnow()
        payload = {
            "id": history_id,
            "question": question,
            "answer": response.get("answer", ""),
            "citations": response.get("citations", []),
            "retrieval_trace": response.get("retrieval_trace", {}),
            "generation_trace": response.get("generation_trace", {}),
            "confidence": response.get("confidence"),
            "knowledge_base_id": knowledge_base_id,
            "created_at": created_at,
        }
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO history (history_id, knowledge_base_id, question, answer, payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (history_id, knowledge_base_id, question, payload["answer"], json.dumps(payload, ensure_ascii=False), created_at),
            )
        return payload

    def get_history(self, history_id: str) -> dict | None:
        return self._json_row("SELECT payload FROM history WHERE history_id = ?", (history_id,))

    def list_history(self, limit: int = 30) -> list[dict]:
        return self._json_rows("SELECT payload FROM history ORDER BY created_at DESC LIMIT ?", (limit,))

    def clear_history(self) -> None:
        with self._connection() as connection:
            connection.execute("DELETE FROM history")

    def save_feedback(self, payload: dict) -> dict:
        stored = {"id": str(uuid.uuid4()), "created_at": _utcnow(), **payload}
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO feedback (feedback_id, history_id, rating, failure_type, payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (stored["id"], stored.get("history_id") or "", stored.get("rating") or "", stored.get("failure_type") or "", json.dumps(stored, ensure_ascii=False), stored["created_at"]),
            )
        return stored

    def list_feedback(self, limit: int = 50) -> list[dict]:
        return self._json_rows("SELECT payload FROM feedback ORDER BY created_at DESC LIMIT ?", (limit,))

    def feedback_stats(self) -> dict:
        feedback = self._json_rows("SELECT payload FROM feedback ORDER BY created_at DESC")
        failure_types: dict[str, int] = {}
        for item in feedback:
            failure_type = item.get("failure_type") or "unclassified"
            failure_types[failure_type] = failure_types.get(failure_type, 0) + 1
        return {
            "total": len(feedback),
            "positive": sum(1 for item in feedback if item.get("rating") == "up"),
            "negative": sum(1 for item in feedback if item.get("rating") == "down"),
            "failure_types": failure_types,
            "recent": feedback[:8],
        }

    def log_operation(self, event_type: str, message: str, payload: dict | None = None, level: str = "info") -> dict:
        stored = {"id": str(uuid.uuid4()), "event_type": event_type, "level": level, "message": message, "payload": payload or {}, "created_at": _utcnow()}
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO operation_logs (operation_id, event_type, level, payload, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (stored["id"], event_type, level, json.dumps(stored, ensure_ascii=False), stored["created_at"]),
            )
        return stored

    def list_operations(self, limit: int = 40) -> list[dict]:
        return self._json_rows("SELECT payload FROM operation_logs ORDER BY created_at DESC LIMIT ?", (limit,))

    def save_knowledge_card(self, payload: dict) -> dict:
        stored = {"id": str(uuid.uuid4()), "created_at": _utcnow(), **payload}
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO knowledge_cards (card_id, title, payload, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (stored["id"], stored.get("title") or "", json.dumps(stored, ensure_ascii=False), stored["created_at"]),
            )
        return stored

    def list_knowledge_cards(self, limit: int = 50) -> list[dict]:
        return self._json_rows("SELECT payload FROM knowledge_cards ORDER BY created_at DESC LIMIT ?", (limit,))

    def delete_knowledge_card(self, card_id: str) -> bool:
        with self._connection() as connection:
            cursor = connection.execute("DELETE FROM knowledge_cards WHERE card_id = ?", (card_id,))
        return cursor.rowcount > 0

    def save_eval_case(self, payload: dict) -> dict:
        stored = {"id": str(uuid.uuid4()), "created_at": _utcnow(), "status": payload.get("status") or "draft", **payload}
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO eval_cases (case_id, question, payload, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (stored["id"], stored.get("question") or "", json.dumps(stored, ensure_ascii=False), stored["created_at"]),
            )
        return stored

    def list_eval_cases(self, limit: int = 100) -> list[dict]:
        return self._json_rows("SELECT payload FROM eval_cases ORDER BY created_at DESC LIMIT ?", (limit,))

    # Schema and serialization helpers -----------------------------------------

    def _backup_before_migration(self, path: Path) -> None:
        if not path.exists() or path.stat().st_size == 0:
            return
        try:
            connection = sqlite3.connect(str(path))
            has_migrations = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
            ).fetchone()
            version = 0
            if has_migrations:
                row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
                version = int(row[0] or 0)
            connection.close()
            if version >= self.CURRENT_SCHEMA_VERSION:
                return
            timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
            shutil.copy2(path, path.with_suffix(path.suffix + f".bak-{timestamp}"))
        except sqlite3.DatabaseError:
            return

    def _ensure_schema(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                  version INTEGER PRIMARY KEY,
                  applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_bases (
                  knowledge_base_id TEXT PRIMARY KEY,
                  name TEXT NOT NULL,
                  description TEXT NOT NULL DEFAULT '',
                  is_default INTEGER NOT NULL DEFAULT 0,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS documents (
                  document_id TEXT PRIMARY KEY,
                  knowledge_base_id TEXT NOT NULL DEFAULT 'default',
                  content_hash TEXT NOT NULL DEFAULT '',
                  index_version TEXT NOT NULL DEFAULT 'hybrid-v1',
                  payload TEXT NOT NULL,
                  FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_bases(knowledge_base_id)
                );
                CREATE TABLE IF NOT EXISTS history (
                  history_id TEXT PRIMARY KEY,
                  knowledge_base_id TEXT NOT NULL DEFAULT 'default',
                  question TEXT NOT NULL,
                  answer TEXT NOT NULL,
                  payload TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS feedback (
                  feedback_id TEXT PRIMARY KEY, history_id TEXT, rating TEXT NOT NULL,
                  failure_type TEXT, payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operation_logs (
                  operation_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, level TEXT NOT NULL,
                  payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_cards (
                  card_id TEXT PRIMARY KEY, title TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS eval_cases (
                  case_id TEXT PRIMARY KEY, question TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS conversations (
                  conversation_id TEXT PRIMARY KEY,
                  title TEXT NOT NULL,
                  knowledge_base_ids TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS conversation_messages (
                  message_id TEXT PRIMARY KEY,
                  conversation_id TEXT NOT NULL,
                  role TEXT NOT NULL,
                  content TEXT NOT NULL,
                  status TEXT NOT NULL,
                  metadata TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS index_jobs (
                  job_id TEXT PRIMARY KEY,
                  source_type TEXT NOT NULL,
                  source_name TEXT NOT NULL,
                  payload TEXT NOT NULL,
                  knowledge_base_id TEXT NOT NULL,
                  idempotency_key TEXT NOT NULL UNIQUE,
                  status TEXT NOT NULL,
                  stage TEXT NOT NULL,
                  progress INTEGER NOT NULL,
                  attempts INTEGER NOT NULL,
                  max_attempts INTEGER NOT NULL,
                  cancel_requested INTEGER NOT NULL DEFAULT 0,
                  deduped INTEGER NOT NULL DEFAULT 0,
                  error_code TEXT NOT NULL DEFAULT '',
                  error_message TEXT NOT NULL DEFAULT '',
                  document_id TEXT NOT NULL DEFAULT '',
                  worker_id TEXT NOT NULL DEFAULT '',
                  lease_expires_at TEXT NOT NULL DEFAULT '',
                  next_attempt_at TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  started_at TEXT NOT NULL DEFAULT '',
                  completed_at TEXT NOT NULL DEFAULT '',
                  FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_bases(knowledge_base_id)
                );
                CREATE TABLE IF NOT EXISTS assets (
                  asset_id TEXT PRIMARY KEY,
                  document_id TEXT,
                  knowledge_base_id TEXT NOT NULL,
                  kind TEXT NOT NULL,
                  object_key TEXT NOT NULL,
                  original_name TEXT NOT NULL,
                  media_type TEXT NOT NULL,
                  sha256 TEXT NOT NULL,
                  size_bytes INTEGER NOT NULL,
                  metadata TEXT NOT NULL,
                  expires_at TEXT NOT NULL DEFAULT '',
                  created_at TEXT NOT NULL,
                  FOREIGN KEY (document_id) REFERENCES documents(document_id) ON DELETE CASCADE,
                  FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_bases(knowledge_base_id)
                );
                CREATE TABLE IF NOT EXISTS document_elements (
                  element_id TEXT PRIMARY KEY,
                  document_id TEXT NOT NULL,
                  knowledge_base_id TEXT NOT NULL,
                  element_type TEXT NOT NULL,
                  page_number INTEGER,
                  element_order INTEGER NOT NULL,
                  payload TEXT NOT NULL,
                  FOREIGN KEY (document_id) REFERENCES documents(document_id) ON DELETE CASCADE,
                  FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_bases(knowledge_base_id)
                );
                CREATE TABLE IF NOT EXISTS parser_runs (
                  run_id TEXT PRIMARY KEY,
                  document_id TEXT NOT NULL,
                  job_id TEXT NOT NULL DEFAULT '',
                  provider TEXT NOT NULL,
                  parser TEXT NOT NULL,
                  status TEXT NOT NULL,
                  payload TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  FOREIGN KEY (document_id) REFERENCES documents(document_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS enrichment_cache (
                  cache_key TEXT PRIMARY KEY,
                  provider TEXT NOT NULL,
                  model TEXT NOT NULL,
                  prompt_version TEXT NOT NULL,
                  payload TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS graph_nodes (
                  node_id TEXT PRIMARY KEY,
                  knowledge_base_id TEXT NOT NULL,
                  document_id TEXT,
                  element_id TEXT,
                  node_type TEXT NOT NULL,
                  label TEXT NOT NULL,
                  normalized_label TEXT NOT NULL,
                  payload TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_bases(knowledge_base_id) ON DELETE CASCADE,
                  FOREIGN KEY (document_id) REFERENCES documents(document_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS graph_edges (
                  edge_id TEXT PRIMARY KEY,
                  knowledge_base_id TEXT NOT NULL,
                  document_id TEXT NOT NULL,
                  source_node_id TEXT NOT NULL,
                  target_node_id TEXT NOT NULL,
                  relation TEXT NOT NULL,
                  evidence_element_ids TEXT NOT NULL,
                  evidence_span TEXT NOT NULL,
                  confidence REAL NOT NULL,
                  extraction_version TEXT NOT NULL,
                  payload TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_bases(knowledge_base_id) ON DELETE CASCADE,
                  FOREIGN KEY (document_id) REFERENCES documents(document_id) ON DELETE CASCADE,
                  FOREIGN KEY (source_node_id) REFERENCES graph_nodes(node_id) ON DELETE CASCADE,
                  FOREIGN KEY (target_node_id) REFERENCES graph_nodes(node_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS entity_mentions (
                  mention_id TEXT PRIMARY KEY,
                  knowledge_base_id TEXT NOT NULL,
                  document_id TEXT NOT NULL,
                  element_id TEXT NOT NULL,
                  entity_node_id TEXT NOT NULL,
                  evidence_span TEXT NOT NULL,
                  start_offset INTEGER NOT NULL,
                  end_offset INTEGER NOT NULL,
                  confidence REAL NOT NULL,
                  extraction_version TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_bases(knowledge_base_id) ON DELETE CASCADE,
                  FOREIGN KEY (document_id) REFERENCES documents(document_id) ON DELETE CASCADE,
                  FOREIGN KEY (entity_node_id) REFERENCES graph_nodes(node_id) ON DELETE CASCADE
                );
                """
            )
            self._add_column_if_missing(connection, "documents", "knowledge_base_id", "TEXT NOT NULL DEFAULT 'default'")
            self._add_column_if_missing(connection, "documents", "content_hash", "TEXT NOT NULL DEFAULT ''")
            self._add_column_if_missing(connection, "documents", "index_version", "TEXT NOT NULL DEFAULT 'hybrid-v1'")
            self._add_column_if_missing(connection, "history", "knowledge_base_id", "TEXT NOT NULL DEFAULT 'default'")
            connection.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_documents_kb ON documents(knowledge_base_id);
                CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(content_hash, knowledge_base_id);
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON index_jobs(status, next_attempt_at);
                CREATE INDEX IF NOT EXISTS idx_messages_conversation ON conversation_messages(conversation_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_assets_document ON assets(document_id, kind);
                CREATE INDEX IF NOT EXISTS idx_assets_expiry ON assets(expires_at);
                CREATE INDEX IF NOT EXISTS idx_elements_document ON document_elements(document_id, element_order);
                CREATE INDEX IF NOT EXISTS idx_elements_kb_type ON document_elements(knowledge_base_id, element_type);
                CREATE INDEX IF NOT EXISTS idx_parser_runs_document ON parser_runs(document_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_graph_nodes_kb_label ON graph_nodes(knowledge_base_id, normalized_label);
                CREATE INDEX IF NOT EXISTS idx_graph_nodes_document ON graph_nodes(document_id, node_type);
                CREATE INDEX IF NOT EXISTS idx_graph_edges_nodes ON graph_edges(source_node_id, target_node_id);
                CREATE INDEX IF NOT EXISTS idx_graph_edges_document ON graph_edges(document_id, relation);
                CREATE INDEX IF NOT EXISTS idx_entity_mentions_element ON entity_mentions(document_id, element_id);
                """
            )
            now = _utcnow()
            connection.execute(
                """
                INSERT INTO knowledge_bases
                  (knowledge_base_id, name, description, is_default, created_at, updated_at)
                VALUES (?, ?, '自动迁移的本地默认空间', 1, ?, ?)
                ON CONFLICT(knowledge_base_id) DO NOTHING
                """,
                (DEFAULT_KNOWLEDGE_BASE_ID, DEFAULT_KNOWLEDGE_BASE_NAME, now, now),
            )
            rows = connection.execute("SELECT document_id, payload FROM documents").fetchall()
            for row in rows:
                document = Document.model_validate_json(row["payload"])
                document.metadata.setdefault("knowledge_base_id", DEFAULT_KNOWLEDGE_BASE_ID)
                document.metadata.setdefault("chunker_version", "paragraph-v1")
                document.metadata.setdefault("index_version", "hybrid-v1")
                document.metadata.setdefault("source_available", False)
                connection.execute(
                    """
                    UPDATE documents SET knowledge_base_id = ?, content_hash = ?, index_version = ?, payload = ?
                    WHERE document_id = ?
                    """,
                    (
                        document.metadata["knowledge_base_id"],
                        str(document.metadata.get("content_hash") or ""),
                        str(document.metadata.get("index_version") or "hybrid-v1"),
                        document.model_dump_json(),
                        document.document_id,
                    ),
                )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (self.CURRENT_SCHEMA_VERSION, now),
            )

    def _add_column_if_missing(self, connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _replace_document_elements(self, connection: sqlite3.Connection, document: Document) -> None:
        connection.execute("DELETE FROM document_elements WHERE document_id = ?", (document.document_id,))
        knowledge_base_id = str(document.metadata.get("knowledge_base_id") or DEFAULT_KNOWLEDGE_BASE_ID)
        for element in document.elements:
            connection.execute(
                """
                INSERT INTO document_elements
                  (element_id, document_id, knowledge_base_id, element_type, page_number, element_order, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    element.element_id,
                    document.document_id,
                    knowledge_base_id,
                    element.type,
                    element.page_number,
                    element.order,
                    element.model_dump_json(),
                ),
            )

    def _assert_knowledge_base(self, connection: sqlite3.Connection, knowledge_base_id: str) -> None:
        row = connection.execute(
            "SELECT 1 FROM knowledge_bases WHERE knowledge_base_id = ?",
            (knowledge_base_id,),
        ).fetchone()
        if not row:
            raise ValueError("Knowledge base not found")

    def _json_row(self, query: str, params: tuple = ()) -> dict | None:
        with self._connection() as connection:
            row = connection.execute(query, params).fetchone()
        return json.loads(row["payload"]) if row else None

    def _json_rows(self, query: str, params: tuple = ()) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def _knowledge_base_payload(self, row: sqlite3.Row) -> dict:
        return {
            "id": row["knowledge_base_id"],
            "name": row["name"],
            "description": row["description"],
            "is_default": bool(row["is_default"]),
            "document_count": int(row["document_count"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _conversation_payload(self, row: sqlite3.Row) -> dict:
        return {
            "id": row["conversation_id"],
            "title": row["title"],
            "knowledge_base_ids": json.loads(row["knowledge_base_ids"]),
            "message_count": int(row["message_count"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _message_payload(self, row: sqlite3.Row) -> dict:
        return {
            "id": row["message_id"],
            "conversation_id": row["conversation_id"],
            "role": row["role"],
            "content": row["content"],
            "status": row["status"],
            "metadata": json.loads(row["metadata"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _job_payload(self, row: sqlite3.Row, *, include_payload: bool = False) -> dict:
        result = {
            "id": row["job_id"],
            "source_type": row["source_type"],
            "source_name": row["source_name"],
            "knowledge_base_id": row["knowledge_base_id"],
            "status": row["status"],
            "stage": row["stage"],
            "progress": int(row["progress"]),
            "attempts": int(row["attempts"]),
            "max_attempts": int(row["max_attempts"]),
            "cancel_requested": bool(row["cancel_requested"]),
            "deduped": bool(row["deduped"]),
            "error_code": row["error_code"],
            "error_message": row["error_message"],
            "document_id": row["document_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
        }
        if include_payload:
            result["payload"] = json.loads(row["payload"])
        return result

    @staticmethod
    def _element_payload(element: DocumentElement) -> dict:
        return {
            "id": element.element_id,
            "document_id": element.document_id,
            "type": element.type,
            "order": element.order,
            "text": element.text,
            "page_number": element.page_number,
            "bbox": element.bbox,
            "heading_path": element.heading_path,
            "asset_id": element.asset_id,
            "caption": element.caption,
            "footnotes": element.footnotes,
            "table": element.table,
            "latex": element.latex,
            "confidence": element.confidence,
            "metadata": redact_private_metadata(element.metadata),
        }

    @staticmethod
    def _asset_payload(row: sqlite3.Row, *, include_private: bool = False) -> dict:
        payload = {
            "id": row["asset_id"],
            "document_id": row["document_id"],
            "knowledge_base_id": row["knowledge_base_id"],
            "kind": row["kind"],
            "original_name": row["original_name"],
            "media_type": row["media_type"],
            "sha256": row["sha256"],
            "size_bytes": int(row["size_bytes"]),
            "metadata": json.loads(row["metadata"]),
            "expires_at": row["expires_at"],
            "created_at": row["created_at"],
        }
        if include_private:
            payload["object_key"] = row["object_key"]
        return payload

    @staticmethod
    def _parser_run_payload(row: sqlite3.Row) -> dict:
        return {
            "id": row["run_id"],
            "document_id": row["document_id"],
            "job_id": row["job_id"],
            "provider": row["provider"],
            "parser": row["parser"],
            "status": row["status"],
            "payload": json.loads(row["payload"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
