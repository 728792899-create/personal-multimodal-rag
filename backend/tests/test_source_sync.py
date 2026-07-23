from __future__ import annotations

from dataclasses import replace

import pytest

from app.config import Settings
from app.services.document_registry import DocumentRegistry
from app.services.document_processor import DocumentProcessor
from app.services.object_store import LocalObjectStore
from app.services.source_connectors import (
    DirectoryConnector,
    DiscoveryResult,
    FeedConnector,
    SourceCandidate,
    SourceRootResolver,
)
from app.services.source_sync import SourceSyncService


def _candidate(external_id: str, payload: bytes) -> SourceCandidate:
    import hashlib

    return SourceCandidate(
        external_id=external_id,
        location=external_id,
        title=f"{external_id}.md",
        filename=f"{external_id}.md",
        media_type="text/markdown",
        payload=payload,
        content_hash=hashlib.sha256(payload).hexdigest(),
    )


class SequenceConnector:
    type = "test"

    def __init__(self, results: list[DiscoveryResult]):
        self.results = results

    def discover(self, _source):
        return self.results.pop(0)


class Registry:
    def __init__(self, connector):
        self.connector = connector

    def get(self, source_type: str):
        assert source_type == "test"
        return self.connector


def _service(tmp_path, results):
    registry = DocumentRegistry(":memory:")
    source = registry.create_source(
        source_type="test",
        name="Contract",
        config={},
    )
    service = SourceSyncService(
        registry,
        LocalObjectStore(tmp_path / "objects"),
        Registry(SequenceConnector(results)),
        replace(Settings(), provider_fallback_allowed=True),
    )
    return registry, source, service


def test_source_sync_queues_changed_items_and_skips_indexed_unchanged_items(tmp_path):
    candidate = _candidate("guide", b"# durable guide")
    registry, source, service = _service(
        tmp_path,
        [
            DiscoveryResult([candidate]),
            DiscoveryResult([candidate]),
        ],
    )

    first = service.sync(source["id"])
    item = registry.list_source_items(source["id"])[0]
    registry.mark_source_item_indexed(item["id"], "document-1")
    second = service.sync(source["id"])

    assert first["status"] == "succeeded"
    assert first["updated"] == 1
    assert len(registry.list_index_jobs()) == 1
    assert second["unchanged"] == 1
    assert second["updated"] == 0


def test_deletion_requires_two_complete_nonempty_syncs_and_confirmation(tmp_path):
    alpha = _candidate("alpha", b"alpha")
    beta = _candidate("beta", b"beta")
    registry, source, service = _service(
        tmp_path,
        [
            DiscoveryResult([alpha]),
            DiscoveryResult([beta]),
            DiscoveryResult([beta]),
        ],
    )
    service.sync(source["id"])
    alpha_item = registry.find_source_item(source["id"], "alpha")
    registry.mark_source_item_indexed(alpha_item["id"], "missing-document")

    first_missing = service.sync(source["id"])
    second_missing = service.sync(source["id"])
    candidate = registry.find_source_item(source["id"], "alpha")

    assert first_missing["deletion_candidates"] == 0
    assert second_missing["deletion_candidates"] == 1
    assert candidate["deletion_candidate"] is True

    result = service.confirm_deletions(source["id"], [candidate["id"]])
    assert result == {
        "source_id": source["id"],
        "removed_items": 1,
        "removed_documents": 0,
    }
    assert registry.find_source_item(source["id"], "alpha") is None


def test_empty_or_partial_result_never_advances_deletion_state(tmp_path):
    alpha = _candidate("alpha", b"alpha")
    registry, source, service = _service(
        tmp_path,
        [
            DiscoveryResult([alpha]),
            DiscoveryResult([], empty_result=True),
            DiscoveryResult([], failures=["temporary feed failure"], complete=False),
        ],
    )
    service.sync(source["id"])

    empty = service.sync(source["id"])
    partial = service.sync(source["id"])
    item = registry.find_source_item(source["id"], "alpha")

    assert empty["empty_result"] is True
    assert partial["status"] == "failed"
    assert item["missing_successes"] == 0
    assert item["deletion_candidate"] is False


