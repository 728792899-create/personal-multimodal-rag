from __future__ import annotations

import os
import uuid

import pytest

from app.services.document_registry import DocumentRegistry
from app.services.registry_migration import migrate_sqlite_to_postgres


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_DSN"), reason="requires PostgreSQL service")
def test_postgres_registry_matches_local_job_contract():
    registry = DocumentRegistry(os.environ["TEST_POSTGRES_DSN"])
    key = f"postgres-contract-{uuid.uuid4()}"
    job = registry.create_index_job(
        source_type="url",
        source_name="example.org",
        payload={"url": "https://example.org"},
        knowledge_base_id="default",
        idempotency_key=key,
    )

    claimed = registry.claim_next_index_job("contract-worker", lease_seconds=30)
    assert claimed["id"] == job["id"]
    assert claimed["status"] == "running"
    assert registry.complete_index_job(job["id"], "document-1")["status"] == "succeeded"


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_DSN"), reason="requires PostgreSQL service")
def test_sqlite_to_postgres_migration_preserves_ids_and_checksums(tmp_path):
    sqlite_path = tmp_path / "registry.sqlite3"
    source = DocumentRegistry(str(sqlite_path))
    knowledge_base = source.create_knowledge_base("Migration contract")

    report = migrate_sqlite_to_postgres(
        str(sqlite_path),
        os.environ["TEST_POSTGRES_DSN"],
    )
    destination = DocumentRegistry(os.environ["TEST_POSTGRES_DSN"])

    assert destination.get_knowledge_base(knowledge_base["id"])["name"] == "Migration contract"
    assert report["verification"]["knowledge_bases"]["verified"] == 2
    assert (
        report["verification"]["knowledge_bases"]["source_sha256"]
        == report["verification"]["knowledge_bases"]["destination_sha256"]
    )
    assert report["backup"]
