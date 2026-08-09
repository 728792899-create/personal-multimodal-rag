from __future__ import annotations

import json
import re
import shutil
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

from app.models.domain import Document, DocumentElement
from app.services.safe_logging import redact_private_metadata, redact_sensitive_text


DEFAULT_KNOWLEDGE_BASE_ID = "default"
DEFAULT_KNOWLEDGE_BASE_NAME = "默认知识库"
DEFAULT_WORKSPACE_ID = "default"
DEFAULT_WORKSPACE_NAME = "个人工作区"


def _utcnow() -> str:
    return datetime.utcnow().isoformat(timespec="microseconds")


class _PostgresConnection:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, query: str, params: tuple = ()):
        normalized = query.replace("?", "%s")
        normalized = normalized.replace("BEGIN IMMEDIATE", "BEGIN")
        normalized = normalized.replace("MAX(progress, 5)", "GREATEST(progress, 5)")
        stripped = normalized.strip()
        if stripped.upper().startswith("INSERT OR IGNORE INTO"):
            normalized = re.sub(
                r"^\s*INSERT\s+OR\s+IGNORE\s+INTO",
                "INSERT INTO",
                normalized,
                count=1,
                flags=re.IGNORECASE,
            )
            normalized = normalized.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
        return self.connection.execute(normalized, params)

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)

    def commit(self) -> None:
        self.connection.commit()

    def rollback(self) -> None:
        self.connection.rollback()

    def close(self) -> None:
        self.connection.close()


