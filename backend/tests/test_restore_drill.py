from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.services.document_registry import DocumentRegistry
from app.services.object_store import LocalObjectStore
from scripts.verify_local_restore import RestoreDrillError, run_restore_drill


def _registry_with_asset(tmp_path: Path, *, object_key: str | None = None):
    database = tmp_path / "registry.sqlite3"
    objects = tmp_path / "objects"
    registry = DocumentRegistry(str(database))
    store = LocalObjectStore(objects)
    stored = store.put_bytes(b"durable restore fixture")
    asset = registry.create_asset(
        knowledge_base_id="default",
        kind="source",
        object_key=object_key or stored.object_key,
        original_name="restore.md",
        media_type="text/markdown",
        sha256=stored.sha256,
        size_bytes=stored.size_bytes,
    )
    registry.close()
    return database, objects, stored, asset


def test_restore_drill_uses_isolated_snapshot_and_verifies_objects(tmp_path: Path):
    database, objects, stored, _asset = _registry_with_asset(tmp_path)
    database_before = hashlib.sha256(database.read_bytes()).hexdigest()
    object_before = hashlib.sha256(stored.path.read_bytes()).hexdigest()

    report = run_restore_drill(
        database,
        objects,
        expected_schema=DocumentRegistry.CURRENT_SCHEMA_VERSION,
    )

    assert report["status"] == "passed"
    assert report["schema_version"] == DocumentRegistry.CURRENT_SCHEMA_VERSION
    assert report["table_counts"]["assets"] == 1
    assert report["referenced_objects"] == 1
    assert report["copied_object_files"] == 1
    assert hashlib.sha256(database.read_bytes()).hexdigest() == database_before
    assert hashlib.sha256(stored.path.read_bytes()).hexdigest() == object_before


@pytest.mark.parametrize(
    ("unsafe_key", "expected_error"),
    [
        (None, "缺少数据库引用的对象"),
        ("../outside", "不安全的对象 key"),
    ],
)
def test_restore_drill_rejects_incomplete_or_unsafe_object_snapshots(
    tmp_path: Path,
    unsafe_key: str | None,
    expected_error: str,
):
    database, objects, stored, _asset = _registry_with_asset(tmp_path, object_key=unsafe_key)
    if unsafe_key is None:
        stored.path.unlink()

    with pytest.raises(RestoreDrillError, match=expected_error):
        run_restore_drill(
            database,
            objects,
            expected_schema=DocumentRegistry.CURRENT_SCHEMA_VERSION,
        )
