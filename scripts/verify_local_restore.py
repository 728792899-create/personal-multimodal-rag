#!/usr/bin/env python3
"""执行非破坏性的 SQLite 与对象存储恢复演练。

本命令不会写入源数据库。它通过备份 API 创建隔离的 SQLite 快照，只复制快照
引用的对象，并验证完整性、外键、schema 版本、安全对象路径、字节数和 SHA-256。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path


COUNTED_TABLES = (
    "knowledge_bases",
    "documents",
    "assets",
    "document_elements",
    "parser_runs",
    "conversations",
    "conversation_messages",
    "index_jobs",
    "graph_nodes",
    "graph_edges",
    "entity_mentions",
)


class RestoreDrillError(RuntimeError):
    """隔离恢复副本未通过一致性检查。"""


def run_restore_drill(
    database_path: str | Path,
    object_root: str | Path | None = None,
    *,
    expected_schema: int | None = None,
) -> dict:
    database = Path(database_path).expanduser().resolve()
    objects = Path(object_root).expanduser().resolve() if object_root else database.parent / "objects"
    if not database.is_file() or database.stat().st_size == 0:
        raise RestoreDrillError("数据库备份不存在或为空。")

    try:
        with tempfile.TemporaryDirectory(prefix="rag-restore-drill-") as temporary:
            restore_root = Path(temporary)
            restored_database = restore_root / "registry.sqlite3"
            restored_objects = restore_root / "objects"
            _snapshot_database(database, restored_database)
            inspection = _inspect_database(restored_database, expected_schema)
            copied = _restore_referenced_objects(
                inspection.pop("asset_rows"),
                source_root=objects,
                restored_root=restored_objects,
            )
            return {
                "status": "passed",
                **inspection,
                "database_bytes": restored_database.stat().st_size,
                "referenced_objects": copied,
                "copied_object_files": sum(1 for path in restored_objects.rglob("*") if path.is_file()),
            }
    except RestoreDrillError:
        raise
    except (OSError, sqlite3.DatabaseError) as exc:
        raise RestoreDrillError("恢复演练无法创建或验证隔离快照。") from exc


def _snapshot_database(source_path: Path, destination_path: Path) -> None:
    # WAL databases may require SQLite to create shared-memory bookkeeping even
    # when the logical workload is read-only. query_only forbids SQL writes
    # while retaining WAL-safe backup semantics across supported platforms.
    with closing(sqlite3.connect(str(source_path), timeout=15)) as source:
        source.execute("PRAGMA query_only = ON")
        with closing(sqlite3.connect(str(destination_path), timeout=15)) as destination:
            source.backup(destination)


def _inspect_database(database_path: Path, expected_schema: int | None) -> dict:
    with closing(sqlite3.connect(str(database_path))) as connection:
        connection.row_factory = sqlite3.Row
        integrity = [str(row[0]) for row in connection.execute("PRAGMA integrity_check").fetchall()]
        if integrity != ["ok"]:
            raise RestoreDrillError("恢复后的数据库未通过 integrity_check。")
        foreign_key_failures = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_failures:
            raise RestoreDrillError("恢复后的数据库存在外键约束错误。")

        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        if "schema_migrations" not in tables:
            raise RestoreDrillError("恢复后的数据库缺少 schema 迁移历史。")
        row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        schema_version = int(row[0] or 0)
        if expected_schema is not None and schema_version != expected_schema:
            raise RestoreDrillError("恢复后的数据库 schema 版本与目标版本不一致。")

        table_counts = {
            table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in COUNTED_TABLES
            if table in tables
        }
        asset_rows = []
        if "assets" in tables:
            asset_rows = [dict(row) for row in connection.execute(
                "SELECT object_key, sha256, size_bytes FROM assets ORDER BY object_key"
            ).fetchall()]
    return {
        "schema_version": schema_version,
        "integrity_check": "ok",
        "foreign_key_violations": 0,
        "table_counts": table_counts,
        "asset_rows": asset_rows,
    }


def _restore_referenced_objects(asset_rows: list[dict], *, source_root: Path, restored_root: Path) -> int:
    unique: dict[str, dict] = {}
    for row in asset_rows:
        key = str(row.get("object_key") or "")
        if key in unique:
            previous = unique[key]
            if previous.get("sha256") != row.get("sha256") or previous.get("size_bytes") != row.get("size_bytes"):
                raise RestoreDrillError("共享对象的元数据不一致。")
            continue
        unique[key] = row

    for key, row in unique.items():
        source = _safe_object_path(source_root, key)
        destination = _safe_object_path(restored_root, key)
        if not source.is_file():
            raise RestoreDrillError("备份中缺少数据库引用的对象。")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        size, digest = _file_digest(destination)
        if size != int(row.get("size_bytes") or 0):
            raise RestoreDrillError("恢复对象的字节数与数据库记录不一致。")
        expected_digest = str(row.get("sha256") or "")
        if not expected_digest or digest != expected_digest:
            raise RestoreDrillError("恢复对象的 SHA-256 与数据库记录不一致。")
    return len(unique)


def _safe_object_path(root: Path, object_key: str) -> Path:
    normalized = Path(object_key)
    if not object_key or normalized.is_absolute() or ".." in normalized.parts:
        raise RestoreDrillError("恢复后的数据库包含不安全的对象 key。")
    resolved_root = root.resolve()
    candidate = (resolved_root / normalized).resolve()
    if candidate == resolved_root or resolved_root not in candidate.parents:
        raise RestoreDrillError("恢复后的数据库包含不安全的对象 key。")
    return candidate


def _file_digest(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(block)
            digest.update(block)
    return size, digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, help="要验证的 SQLite registry 备份")
    parser.add_argument("--objects", help="与备份匹配的内容寻址对象目录")
    parser.add_argument("--expected-schema", type=int, help="要求精确匹配的 schema 版本")
    args = parser.parse_args()
    try:
        report = run_restore_drill(args.database, args.objects, expected_schema=args.expected_schema)
    except RestoreDrillError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