class DocumentRegistry:
    """Durable local registry with idempotent SQLite migrations.

    File-backed registries open a connection per operation so API and worker
    threads never share a connection. In-memory registries use a private shared
    SQLite URI plus a keeper connection to preserve test compatibility.
    """

    CURRENT_SCHEMA_VERSION = 9

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.dialect = "postgres" if db_path.startswith(("postgresql://", "postgres://")) else "sqlite"
        self._lock = threading.RLock()
        self._keeper: sqlite3.Connection | None = None
        if self.dialect == "postgres":
            self._connect_target = db_path
            self._connect_uri = False
        elif db_path == ":memory:":
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

    def _new_connection(self):
        if self.dialect == "postgres":
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise RuntimeError(
                    "使用 PostgreSQL metadata registry 需要安装 psycopg[binary]。"
                ) from exc
            return _PostgresConnection(psycopg.connect(self._connect_target, row_factory=dict_row))
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

    def health(self) -> bool:
        with self._connection() as connection:
            row = connection.execute("SELECT 1 AS healthy").fetchone()
        return bool(row and int(row["healthy"]) == 1)

    # Identity and workspace -----------------------------------------------------

    def get_workspace(self, workspace_id: str = DEFAULT_WORKSPACE_ID) -> dict | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM workspaces WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["workspace_id"],
            "name": row["name"],
            "is_default": bool(row["is_default"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def bootstrap_admin(
        self,
        *,
        password_hash: str,
        username: str = "admin",
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> dict:
        """Migrate the legacy ADMIN_PASSWORD_HASH into the local admin account once.

        The configured hash is intentionally ignored after a database-backed
        password exists so restarting the service cannot undo an in-product
        password change.
        """

        now = _utcnow()
        normalized = username.strip().casefold()
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM users
                WHERE workspace_id = ? AND (username = ? OR user_id = 'owner')
                ORDER BY CASE WHEN username = ? THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (workspace_id, normalized, normalized),
            ).fetchone()
            if row is None:
                user_id = "owner"
                connection.execute(
                    """
                    INSERT INTO users
                      (user_id, workspace_id, role, username, password_hash,
                       display_name, is_active, must_change_password,
                       disabled_at, created_at, updated_at)
                    VALUES (?, ?, 'admin', ?, ?, 'Administrator', 1, 0, '', ?, ?)
                    """,
                    (user_id, workspace_id, normalized, password_hash, now, now),
                )
                needs_migration = True
            else:
                user_id = str(row["user_id"])
                needs_migration = not str(row["password_hash"] or "")
                if needs_migration:
                    connection.execute(
                        """
                        UPDATE users
                        SET username = ?, password_hash = ?, role = 'admin',
                            is_active = 1, must_change_password = 0,
                            disabled_at = '', updated_at = ?
                        WHERE user_id = ?
                        """,
                        (normalized, password_hash, now, user_id),
                    )
            if needs_migration:
                connection.execute(
                    """
                    INSERT INTO memberships (workspace_id, user_id, role, created_at, updated_at)
                    VALUES (?, ?, 'admin', ?, ?)
                    ON CONFLICT(workspace_id, user_id) DO UPDATE SET
                      role = excluded.role,
                      updated_at = excluded.updated_at
                    """,
                    (workspace_id, user_id, now, now),
                )
        member = self.get_member(user_id, workspace_id=workspace_id)
        if member is None:
            raise RuntimeError("管理员账号初始化失败。")
        return member

    def create_member(
        self,
        *,
        username: str,
        password_hash: str,
        display_name: str,
        role: str,
        must_change_password: bool = True,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
        user_id: str | None = None,
    ) -> dict:
        now = _utcnow()
        normalized = username.strip().casefold()
        resolved_user_id = user_id or str(uuid.uuid4())
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO users
                      (user_id, workspace_id, role, username, password_hash,
                       display_name, is_active, must_change_password,
                       disabled_at, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?, '', ?, ?)
                    """,
                    (
                        resolved_user_id,
                        workspace_id,
                        role,
                        normalized,
                        password_hash,
                        display_name.strip() or normalized,
                        1 if must_change_password else 0,
                        now,
                        now,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO memberships
                      (workspace_id, user_id, role, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (workspace_id, resolved_user_id, role, now, now),
                )
        except Exception as exc:
            if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                raise ValueError("用户名已存在。") from exc
            raise
        member = self.get_member(resolved_user_id, workspace_id=workspace_id)
        if member is None:
            raise RuntimeError("成员创建失败。")
        return member

    def get_user_by_username(
        self,
        username: str,
        *,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
        include_password: bool = False,
    ) -> dict | None:
        normalized = username.strip().casefold()
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT u.*, m.role AS membership_role
                FROM users u
                JOIN memberships m
                  ON m.user_id = u.user_id AND m.workspace_id = u.workspace_id
                WHERE u.workspace_id = ? AND u.username = ?
                LIMIT 1
                """,
                (workspace_id, normalized),
            ).fetchone()
        return self._member_from_row(row, include_password=include_password)

    def get_member(
        self,
        user_id: str,
        *,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
        include_password: bool = False,
    ) -> dict | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT u.*, m.role AS membership_role
                FROM users u
                JOIN memberships m
                  ON m.user_id = u.user_id AND m.workspace_id = u.workspace_id
                WHERE u.workspace_id = ? AND u.user_id = ?
                LIMIT 1
                """,
                (workspace_id, user_id),
            ).fetchone()
        return self._member_from_row(row, include_password=include_password)

    def list_members(self, workspace_id: str = DEFAULT_WORKSPACE_ID) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT u.*, m.role AS membership_role
                FROM users u
                JOIN memberships m
                  ON m.user_id = u.user_id AND m.workspace_id = u.workspace_id
                WHERE u.workspace_id = ?
                ORDER BY u.is_active DESC, u.username ASC
                """,
                (workspace_id,),
            ).fetchall()
        return [self._member_from_row(row) for row in rows]

    def update_member(
        self,
        user_id: str,
        *,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
        role: str | None = None,
        display_name: str | None = None,
        is_active: bool | None = None,
        password_hash: str | None = None,
        must_change_password: bool | None = None,
    ) -> dict | None:
        now = _utcnow()
        revoke_sessions = role is not None or is_active is not None or password_hash is not None
        with self._connection() as connection:
            # Serialize membership mutations across processes before checking
            # the last-admin invariant. The in-process lock alone is not
            # sufficient once multiple API replicas share PostgreSQL.
            connection.execute("BEGIN IMMEDIATE")
            if self.dialect == "postgres":
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(?))",
                    (f"membership-admin:{workspace_id}",),
                )
            row = connection.execute(
                """
                SELECT u.*, m.role AS membership_role
                FROM users u
                JOIN memberships m
                  ON m.user_id = u.user_id AND m.workspace_id = u.workspace_id
                WHERE u.workspace_id = ? AND u.user_id = ?
                """,
                (workspace_id, user_id),
            ).fetchone()
            if row is None:
                return None
            current_role = str(row["membership_role"])
            current_active = bool(row["is_active"])
            next_role = role if role is not None else current_role
            next_active = is_active if is_active is not None else current_active
            if current_role == "admin" and current_active and (
                next_role != "admin" or not next_active
            ):
                active_admins = connection.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM users u
                    JOIN memberships m
                      ON m.user_id = u.user_id AND m.workspace_id = u.workspace_id
                    WHERE u.workspace_id = ? AND u.is_active = 1 AND m.role = 'admin'
                    """,
                    (workspace_id,),
                ).fetchone()
                if int(active_admins["count"] or 0) <= 1:
                    raise ValueError("不能禁用或降级最后一个管理员。")

            assignments = ["updated_at = ?"]
            values: list[object] = [now]
            if role is not None:
                assignments.append("role = ?")
                values.append(role)
            if display_name is not None:
                assignments.append("display_name = ?")
                values.append(display_name.strip() or str(row["username"]))
            if is_active is not None:
                assignments.extend(["is_active = ?", "disabled_at = ?"])
                values.extend([1 if is_active else 0, "" if is_active else now])
            if password_hash is not None:
                assignments.append("password_hash = ?")
                values.append(password_hash)
            if must_change_password is not None:
                assignments.append("must_change_password = ?")
                values.append(1 if must_change_password else 0)
            values.append(user_id)
            connection.execute(
                f"UPDATE users SET {', '.join(assignments)} WHERE user_id = ?",
                tuple(values),
            )
            if role is not None:
                connection.execute(
                    """
                    UPDATE memberships SET role = ?, updated_at = ?
                    WHERE workspace_id = ? AND user_id = ?
                    """,
                    (role, now, workspace_id, user_id),
                )
            if revoke_sessions:
                connection.execute(
                    """
                    UPDATE sessions SET revoked_at = ?
                    WHERE workspace_id = ? AND user_id = ? AND revoked_at = ''
                    """,
                    (now, workspace_id, user_id),
                )
        return self.get_member(user_id, workspace_id=workspace_id)

    def revoke_user_sessions(
        self,
        user_id: str,
        *,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> int:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE sessions SET revoked_at = ?
                WHERE workspace_id = ? AND user_id = ? AND revoked_at = ''
                """,
                (_utcnow(), workspace_id, user_id),
            )
        return cursor.rowcount

    def resolve_session_identity(self, token_hash: str, *, touch: bool = True) -> dict | None:
        now = _utcnow()
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT s.*, u.username, u.display_name, u.is_active,
                       u.must_change_password, m.role AS membership_role
                FROM sessions s
                JOIN users u
                  ON u.user_id = s.user_id AND u.workspace_id = s.workspace_id
                JOIN memberships m
                  ON m.user_id = s.user_id AND m.workspace_id = s.workspace_id
                WHERE s.token_hash = ? AND s.revoked_at = '' AND s.expires_at > ?
                  AND u.is_active = 1
                LIMIT 1
                """,
                (token_hash, now),
            ).fetchone()
            if row and touch:
                connection.execute(
                    "UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?",
                    (now, token_hash),
                )
        if row is None:
            return None
        return {
            "token_hash": row["token_hash"],
            "csrf_token": row["csrf_token"],
            "user_id": row["user_id"],
            "username": row["username"],
            "display_name": row["display_name"],
            "workspace_id": row["workspace_id"],
            "role": row["membership_role"],
            "must_change_password": bool(row["must_change_password"]),
            "expires_at": row["expires_at"],
            "created_at": row["created_at"],
            "last_seen_at": now if touch else row["last_seen_at"],
        }

    @staticmethod
    def _member_from_row(row, *, include_password: bool = False) -> dict | None:
        if row is None:
            return None
        member = {
            "user_id": row["user_id"],
            "username": row["username"],
            "display_name": row["display_name"],
            "workspace_id": row["workspace_id"],
            "role": row["membership_role"],
            "is_active": bool(row["is_active"]),
            "must_change_password": bool(row["must_change_password"]),
            "disabled_at": row["disabled_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        if include_password:
            member["password_hash"] = row["password_hash"]
        return member

    def create_session(
        self,
        *,
        token_hash: str,
        csrf_token: str,
        user_id: str,
        workspace_id: str,
        expires_at: str,
    ) -> dict:
        created_at = _utcnow()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO sessions
                  (token_hash, csrf_token, user_id, workspace_id, expires_at,
                   created_at, last_seen_at, revoked_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, '')
                """,
                (
                    token_hash,
                    csrf_token,
                    user_id,
                    workspace_id,
                    expires_at,
                    created_at,
                    created_at,
                ),
            )
        return self.get_session(token_hash, touch=False) or {}

    def get_session(self, token_hash: str, *, touch: bool = True) -> dict | None:
        now = _utcnow()
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM sessions
                WHERE token_hash = ? AND revoked_at = '' AND expires_at > ?
                """,
                (token_hash, now),
            ).fetchone()
            if row and touch:
                connection.execute(
                    "UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?",
                    (now, token_hash),
                )
        if not row:
            return None
        return {
            "token_hash": row["token_hash"],
            "csrf_token": row["csrf_token"],
            "user_id": row["user_id"],
            "workspace_id": row["workspace_id"],
            "expires_at": row["expires_at"],
            "created_at": row["created_at"],
            "last_seen_at": now if touch else row["last_seen_at"],
        }

    def revoke_session(self, token_hash: str) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at = ''",
                (_utcnow(), token_hash),
            )
        return cursor.rowcount > 0

    def purge_expired_sessions(self) -> int:
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM sessions WHERE expires_at <= ? OR revoked_at != ''",
                (_utcnow(),),
            )
        return cursor.rowcount

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
                raise ValueError("文档不存在或已被删除。")
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
                raise ValueError("文档不存在或已被删除。")
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
            raise ValueError("请填写知识库名称。")
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
            raise ValueError("请填写知识库名称。")
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
            raise ValueError("默认知识库不能删除。")
        with self._connection() as connection:
            active_jobs = connection.execute(
                """
                SELECT COUNT(*) AS count FROM index_jobs
                WHERE knowledge_base_id = ? AND status IN ('queued', 'running', 'cancelling')
                """,
                (knowledge_base_id,),
            ).fetchone()
            if active_jobs and int(active_jobs["count"]):
                raise ValueError("知识库仍有运行中的索引任务；请先取消任务并等待结束。")
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM documents WHERE knowledge_base_id = ?",
                (knowledge_base_id,),
            ).fetchone()
            if row and int(row["count"]) and not force:
                raise ValueError("知识库仍包含文档；如需级联删除，请使用 force=true。")
            jobs = connection.execute(
                "SELECT COUNT(*) AS count FROM index_jobs WHERE knowledge_base_id = ?",
                (knowledge_base_id,),
            ).fetchone()
            if jobs and int(jobs["count"]) and not force:
                raise ValueError("知识库仍包含索引任务；如需级联删除，请使用 force=true。")
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
        *,
        user_id: str = "owner",
        workspace_id: str = DEFAULT_WORKSPACE_ID,
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
                  (conversation_id, workspace_id, user_id, title,
                   knowledge_base_ids, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    workspace_id,
                    user_id,
                    title.strip()[:160] or "新会话",
                    json.dumps(selected),
                    created_at,
                    created_at,
                ),
            )
        return self.get_conversation(
            conversation_id,
            user_id=user_id,
            workspace_id=workspace_id,
        ) or {}

    def get_conversation(
        self,
        conversation_id: str,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict | None:
        conditions = ["c.conversation_id = ?"]
        params: list[object] = [conversation_id]
        if user_id is not None:
            conditions.append("c.user_id = ?")
            params.append(user_id)
        if workspace_id is not None:
            conditions.append("c.workspace_id = ?")
            params.append(workspace_id)
        with self._connection() as connection:
            row = connection.execute(
                f"""
                SELECT c.*, COUNT(m.message_id) AS message_count
                FROM conversations c
                LEFT JOIN conversation_messages m ON m.conversation_id = c.conversation_id
                WHERE {' AND '.join(conditions)}
                GROUP BY c.conversation_id
                """,
                tuple(params),
            ).fetchone()
        return self._conversation_payload(row) if row else None

    def list_conversations(
        self,
        limit: int = 50,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> list[dict]:
        conditions: list[str] = []
        params: list[object] = []
        if user_id is not None:
            conditions.append("c.user_id = ?")
            params.append(user_id)
        if workspace_id is not None:
            conditions.append("c.workspace_id = ?")
            params.append(workspace_id)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(max(1, min(limit, 200)))
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT c.*, COUNT(m.message_id) AS message_count
                FROM conversations c
                LEFT JOIN conversation_messages m ON m.conversation_id = c.conversation_id
                {where}
                GROUP BY c.conversation_id
                ORDER BY c.updated_at DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [self._conversation_payload(row) for row in rows]

    def update_conversation(
        self,
        conversation_id: str,
        *,
        title: str | None = None,
        knowledge_base_ids: list[str] | None = None,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict | None:
        current = self.get_conversation(
            conversation_id,
            user_id=user_id,
            workspace_id=workspace_id,
        )
        if not current:
            return None
        next_title = current["title"] if title is None else (title.strip()[:160] or "新会话")
        next_ids = current["knowledge_base_ids"] if knowledge_base_ids is None else knowledge_base_ids
        if not next_ids:
            next_ids = [DEFAULT_KNOWLEDGE_BASE_ID]
        with self._connection() as connection:
            for knowledge_base_id in next_ids:
                self._assert_knowledge_base(connection, knowledge_base_id)
            conditions = ["conversation_id = ?"]
            params: list[object] = [
                next_title,
                json.dumps(next_ids),
                _utcnow(),
                conversation_id,
            ]
            if user_id is not None:
                conditions.append("user_id = ?")
                params.append(user_id)
            if workspace_id is not None:
                conditions.append("workspace_id = ?")
                params.append(workspace_id)
            cursor = connection.execute(
                f"""
                UPDATE conversations SET title = ?, knowledge_base_ids = ?, updated_at = ?
                WHERE {' AND '.join(conditions)}
                """,
                tuple(params),
            )
        if not cursor.rowcount:
            return None
        return self.get_conversation(
            conversation_id,
            user_id=user_id,
            workspace_id=workspace_id,
        )

    def delete_conversation(
        self,
        conversation_id: str,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> bool:
        conditions = ["conversation_id = ?"]
        params: list[object] = [conversation_id]
        if user_id is not None:
            conditions.append("user_id = ?")
            params.append(user_id)
        if workspace_id is not None:
            conditions.append("workspace_id = ?")
            params.append(workspace_id)
        with self._connection() as connection:
            cursor = connection.execute(
                f"DELETE FROM conversations WHERE {' AND '.join(conditions)}",
                tuple(params),
            )
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
            raise ValueError("不支持该会话消息角色。")
        if not self.get_conversation(conversation_id):
            raise ValueError("会话不存在或已被删除。")
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

    def list_conversation_messages(
        self,
        conversation_id: str,
        limit: int = 200,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> list[dict]:
        if (user_id is not None or workspace_id is not None) and not self.get_conversation(
            conversation_id,
            user_id=user_id,
            workspace_id=workspace_id,
        ):
            return []
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

    def conversation_retrieval_traces(self, limit: int = 200) -> list[dict]:
        """Return only persisted assistant retrieval traces for health rollups."""

        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT metadata FROM conversation_messages
                WHERE role = 'assistant' ORDER BY created_at DESC LIMIT ?
                """,
                (max(1, min(limit, 1000)),),
            ).fetchall()
        traces: list[dict] = []
        for row in rows:
            try:
                metadata = json.loads(row["metadata"])
            except (TypeError, json.JSONDecodeError):
                continue
            response = metadata.get("response") if isinstance(metadata, dict) else None
            trace = (
                response.get("retrieval_trace")
                if isinstance(response, dict)
                else None
            )
            if isinstance(trace, dict):
                traces.append(trace)
        return traces

    def real_usage_summary(self) -> dict:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT message_id, conversation_id, metadata, created_at
                FROM conversation_messages
                WHERE role = 'user'
                ORDER BY created_at ASC
                """
            ).fetchall()
        recorded: list[dict] = []
        for row in rows:
            try:
                metadata = json.loads(row["metadata"])
            except (TypeError, json.JSONDecodeError):
                continue
            evidence = (
                metadata.get("usage_evidence")
                if isinstance(metadata, dict)
                else None
            )
            if not isinstance(evidence, dict):
                continue
            if (
                evidence.get("attestation") != "human-originated"
                or not evidence.get("user_id")
                or not evidence.get("workspace_id")
            ):
                continue
            recorded.append(
                {
                    "message_id": row["message_id"],
                    "conversation_id": row["conversation_id"],
                    "recorded_at": evidence.get("recorded_at") or row["created_at"],
                }
            )
        count = len(recorded)
        return {
            "human_originated_questions": count,
            "target": 100,
            "remaining_for_1_0": max(0, 100 - count),
            "conversation_count": len(
                {item["conversation_id"] for item in recorded}
            ),
            "first_recorded_at": recorded[0]["recorded_at"] if recorded else "",
            "last_recorded_at": recorded[-1]["recorded_at"] if recorded else "",
            "attestation": "human-originated",
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
                if existing["status"] in {"failed", "cancelled"}:
                    previous_payload = json.loads(existing["payload"])
                    connection.execute(
                        """
                        UPDATE index_jobs
                        SET source_type = ?, source_name = ?, payload = ?,
                            knowledge_base_id = ?, status = 'queued', stage = 'receive',
                            progress = 0, attempts = 0, max_attempts = ?,
                            cancel_requested = 0, deduped = 0,
                            error_code = '', error_message = '', document_id = '',
                            worker_id = '', lease_expires_at = '', next_attempt_at = ?,
                            started_at = '', completed_at = '', updated_at = ?
                        WHERE job_id = ? AND status IN ('failed', 'cancelled')
                        """,
                        (
                            source_type,
                            source_name[:240],
                            json.dumps(payload, ensure_ascii=False),
                            knowledge_base_id,
                            max(1, min(max_attempts, 10)),
                            created_at,
                            created_at,
                            existing["job_id"],
                        ),
                    )
                    self._enqueue_outbox_event(
                        connection,
                        event_type="index_job.retry_requested",
                        aggregate_id=existing["job_id"],
                        payload={
                            "job_id": existing["job_id"],
                            "reason": "idempotent_source_refresh",
                        },
                    )
                    refreshed = connection.execute(
                        "SELECT * FROM index_jobs WHERE job_id = ?",
                        (existing["job_id"],),
                    ).fetchone()
                    result = self._job_payload(refreshed, include_payload=True)
                    previous_asset_id = str(previous_payload.get("asset_id") or "")
                    if previous_asset_id and previous_asset_id != str(payload.get("asset_id") or ""):
                        result["_superseded_asset_id"] = previous_asset_id
                    return result
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
            self._enqueue_outbox_event(
                connection,
                event_type="index_job.queued",
                aggregate_id=job_id,
                payload={"job_id": job_id},
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
            claim_query = """
                SELECT job_id FROM index_jobs
                WHERE status = 'queued' AND cancel_requested = 0 AND next_attempt_at <= ?
                ORDER BY created_at ASC LIMIT 1
            """
            if self.dialect == "postgres":
                claim_query += " FOR UPDATE SKIP LOCKED"
            row = connection.execute(claim_query, (now,)).fetchone()
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

    def renew_index_job_lease(
        self,
        job_id: str,
        worker_id: str,
        lease_seconds: int,
    ) -> bool:
        lease = (
            datetime.utcnow() + timedelta(seconds=max(1, lease_seconds))
        ).isoformat(timespec="microseconds")
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE index_jobs
                SET lease_expires_at = ?, updated_at = ?
                WHERE job_id = ? AND status = 'running' AND worker_id = ?
                """,
                (lease, _utcnow(), job_id, worker_id),
            )
        return cursor.rowcount > 0

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
        safe_error = redact_sensitive_text(error_message)
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE index_jobs SET status = ?, stage = ?, error_code = ?, error_message = ?,
                    worker_id = '', lease_expires_at = '', next_attempt_at = ?,
                    completed_at = ?, updated_at = ? WHERE job_id = ?
                """,
                (status, status, error_code[:80], safe_error[:500], next_attempt, completed_at, _utcnow(), job_id),
            )
            if status == "queued":
                self._enqueue_outbox_event(
                    connection,
                    event_type="index_job.retry_scheduled",
                    aggregate_id=job_id,
                    payload={"job_id": job_id, "available_at": next_attempt},
                    available_at=next_attempt,
                )
            elif status == "failed":
                connection.execute(
                    """
                    INSERT INTO dead_letter_jobs
                      (dead_letter_id, job_id, payload, error_code, error_message, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        job_id,
                        json.dumps(current.get("payload") or {}, ensure_ascii=False),
                        error_code[:80],
                        safe_error[:500],
                        _utcnow(),
                    ),
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
            if cursor.rowcount:
                self._enqueue_outbox_event(
                    connection,
                    event_type="index_job.retry_requested",
                    aggregate_id=job_id,
                    payload={"job_id": job_id},
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

    def list_pending_outbox_events(self, limit: int = 100) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM outbox_events
                WHERE status = 'pending' AND available_at <= ?
                ORDER BY created_at ASC LIMIT ?
                """,
                (_utcnow(), max(1, min(limit, 500))),
            ).fetchall()
        return [
            {
                "id": row["event_id"],
                "event_type": row["event_type"],
                "aggregate_id": row["aggregate_id"],
                "payload": json.loads(row["payload"]),
                "attempts": int(row["attempts"]),
                "available_at": row["available_at"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def mark_outbox_published(self, event_id: str) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE outbox_events
                SET status = 'published', published_at = ?, error_message = ''
                WHERE event_id = ?
                """,
                (_utcnow(), event_id),
            )

    def mark_outbox_failed(self, event_id: str, error_message: str) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE outbox_events
                SET attempts = attempts + 1, error_message = ?, available_at = ?
                WHERE event_id = ?
                """,
                (
                    error_message[:500],
                    (datetime.utcnow() + timedelta(seconds=5)).isoformat(timespec="microseconds"),
                    event_id,
                ),
            )

    def list_dead_letter_jobs(self, limit: int = 50) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM dead_letter_jobs ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [
            {
                "id": row["dead_letter_id"],
                "job_id": row["job_id"],
                "payload": json.loads(row["payload"]),
                "error_code": row["error_code"],
                "error_message": row["error_message"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    # Incremental sources -------------------------------------------------------

    def create_source(
        self,
        *,
        source_type: str,
        name: str,
        config: dict,
        knowledge_base_id: str = DEFAULT_KNOWLEDGE_BASE_ID,
        enabled: bool = True,
    ) -> dict:
        source_id = str(uuid.uuid4())
        now = _utcnow()
        with self._connection() as connection:
            self._assert_knowledge_base(connection, knowledge_base_id)
            connection.execute(
                """
                INSERT INTO sources
                  (source_id, workspace_id, knowledge_base_id, source_type, name,
                   config, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    DEFAULT_WORKSPACE_ID,
                    knowledge_base_id,
                    source_type[:40],
                    name.strip()[:160],
                    json.dumps(config, ensure_ascii=False),
                    int(enabled),
                    now,
                    now,
                ),
            )
        return self.get_source(source_id) or {}

    def get_source(self, source_id: str) -> dict | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT s.*,
                  (SELECT COUNT(*) FROM source_items i WHERE i.source_id = s.source_id) AS item_count,
                  (SELECT COUNT(*) FROM source_items i
                   WHERE i.source_id = s.source_id AND i.deletion_candidate = 1) AS deletion_candidate_count
                FROM sources s WHERE s.source_id = ?
                """,
                (source_id,),
            ).fetchone()
        return self._source_payload(row) if row else None

    def list_sources(self, knowledge_base_id: str = "") -> list[dict]:
        params: tuple = ()
        where = ""
        if knowledge_base_id:
            where = "WHERE s.knowledge_base_id = ?"
            params = (knowledge_base_id,)
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT s.*,
                  (SELECT COUNT(*) FROM source_items i WHERE i.source_id = s.source_id) AS item_count,
                  (SELECT COUNT(*) FROM source_items i
                   WHERE i.source_id = s.source_id AND i.deletion_candidate = 1) AS deletion_candidate_count
                FROM sources s
                {where}
                ORDER BY s.created_at ASC
                """,
                params,
            ).fetchall()
        return [self._source_payload(row) for row in rows]

    def update_source(
        self,
        source_id: str,
        *,
        name: str | None = None,
        config: dict | None = None,
        enabled: bool | None = None,
    ) -> dict | None:
        current = self.get_source(source_id)
        if not current:
            return None
        next_name = current["name"] if name is None else name.strip()[:160]
        next_config = current["config"] if config is None else config
        next_enabled = current["enabled"] if enabled is None else bool(enabled)
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE sources SET name = ?, config = ?, enabled = ?, updated_at = ?
                WHERE source_id = ?
                """,
                (
                    next_name,
                    json.dumps(next_config, ensure_ascii=False),
                    int(next_enabled),
                    _utcnow(),
                    source_id,
                ),
            )
        return self.get_source(source_id)

    def delete_source(self, source_id: str) -> bool:
        with self._connection() as connection:
            cursor = connection.execute("DELETE FROM sources WHERE source_id = ?", (source_id,))
        return cursor.rowcount > 0

    def get_source_item(self, source_item_id: str) -> dict | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM source_items WHERE source_item_id = ?",
                (source_item_id,),
            ).fetchone()
        return self._source_item_payload(row) if row else None

    def find_source_item(self, source_id: str, external_id: str) -> dict | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM source_items WHERE source_id = ? AND external_id = ?",
                (source_id, external_id),
            ).fetchone()
        return self._source_item_payload(row) if row else None

    def list_source_items(self, source_id: str) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM source_items
                WHERE source_id = ?
                ORDER BY deletion_candidate DESC, title ASC, external_id ASC
                """,
                (source_id,),
            ).fetchall()
        return [self._source_item_payload(row) for row in rows]

    def upsert_source_item(
        self,
        *,
        source_id: str,
        external_id: str,
        location: str,
        title: str,
        content_hash: str,
        etag: str = "",
        last_modified: str = "",
        metadata: dict | None = None,
        sync_run_id: str = "",
    ) -> dict:
        now = _utcnow()
        source_item_id = str(uuid.uuid4())
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO source_items
                  (source_item_id, source_id, external_id, location, title,
                   content_hash, etag, last_modified, status, missing_successes,
                   deletion_candidate, document_id, metadata, last_seen_sync_id,
                   first_seen_at, last_seen_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', 0, 0, '', ?, ?, ?, ?, ?)
                ON CONFLICT(source_id, external_id) DO UPDATE SET
                  location = excluded.location,
                  title = excluded.title,
                  content_hash = excluded.content_hash,
                  etag = excluded.etag,
                  last_modified = excluded.last_modified,
                  status = 'active',
                  missing_successes = 0,
                  deletion_candidate = 0,
                  metadata = excluded.metadata,
                  last_seen_sync_id = excluded.last_seen_sync_id,
                  last_seen_at = excluded.last_seen_at,
                  updated_at = excluded.updated_at
                """,
                (
                    source_item_id,
                    source_id,
                    external_id,
                    location[:2048],
                    title[:240],
                    content_hash,
                    etag[:500],
                    last_modified[:200],
                    json.dumps(metadata or {}, ensure_ascii=False),
                    sync_run_id,
                    now,
                    now,
                    now,
                ),
            )
        return self.find_source_item(source_id, external_id) or {}

    def mark_source_item_indexed(self, source_item_id: str, document_id: str) -> dict | None:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE source_items
                SET document_id = ?, status = 'active', updated_at = ?
                WHERE source_item_id = ?
                """,
                (document_id, _utcnow(), source_item_id),
            )
        return self.get_source_item(source_item_id) if cursor.rowcount else None

    def update_source_item_status(self, source_item_id: str, status: str) -> dict | None:
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE source_items SET status = ?, updated_at = ? WHERE source_item_id = ?",
                (status[:40], _utcnow(), source_item_id),
            )
        return self.get_source_item(source_item_id) if cursor.rowcount else None

    def mark_missing_source_items(
        self,
        source_id: str,
        seen_external_ids: set[str],
        *,
        threshold: int = 2,
    ) -> int:
        candidates = 0
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT source_item_id, external_id, missing_successes FROM source_items WHERE source_id = ?",
                (source_id,),
            ).fetchall()
            for row in rows:
                if row["external_id"] in seen_external_ids:
                    continue
                missing = int(row["missing_successes"]) + 1
                deletion_candidate = int(missing >= max(2, threshold))
                connection.execute(
                    """
                    UPDATE source_items
                    SET missing_successes = ?, deletion_candidate = ?,
                        status = ?, updated_at = ?
                    WHERE source_item_id = ?
                    """,
                    (
                        missing,
                        deletion_candidate,
                        "deletion_candidate" if deletion_candidate else "missing",
                        _utcnow(),
                        row["source_item_id"],
                    ),
                )
                candidates += deletion_candidate
        return candidates

    def delete_source_item(self, source_item_id: str) -> dict | None:
        item = self.get_source_item(source_item_id)
        if not item:
            return None
        with self._connection() as connection:
            connection.execute(
                "DELETE FROM source_items WHERE source_item_id = ?",
                (source_item_id,),
            )
        return item

    def source_item_document_reference_count(self, document_id: str) -> int:
        if not document_id:
            return 0
        with self._connection() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM source_items WHERE document_id = ?",
                (document_id,),
            ).fetchone()
        return int(row["count"] if row else 0)

    def start_sync_run(self, source_id: str) -> dict:
        run_id = str(uuid.uuid4())
        now = _utcnow()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO sync_runs
                  (run_id, source_id, status, discovered_count, unchanged_count,
                   updated_count, deletion_candidate_count, failed_count,
                   partial, empty_result, error_message, started_at, completed_at)
                VALUES (?, ?, 'running', 0, 0, 0, 0, 0, 0, 0, '', ?, '')
                """,
                (run_id, source_id, now),
            )
        return self.get_sync_run(run_id) or {}

    def complete_sync_run(
        self,
        run_id: str,
        *,
        status: str,
        discovered: int,
        unchanged: int,
        updated: int,
        deletion_candidates: int,
        failed: int,
        partial: bool,
        empty_result: bool,
        error_message: str = "",
    ) -> dict | None:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE sync_runs
                SET status = ?, discovered_count = ?, unchanged_count = ?,
                    updated_count = ?, deletion_candidate_count = ?,
                    failed_count = ?, partial = ?, empty_result = ?,
                    error_message = ?, completed_at = ?
                WHERE run_id = ?
                """,
                (
                    status,
                    discovered,
                    unchanged,
                    updated,
                    deletion_candidates,
                    failed,
                    int(partial),
                    int(empty_result),
                    redact_sensitive_text(error_message)[:500],
                    _utcnow(),
                    run_id,
                ),
            )
        return self.get_sync_run(run_id) if cursor.rowcount else None

    def get_sync_run(self, run_id: str) -> dict | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM sync_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return self._sync_run_payload(row) if row else None

    def list_sync_runs(self, limit: int = 50, source_id: str = "") -> list[dict]:
        with self._connection() as connection:
            if source_id:
                rows = connection.execute(
                    """
                    SELECT * FROM sync_runs WHERE source_id = ?
                    ORDER BY started_at DESC LIMIT ?
                    """,
                    (source_id, max(1, min(limit, 200))),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM sync_runs ORDER BY started_at DESC LIMIT ?",
                    (max(1, min(limit, 200)),),
                ).fetchall()
        return [self._sync_run_payload(row) for row in rows]

    def recover_interrupted_sync_runs(self) -> int:
        now = _utcnow()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE sync_runs
                SET status = 'failed', partial = 1,
                    error_message = '同步在完成前中断，可以安全重试。',
                    completed_at = ?
                WHERE status = 'running'
                """,
                (now,),
            )
        return cursor.rowcount

    # Existing quality/history APIs --------------------------------------------

    def save_history(
        self,
        question: str,
        response: dict,
        knowledge_base_id: str = DEFAULT_KNOWLEDGE_BASE_ID,
        *,
        user_id: str = "owner",
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> dict:
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
            "user_id": user_id,
            "workspace_id": workspace_id,
            "created_at": created_at,
        }
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO history
                  (history_id, workspace_id, user_id, knowledge_base_id,
                   question, answer, payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    history_id,
                    workspace_id,
                    user_id,
                    knowledge_base_id,
                    question,
                    payload["answer"],
                    json.dumps(payload, ensure_ascii=False),
                    created_at,
                ),
            )
        return payload

    def get_history(
        self,
        history_id: str,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict | None:
        if user_id is None:
            return self._json_row(
                "SELECT payload FROM history WHERE history_id = ?", (history_id,)
            )
        return self._json_row(
            """
            SELECT payload FROM history
            WHERE history_id = ? AND user_id = ? AND workspace_id = ?
            """,
            (history_id, user_id, workspace_id or DEFAULT_WORKSPACE_ID),
        )

    def list_history(
        self,
        limit: int = 30,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> list[dict]:
        if user_id is None:
            return self._json_rows(
                "SELECT payload FROM history ORDER BY created_at DESC LIMIT ?", (limit,)
            )
        return self._json_rows(
            """
            SELECT payload FROM history
            WHERE user_id = ? AND workspace_id = ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (user_id, workspace_id or DEFAULT_WORKSPACE_ID, limit),
        )

    def clear_history(self) -> None:
        with self._connection() as connection:
            connection.execute("DELETE FROM history")

    def save_feedback(
        self,
        payload: dict,
        *,
        user_id: str = "owner",
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> dict:
        stored = {
            "id": str(uuid.uuid4()),
            "created_at": _utcnow(),
            "user_id": user_id,
            "workspace_id": workspace_id,
            **payload,
        }
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO feedback
                  (feedback_id, workspace_id, user_id, history_id, rating,
                   failure_type, payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stored["id"],
                    workspace_id,
                    user_id,
                    stored.get("history_id") or "",
                    stored.get("rating") or "",
                    stored.get("failure_type") or "",
                    json.dumps(stored, ensure_ascii=False),
                    stored["created_at"],
                ),
            )
        return stored

    def list_feedback(
        self,
        limit: int = 50,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> list[dict]:
        if user_id is None:
            return self._json_rows(
                "SELECT payload FROM feedback ORDER BY created_at DESC LIMIT ?", (limit,)
            )
        return self._json_rows(
            """
            SELECT payload FROM feedback
            WHERE user_id = ? AND workspace_id = ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (user_id, workspace_id or DEFAULT_WORKSPACE_ID, limit),
        )

    def feedback_stats(
        self,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict:
        feedback = self.list_feedback(
            limit=10_000,
            user_id=user_id,
            workspace_id=workspace_id,
        )
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

    def get_knowledge_card(self, card_id: str) -> dict | None:
        return self._json_row(
            "SELECT payload FROM knowledge_cards WHERE card_id = ?",
            (card_id,),
        )

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

    def get_eval_case(self, case_id: str) -> dict | None:
        return self._json_row(
            "SELECT payload FROM eval_cases WHERE case_id = ?",
            (case_id,),
        )

    def update_eval_case(self, case_id: str, payload: dict) -> dict | None:
        current = self.get_eval_case(case_id)
        if not current:
            return None
        stored = {
            **current,
            **payload,
            "id": case_id,
            "updated_at": _utcnow(),
        }
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE eval_cases
                SET question = ?, payload = ?
                WHERE case_id = ?
                """,
                (
                    stored.get("question") or "",
                    json.dumps(stored, ensure_ascii=False),
                    case_id,
                ),
            )
        return stored if cursor.rowcount > 0 else None

    def eval_review_summary(self) -> dict:
        cases = self.list_eval_cases(limit=10_000)
        reviewed = [case for case in cases if case.get("status") == "reviewed"]
        human_reviewed = [
            case
            for case in reviewed
            if case.get("reviewer_attestation") == "human-reviewed"
            and case.get("reviewer_id")
        ]
        return {
            "total": len(cases),
            "draft": sum(1 for case in cases if case.get("status") == "draft"),
            "reviewed": len(reviewed),
            "human_reviewed": len(human_reviewed),
            "remaining_for_1_0": max(0, 200 - len(human_reviewed)),
        }

    # Schema and serialization helpers -----------------------------------------

    def _backup_before_migration(self, path: Path) -> None:
        if self.dialect != "sqlite":
            return
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
                CREATE TABLE IF NOT EXISTS workspaces (
                  workspace_id TEXT PRIMARY KEY,
                  name TEXT NOT NULL,
                  is_default INTEGER NOT NULL DEFAULT 0,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS users (
                  user_id TEXT PRIMARY KEY,
                  workspace_id TEXT NOT NULL,
                  role TEXT NOT NULL,
                  username TEXT NOT NULL DEFAULT '',
                  password_hash TEXT NOT NULL DEFAULT '',
                  display_name TEXT NOT NULL,
                  is_active INTEGER NOT NULL DEFAULT 1,
                  must_change_password INTEGER NOT NULL DEFAULT 1,
                  disabled_at TEXT NOT NULL DEFAULT '',
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL DEFAULT '',
                  FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id)
                );
                CREATE TABLE IF NOT EXISTS memberships (
                  workspace_id TEXT NOT NULL,
                  user_id TEXT NOT NULL,
                  role TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL DEFAULT '',
                  PRIMARY KEY (workspace_id, user_id),
                  FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
                  FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS sessions (
                  token_hash TEXT PRIMARY KEY,
                  csrf_token TEXT NOT NULL,
                  user_id TEXT NOT NULL,
                  workspace_id TEXT NOT NULL,
                  expires_at TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  last_seen_at TEXT NOT NULL,
                  revoked_at TEXT NOT NULL DEFAULT '',
                  FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS knowledge_bases (
                  knowledge_base_id TEXT PRIMARY KEY,
                  workspace_id TEXT NOT NULL DEFAULT 'default',
                  name TEXT NOT NULL,
                  description TEXT NOT NULL DEFAULT '',
                  is_default INTEGER NOT NULL DEFAULT 0,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS documents (
                  document_id TEXT PRIMARY KEY,
                  workspace_id TEXT NOT NULL DEFAULT 'default',
                  knowledge_base_id TEXT NOT NULL DEFAULT 'default',
                  content_hash TEXT NOT NULL DEFAULT '',
                  index_version TEXT NOT NULL DEFAULT 'hybrid-v1',
                  payload TEXT NOT NULL,
                  FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_bases(knowledge_base_id)
                );
                CREATE TABLE IF NOT EXISTS history (
                  history_id TEXT PRIMARY KEY,
                  workspace_id TEXT NOT NULL DEFAULT 'default',
                  user_id TEXT NOT NULL DEFAULT 'owner',
                  knowledge_base_id TEXT NOT NULL DEFAULT 'default',
                  question TEXT NOT NULL,
                  answer TEXT NOT NULL,
                  payload TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS feedback (
                  feedback_id TEXT PRIMARY KEY,
                  workspace_id TEXT NOT NULL DEFAULT 'default',
                  user_id TEXT NOT NULL DEFAULT 'owner',
                  history_id TEXT, rating TEXT NOT NULL,
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
                  workspace_id TEXT NOT NULL DEFAULT 'default',
                  user_id TEXT NOT NULL DEFAULT 'owner',
                  title TEXT NOT NULL,
                  knowledge_base_ids TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
                  FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
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
                  workspace_id TEXT NOT NULL DEFAULT 'default',
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
                CREATE TABLE IF NOT EXISTS outbox_events (
                  event_id TEXT PRIMARY KEY,
                  event_type TEXT NOT NULL,
                  aggregate_id TEXT NOT NULL,
                  payload TEXT NOT NULL,
                  status TEXT NOT NULL DEFAULT 'pending',
                  attempts INTEGER NOT NULL DEFAULT 0,
                  available_at TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  published_at TEXT NOT NULL DEFAULT '',
                  error_message TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS dead_letter_jobs (
                  dead_letter_id TEXT PRIMARY KEY,
                  job_id TEXT NOT NULL,
                  payload TEXT NOT NULL,
                  error_code TEXT NOT NULL,
                  error_message TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sources (
                  source_id TEXT PRIMARY KEY,
                  workspace_id TEXT NOT NULL DEFAULT 'default',
                  knowledge_base_id TEXT NOT NULL,
                  source_type TEXT NOT NULL,
                  name TEXT NOT NULL,
                  config TEXT NOT NULL,
                  enabled INTEGER NOT NULL DEFAULT 1,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_bases(knowledge_base_id)
                );
                CREATE TABLE IF NOT EXISTS source_items (
                  source_item_id TEXT PRIMARY KEY,
                  source_id TEXT NOT NULL,
                  external_id TEXT NOT NULL,
                  location TEXT NOT NULL,
                  title TEXT NOT NULL,
                  content_hash TEXT NOT NULL DEFAULT '',
                  etag TEXT NOT NULL DEFAULT '',
                  last_modified TEXT NOT NULL DEFAULT '',
                  status TEXT NOT NULL DEFAULT 'active',
                  missing_successes INTEGER NOT NULL DEFAULT 0,
                  deletion_candidate INTEGER NOT NULL DEFAULT 0,
                  document_id TEXT NOT NULL DEFAULT '',
                  metadata TEXT NOT NULL,
                  last_seen_sync_id TEXT NOT NULL DEFAULT '',
                  first_seen_at TEXT NOT NULL,
                  last_seen_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  UNIQUE (source_id, external_id),
                  FOREIGN KEY (source_id) REFERENCES sources(source_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS sync_runs (
                  run_id TEXT PRIMARY KEY,
                  source_id TEXT NOT NULL,
                  status TEXT NOT NULL,
                  discovered_count INTEGER NOT NULL DEFAULT 0,
                  unchanged_count INTEGER NOT NULL DEFAULT 0,
                  updated_count INTEGER NOT NULL DEFAULT 0,
                  deletion_candidate_count INTEGER NOT NULL DEFAULT 0,
                  failed_count INTEGER NOT NULL DEFAULT 0,
                  partial INTEGER NOT NULL DEFAULT 0,
                  empty_result INTEGER NOT NULL DEFAULT 0,
                  error_message TEXT NOT NULL DEFAULT '',
                  started_at TEXT NOT NULL,
                  completed_at TEXT NOT NULL DEFAULT '',
                  FOREIGN KEY (source_id) REFERENCES sources(source_id) ON DELETE CASCADE
                );
                """
            )
            self._add_column_if_missing(connection, "knowledge_bases", "workspace_id", "TEXT NOT NULL DEFAULT 'default'")
            self._add_column_if_missing(connection, "users", "username", "TEXT NOT NULL DEFAULT ''")
            self._add_column_if_missing(connection, "users", "password_hash", "TEXT NOT NULL DEFAULT ''")
            self._add_column_if_missing(connection, "users", "is_active", "INTEGER NOT NULL DEFAULT 1")
            self._add_column_if_missing(connection, "users", "must_change_password", "INTEGER NOT NULL DEFAULT 1")
            self._add_column_if_missing(connection, "users", "disabled_at", "TEXT NOT NULL DEFAULT ''")
            self._add_column_if_missing(connection, "users", "updated_at", "TEXT NOT NULL DEFAULT ''")
            self._add_column_if_missing(connection, "memberships", "updated_at", "TEXT NOT NULL DEFAULT ''")
            self._add_column_if_missing(connection, "conversations", "workspace_id", "TEXT NOT NULL DEFAULT 'default'")
            self._add_column_if_missing(connection, "conversations", "user_id", "TEXT NOT NULL DEFAULT 'owner'")
            self._add_column_if_missing(connection, "documents", "workspace_id", "TEXT NOT NULL DEFAULT 'default'")
            self._add_column_if_missing(connection, "index_jobs", "workspace_id", "TEXT NOT NULL DEFAULT 'default'")
            self._add_column_if_missing(connection, "documents", "knowledge_base_id", "TEXT NOT NULL DEFAULT 'default'")
            self._add_column_if_missing(connection, "documents", "content_hash", "TEXT NOT NULL DEFAULT ''")
            self._add_column_if_missing(connection, "documents", "index_version", "TEXT NOT NULL DEFAULT 'hybrid-v1'")
            self._add_column_if_missing(connection, "history", "knowledge_base_id", "TEXT NOT NULL DEFAULT 'default'")
            self._add_column_if_missing(connection, "history", "workspace_id", "TEXT NOT NULL DEFAULT 'default'")
            self._add_column_if_missing(connection, "history", "user_id", "TEXT NOT NULL DEFAULT 'owner'")
            self._add_column_if_missing(connection, "feedback", "workspace_id", "TEXT NOT NULL DEFAULT 'default'")
            self._add_column_if_missing(connection, "feedback", "user_id", "TEXT NOT NULL DEFAULT 'owner'")
            connection.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_documents_kb ON documents(knowledge_base_id);
                CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(content_hash, knowledge_base_id);
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON index_jobs(status, next_attempt_at);
                CREATE INDEX IF NOT EXISTS idx_messages_conversation ON conversation_messages(conversation_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_conversations_owner
                  ON conversations(workspace_id, user_id, updated_at);
                CREATE INDEX IF NOT EXISTS idx_history_owner
                  ON history(workspace_id, user_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_feedback_owner
                  ON feedback(workspace_id, user_id, created_at);
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
                CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at, revoked_at);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_unique
                  ON users(username) WHERE username != '';
                CREATE INDEX IF NOT EXISTS idx_memberships_role
                  ON memberships(workspace_id, role);
                CREATE INDEX IF NOT EXISTS idx_outbox_pending ON outbox_events(status, available_at);
                CREATE INDEX IF NOT EXISTS idx_dead_letter_jobs_job ON dead_letter_jobs(job_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_sources_kb ON sources(knowledge_base_id, enabled);
                CREATE INDEX IF NOT EXISTS idx_source_items_source ON source_items(source_id, status);
                CREATE INDEX IF NOT EXISTS idx_source_items_document ON source_items(document_id);
                CREATE INDEX IF NOT EXISTS idx_sync_runs_source ON sync_runs(source_id, started_at);
                """
            )
            now = _utcnow()
            connection.execute(
                """
                INSERT INTO workspaces
                  (workspace_id, name, is_default, created_at, updated_at)
                VALUES (?, ?, 1, ?, ?)
                ON CONFLICT(workspace_id) DO NOTHING
                """,
                (DEFAULT_WORKSPACE_ID, DEFAULT_WORKSPACE_NAME, now, now),
            )
            connection.execute(
                """
                INSERT INTO users
                  (user_id, workspace_id, role, username, password_hash,
                   display_name, is_active, must_change_password,
                   disabled_at, created_at, updated_at)
                VALUES ('owner', ?, 'admin', '', '', 'Owner', 1, 1, '', ?, ?)
                ON CONFLICT(user_id) DO NOTHING
                """,
                (DEFAULT_WORKSPACE_ID, now, now),
            )
            connection.execute(
                """
                INSERT INTO memberships
                  (workspace_id, user_id, role, created_at, updated_at)
                VALUES (?, 'owner', 'admin', ?, ?)
                ON CONFLICT(workspace_id, user_id) DO NOTHING
                """,
                (DEFAULT_WORKSPACE_ID, now, now),
            )
            connection.execute(
                """
                INSERT INTO knowledge_bases
                  (knowledge_base_id, workspace_id, name, description, is_default, created_at, updated_at)
                VALUES (?, ?, ?, '自动迁移的本地默认空间', 1, ?, ?)
                ON CONFLICT(knowledge_base_id) DO NOTHING
                """,
                (
                    DEFAULT_KNOWLEDGE_BASE_ID,
                    DEFAULT_WORKSPACE_ID,
                    DEFAULT_KNOWLEDGE_BASE_NAME,
                    now,
                    now,
                ),
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

    def _add_column_if_missing(self, connection, table: str, column: str, definition: str) -> None:
        if self.dialect == "postgres":
            connection.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}")
            return
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

    def _enqueue_outbox_event(
        self,
        connection,
        *,
        event_type: str,
        aggregate_id: str,
        payload: dict,
        available_at: str | None = None,
    ) -> str:
        event_id = str(uuid.uuid4())
        now = _utcnow()
        connection.execute(
            """
            INSERT INTO outbox_events
              (event_id, event_type, aggregate_id, payload, status, attempts,
               available_at, created_at, published_at, error_message)
            VALUES (?, ?, ?, ?, 'pending', 0, ?, ?, '', '')
            """,
            (
                event_id,
                event_type[:120],
                aggregate_id[:240],
                json.dumps(payload, ensure_ascii=False),
                available_at or now,
                now,
            ),
        )
        return event_id

    def _assert_knowledge_base(self, connection: sqlite3.Connection, knowledge_base_id: str) -> None:
        row = connection.execute(
            "SELECT 1 FROM knowledge_bases WHERE knowledge_base_id = ?",
            (knowledge_base_id,),
        ).fetchone()
        if not row:
            raise ValueError("知识库不存在或已被删除。")

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
            "workspace_id": row["workspace_id"],
            "user_id": row["user_id"],
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

    @staticmethod
    def _source_payload(row) -> dict:
        return {
            "id": row["source_id"],
            "knowledge_base_id": row["knowledge_base_id"],
            "type": row["source_type"],
            "name": row["name"],
            "config": redact_private_metadata(json.loads(row["config"])),
            "enabled": bool(row["enabled"]),
            "item_count": int(row["item_count"]),
            "deletion_candidate_count": int(row["deletion_candidate_count"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _source_item_payload(row) -> dict:
        return {
            "id": row["source_item_id"],
            "source_id": row["source_id"],
            "external_id": row["external_id"],
            "location": row["location"],
            "title": row["title"],
            "content_hash": row["content_hash"],
            "etag": row["etag"],
            "last_modified": row["last_modified"],
            "status": row["status"],
            "missing_successes": int(row["missing_successes"]),
            "deletion_candidate": bool(row["deletion_candidate"]),
            "document_id": row["document_id"],
            "metadata": redact_private_metadata(json.loads(row["metadata"])),
            "last_seen_sync_id": row["last_seen_sync_id"],
            "first_seen_at": row["first_seen_at"],
            "last_seen_at": row["last_seen_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _sync_run_payload(row) -> dict:
        return {
            "id": row["run_id"],
            "source_id": row["source_id"],
            "status": row["status"],
            "discovered": int(row["discovered_count"]),
            "unchanged": int(row["unchanged_count"]),
            "updated": int(row["updated_count"]),
            "deletion_candidates": int(row["deletion_candidate_count"]),
            "failed": int(row["failed_count"]),
            "partial": bool(row["partial"]),
            "empty_result": bool(row["empty_result"]),
            "error_message": row["error_message"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
        }