def test_confirmed_deletion_cascades_document_asset_and_retriever(tmp_path):
    candidate = _candidate("alpha", b"alpha")
    registry, source, service = _service(
        tmp_path,
        [DiscoveryResult([candidate])],
    )
    service.sync(source["id"])
    item = registry.find_source_item(source["id"], "alpha")
    document = DocumentProcessor().parse_text_source("alpha evidence", "alpha.md")
    document.metadata["knowledge_base_id"] = "default"
    registry.save_document(document)
    registry.mark_source_item_indexed(item["id"], document.document_id)
    stored = service.object_store.put_bytes(b"original")
    asset = registry.create_asset(
        knowledge_base_id="default",
        kind="source",
        object_key=stored.object_key,
        original_name="alpha.md",
        media_type="text/markdown",
        sha256=stored.sha256,
        size_bytes=stored.size_bytes,
        document_id=document.document_id,
    )
    registry.mark_missing_source_items(source["id"], set())
    registry.mark_missing_source_items(source["id"], set())

    class Retriever:
        deleted: list[str] = []

        def delete_document(self, document_id: str):
            self.deleted.append(document_id)

    retriever = Retriever()
    service.retriever = retriever
    result = service.confirm_deletions(source["id"])

    assert result["removed_documents"] == 1
    assert retriever.deleted == [document.document_id]
    assert registry.get_document(document.document_id) is None
    assert registry.get_asset(asset["id"]) is None
    assert stored.path and not stored.path.exists()


def test_source_root_resolver_rejects_absolute_traversal_and_symlink(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    resolver = SourceRootResolver(str(root))
    root_id = resolver.public_roots()[0]["id"]

    assert resolver.resolve(root_id) == root.resolve()
    with pytest.raises(ValueError, match="relative"):
        resolver.resolve(root_id, "../outside")
    with pytest.raises(ValueError, match="relative"):
        resolver.resolve(root_id, str(outside))
    with pytest.raises(ValueError, match="escapes"):
        resolver.resolve(root_id, "escape")


def test_directory_connector_discovers_supported_files_with_relative_ids(tmp_path):
    root = tmp_path / "allowed"
    nested = root / "notes"
    nested.mkdir(parents=True)
    (nested / "evidence.md").write_text("# Evidence", encoding="utf-8")
    (nested / "ignored.exe").write_bytes(b"binary")
    resolver = SourceRootResolver(str(root))
    connector = DirectoryConnector(resolver, max_items=10, max_bytes=1024)

    result = connector.discover(
        {
            "config": {
                "root_id": resolver.public_roots()[0]["id"],
                "relative_path": "",
                "recursive": True,
            }
        }
    )

    assert result.complete is True
    assert [item.external_id for item in result.candidates] == ["notes/evidence.md"]
    assert result.candidates[0].payload == b"# Evidence"


def test_atom_parser_preserves_stable_id_and_link():
    entries = FeedConnector._parse_entries(
        b"""<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry><id>tag:example,1</id><title>Evidence</title>
          <link href="https://example.org/evidence"/></entry>
        </feed>"""
    )

    assert entries == [
        {
            "url": "https://example.org/evidence",
            "title": "Evidence",
            "external_id": "tag:example,1",
        }
    ]


def test_feed_parser_rejects_dtd_and_entities():
    with pytest.raises(ValueError, match="DTD"):
        FeedConnector._parse_entries(
            b'<!DOCTYPE feed [<!ENTITY x "boom">]><feed><entry><title>&x;</title></entry></feed>'
        )


def test_interrupted_sync_run_is_recoverable_after_restart():
    registry = DocumentRegistry(":memory:")
    source = registry.create_source(source_type="test", name="Interrupted", config={})
    run = registry.start_sync_run(source["id"])

    assert registry.recover_interrupted_sync_runs() == 1
    recovered = registry.get_sync_run(run["id"])
    assert recovered["status"] == "failed"
    assert recovered["partial"] is True
    assert "retry is safe" in recovered["error_message"]
