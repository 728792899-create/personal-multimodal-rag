from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

from app.services.document_registry import DocumentRegistry


MIGRATION_TABLES = (
    "workspaces",
    "users",
    "memberships",
    "knowledge_bases",
    "documents",
    "history",
    "feedback",
    "operation_logs",
    "knowledge_cards",
    "eval_cases",
    "conversations",
    "conversation_messages",
    "index_jobs",
    "assets",
    "document_elements",
    "parser_runs",
    "enrichment_cache",
    "graph_nodes",
    "graph_edges",
    "entity_mentions",
    "sessions",
    "outbox_events",
    "dead_letter_jobs",
    "sources",
    "source_items",
    "sync_runs",
)

PRIMARY_KEYS = {
    "workspaces": ("workspace_id",),
    "users": ("user_id",),
    "memberships": ("workspace_id", "user_id"),
    "knowledge_bases": ("knowledge_base_id",),
    "documents": ("document_id",),
    "history": ("history_id",),
    "feedback": ("feedback_id",),
    "operation_logs": ("operation_id",),
    "knowledge_cards": ("card_id",),
    "eval_cases": ("case_id",),
    "conversations": ("conversation_id",),
    "conversation_messages": ("message_id",),
    "index_jobs": ("job_id",),
    "assets": ("asset_id",),
    "document_elements": ("element_id",),
    "parser_runs": ("run_id",),
    "enrichment_cache": ("cache_key",),
    "graph_nodes": ("node_id",),
    "graph_edges": ("edge_id",),
    "entity_mentions": ("mention_id",),
    "sessions": ("token_hash",),
    "outbox_events": ("event_id",),
    "dead_letter_jobs": ("dead_letter_id",),
    "sources": ("source_id",),
    "source_items": ("source_item_id",),
    "sync_runs": ("run_id",),
}


def _row_dict(row) -> dict:
    return {key: row[key] for key in row.keys()}


def _fingerprint(rows: list[dict]) -> str:
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def migrate_sqlite_to_postgres(
    sqlite_path: str,
    postgres_dsn: str,
    *,
    dry_run: bool = False,
) -> dict:
    source_path = Path(sqlite_path).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"SQLite registry not found: {source_path}")
    source = DocumentRegistry(str(source_path))
    snapshots: dict[str, list[dict]] = {}
    counts: dict[str, dict[str, int]] = {}
    backup_path = ""
    if not dry_run:
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        backup = source_path.with_suffix(source_path.suffix + f".pre-postgres-{timestamp}.bak")
        shutil.copy2(source_path, backup)
        backup_path = str(backup)

    for table in MIGRATION_TABLES:
        with source.transaction() as connection:
            rows = connection.execute(f"SELECT * FROM {table}").fetchall()
        snapshots[table] = [_row_dict(row) for row in rows]
        counts[table] = {"source": len(rows), "upserted": 0}

    verification: dict[str, dict[str, object]] = {}
    if not dry_run:
        destination = DocumentRegistry(postgres_dsn)
        # A single destination transaction guarantees that a failed copy or
        # verification never leaves a partially imported registry.
        with destination.transaction() as connection:
            for table in MIGRATION_TABLES:
                rows = snapshots[table]
                if not rows:
                    verification[table] = {
                        "verified": 0,
                        "source_sha256": _fingerprint([]),
                        "destination_sha256": _fingerprint([]),
                    }
                    continue
                columns = list(rows[0])
                primary_keys = PRIMARY_KEYS[table]
                mutable = [column for column in columns if column not in primary_keys]
                placeholders = ",".join("?" for _ in columns)
                conflict = ",".join(primary_keys)
                update = ", ".join(f"{column} = excluded.{column}" for column in mutable)
                query = (
                    f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders}) "
                    f"ON CONFLICT({conflict}) DO UPDATE SET {update}"
                )
                for row in rows:
                    connection.execute(query, tuple(row[column] for column in columns))
                    counts[table]["upserted"] += 1

                destination_rows: list[dict] = []
                for source_row in rows:
                    where = " AND ".join(f"{column} = ?" for column in primary_keys)
                    found = connection.execute(
                        f"SELECT {','.join(columns)} FROM {table} WHERE {where}",
                        tuple(source_row[column] for column in primary_keys),
                    ).fetchone()
                    if not found:
                        raise RuntimeError(f"Migration verification failed for table {table}")
                    destination_rows.append(_row_dict(found))
                source_hash = _fingerprint(rows)
                destination_hash = _fingerprint(destination_rows)
                if source_hash != destination_hash:
                    raise RuntimeError(f"Migration checksum failed for table {table}")
                verification[table] = {
                    "verified": len(destination_rows),
                    "source_sha256": source_hash,
                    "destination_sha256": destination_hash,
                }

    return {
        "dry_run": dry_run,
        "source": str(source_path),
        "destination": "postgresql://***",
        "counts": counts,
        "verification": verification,
        "backup": backup_path,
    }
