from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from production_backup import artifact  # noqa: E402
from production_restore import verify_manifest  # noqa: E402
from s3_archive import safe_object_key  # noqa: E402


def test_production_backup_manifest_verifies_every_artifact(tmp_path):
    database = tmp_path / "postgres.dump"
    objects = tmp_path / "minio-objects.tar"
    database.write_bytes(b"postgres-backup")
    objects.write_bytes(b"objects-backup")
    manifest = {
        "schema_version": 1,
        "created_at": "2026-07-23T00:00:00Z",
        "artifacts": [artifact(database), artifact(objects)],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    assert verify_manifest(tmp_path)["created_at"] == "2026-07-23T00:00:00Z"


def test_production_backup_manifest_rejects_tampering(tmp_path):
    database = tmp_path / "postgres.dump"
    database.write_bytes(b"original")
    (tmp_path / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "artifacts": [artifact(database)]}),
        encoding="utf-8",
    )
    database.write_bytes(b"tampered")

    with pytest.raises(ValueError, match="checksum"):
        verify_manifest(tmp_path)


@pytest.mark.parametrize("key", ["../secret", "/absolute", r"folder\\secret", "folder/../secret"])
def test_s3_archive_rejects_unsafe_object_keys(key):
    with pytest.raises(ValueError, match="unsafe"):
        safe_object_key(key)


def test_s3_archive_accepts_content_addressed_keys():
    digest = "a" * 64
    assert safe_object_key(f"aa/{digest}") == f"aa/{digest}"
