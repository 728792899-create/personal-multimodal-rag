from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.models.domain import Document, DocumentPage
from app.services.document_processor import DocumentProcessor
from app.services.document_registry import DEFAULT_KNOWLEDGE_BASE_ID, DocumentRegistry


def _document(name: str = "legacy.md", *, content_hash: str = "hash-1") -> Document:
    return Document(
        document_id=f"doc-{name}",
        file_name=name,
        file_path=name,
        file_type="markdown",
        title=name,
        created_at=datetime.utcnow(),
        pages=[DocumentPage(text="# Durable local\n\nEvidence stays local.")],
        metadata={"content_hash": content_hash},
    )


def test_registry_migrates_existing_documents_into_default_knowledge_base(tmp_path):
    path = tmp_path / "registry.sqlite3"
    registry = DocumentRegistry(str(path))
    registry.save_document(_document())
    registry.close()

    migrated = DocumentRegistry(str(path))
    knowledge_bases = migrated.list_knowledge_bases()
    documents = migrated.load_documents()

    assert migrated.schema_version == migrated.CURRENT_SCHEMA_VERSION
    assert knowledge_bases[0]["id"] == DEFAULT_KNOWLEDGE_BASE_ID
    assert knowledge_bases[0]["is_default"] is True
    assert documents[0].metadata["knowledge_base_id"] == DEFAULT_KNOWLEDGE_BASE_ID


def test_registry_migrates_a_pre_02_documents_table_and_creates_backup(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE documents (document_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        legacy = _document("pre-02.md")
        connection.execute(
            "INSERT INTO documents (document_id, payload) VALUES (?, ?)",
            (legacy.document_id, legacy.model_dump_json()),
        )

    migrated = DocumentRegistry(str(path))

    assert migrated.get_document(legacy.document_id).metadata["knowledge_base_id"] == "default"
    assert migrated.schema_version == migrated.CURRENT_SCHEMA_VERSION
    assert list(tmp_path.glob("legacy.sqlite3.bak-*"))


def test_knowledge_base_delete_requires_force_when_it_contains_documents(tmp_path):
    registry = DocumentRegistry(str(tmp_path / "registry.sqlite3"))
    knowledge_base = registry.create_knowledge_base("Research")
    conversation = registry.create_conversation("Research chat", [knowledge_base["id"]])
    document = _document("research.md")
    document.metadata["knowledge_base_id"] = knowledge_base["id"]
    registry.save_document(document)
    with pytest.raises(ValueError, match="contains documents"):
        registry.delete_knowledge_base(knowledge_base["id"])
    job = registry.create_index_job(
        source_type="url",
        source_name="example.com/research",
        payload={"url": "https://example.com/research"},
        knowledge_base_id=knowledge_base["id"],
        idempotency_key="research-delete-job",
    )
    with pytest.raises(ValueError, match="active index jobs"):
        registry.delete_knowledge_base(knowledge_base["id"], force=True)

    registry.request_index_job_cancel(job["id"])
    with pytest.raises(ValueError, match="contains documents"):
        registry.delete_knowledge_base(knowledge_base["id"])

    assert registry.delete_knowledge_base(knowledge_base["id"], force=True) is True
    assert registry.get_document(document.document_id) is None
    assert all(item["knowledge_base_id"] != knowledge_base["id"] for item in registry.list_index_jobs())
    assert registry.get_conversation(conversation["id"])["knowledge_base_ids"] == [DEFAULT_KNOWLEDGE_BASE_ID]
    with pytest.raises(ValueError, match="default"):
        registry.delete_knowledge_base(DEFAULT_KNOWLEDGE_BASE_ID, force=True)


def test_empty_knowledge_base_delete_repairs_conversation_scope(tmp_path):
    registry = DocumentRegistry(str(tmp_path / "registry.sqlite3"))
    knowledge_base = registry.create_knowledge_base("Temporary")
    conversation = registry.create_conversation("Temporary chat", [knowledge_base["id"]])

    assert registry.delete_knowledge_base(knowledge_base["id"]) is True
    assert registry.get_conversation(conversation["id"])["knowledge_base_ids"] == [DEFAULT_KNOWLEDGE_BASE_ID]


def test_content_hash_deduplication_is_scoped_to_knowledge_base(tmp_path):
    registry = DocumentRegistry(str(tmp_path / "registry.sqlite3"))
    first = registry.create_knowledge_base("First")
    second = registry.create_knowledge_base("Second")
    document = _document(content_hash="same")
    document.metadata["knowledge_base_id"] = first["id"]
    registry.save_document(document)

    assert registry.find_by_content_hash("same", first["id"]) is not None
    assert registry.find_by_content_hash("same", second["id"]) is None


def test_index_job_claim_retry_cancel_and_stale_recovery(tmp_path):
    registry = DocumentRegistry(str(tmp_path / "registry.sqlite3"))
    job = registry.create_index_job(
        source_type="url",
        source_name="example.com/guide",
        payload={"url": "https://example.com/guide"},
        knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        idempotency_key="stable-key",
    )
    duplicate = registry.create_index_job(
        source_type="url",
        source_name="example.com/guide",
        payload={"url": "https://example.com/guide"},
        knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        idempotency_key="stable-key",
    )
    assert duplicate["id"] == job["id"]

    claimed = registry.claim_next_index_job(worker_id="worker-1", lease_seconds=30)
    assert claimed and claimed["status"] == "running"
    failed = registry.fail_index_job(claimed["id"], "SAFE_ERROR", "temporary failure")
    assert failed["status"] == "queued"
    assert failed["attempts"] == 1

    registry.make_index_job_available(failed["id"])
    claimed_again = registry.claim_next_index_job(worker_id="worker-2", lease_seconds=0)
    assert claimed_again and claimed_again["attempts"] == 2
    assert registry.recover_stale_index_jobs() == 1
    cancelled = registry.request_index_job_cancel(claimed_again["id"])
    assert cancelled["status"] == "cancelled"


def test_conversations_persist_ordered_messages_and_bounded_context(tmp_path):
    path = tmp_path / "registry.sqlite3"
    registry = DocumentRegistry(str(path))
    conversation = registry.create_conversation("Durable chat", [DEFAULT_KNOWLEDGE_BASE_ID])
    for index in range(8):
        registry.save_conversation_message(conversation["id"], "user", f"question {index}")
        registry.save_conversation_message(conversation["id"], "assistant", f"answer {index}")
    registry.close()

    reopened = DocumentRegistry(str(path))
    messages = reopened.list_conversation_messages(conversation["id"])
    context = reopened.conversation_context(conversation["id"], max_turns=3, max_chars=200)

    assert len(messages) == 16
    assert [item["content"] for item in context] == [
        "question 5", "answer 5", "question 6", "answer 6", "question 7", "answer 7"
    ]


def test_docx_parser_preserves_headings_and_tables(tmp_path):
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_heading("Architecture", level=1)
    document.add_paragraph("The local worker owns durable indexing.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Stage"
    table.cell(0, 1).text = "State"
    table.cell(1, 0).text = "Index"
    table.cell(1, 1).text = "queued"
    path = tmp_path / "architecture.docx"
    document.save(path)

    parsed = DocumentProcessor().parse_file(path)
    chunks = DocumentProcessor().split(parsed)

    assert parsed.file_type == "docx"
    assert parsed.metadata["parser"] == "python-docx"
    assert "Architecture" in parsed.text
    assert "Stage | State" in parsed.text
    assert any("Architecture" in chunk.heading_path for chunk in chunks)


def test_docx_validation_rejects_missing_office_content_types(tmp_path):
    path = tmp_path / "fake.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", "<document />")

    with pytest.raises(ValueError, match="Office document"):
        DocumentProcessor().parse_file(path)


def test_docx_validation_rejects_suspicious_expansion(tmp_path):
    path = tmp_path / "bomb.docx"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", io.BytesIO(b"A" * 2_000_000).getvalue())

    processor = DocumentProcessor(docx_max_uncompressed_bytes=128_000)
    with pytest.raises(ValueError, match="expanded size"):
        processor.parse_file(path)


def test_knowledge_base_and_async_ingestion_api(monkeypatch, tmp_path):
    from app.api.routers import ingestion
    from app.main import app

    monkeypatch.setattr(ingestion, "INGESTION_DIR", tmp_path)
    with TestClient(app) as client:
        created = client.post("/api/knowledge-bases", json={"name": "API Research"})
        assert created.status_code == 201
        knowledge_base_id = created.json()["knowledge_base"]["id"]

        queued = client.post(
            "/api/ingestions/file",
            data={"knowledge_base_id": knowledge_base_id},
            files={"file": ("durable.md", b"# Queue\n\nDurable jobs survive process restarts.", "text/markdown")},
        )
        assert queued.status_code == 202
        assert "payload" not in queued.json()["job"]
        assert str(tmp_path) not in queued.text
        job_id = queued.json()["job"]["id"]

        terminal = None
        for _ in range(100):
            response = client.get(f"/api/index-jobs/{job_id}")
            terminal = response.json()["job"]
            if terminal["status"] in {"succeeded", "failed"}:
                break
            import time

            time.sleep(0.02)

        assert terminal and terminal["status"] == "succeeded"
        assert terminal["document_id"]
        detail = client.get(f"/api/documents/{terminal['document_id']}").json()
        assert detail["document"]["metadata"]["knowledge_base_id"] == knowledge_base_id

        blocked = client.delete(f"/api/knowledge-bases/{knowledge_base_id}")
        assert blocked.status_code == 409


def test_conversation_sse_has_stable_event_order_and_persists_messages():
    from app.main import app

    with TestClient(app) as client:
        upload = client.post(
            "/api/documents",
            files={"file": ("stream.md", b"# Streaming\n\nStreaming answers retain grounded citations.", "text/markdown")},
        )
        assert upload.status_code == 200
        conversation = client.post(
            "/api/conversations",
            json={"title": "Streaming test", "knowledge_base_ids": ["default"]},
        )
        assert conversation.status_code == 201
        conversation_id = conversation.json()["conversation"]["id"]

        response = client.post(
            f"/api/conversations/{conversation_id}/messages:stream",
            json={"question": "What do streaming answers retain?", "query_rewrite": False},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = [line.removeprefix("event: ") for line in response.text.splitlines() if line.startswith("event: ")]
        assert events[0] == "retrieval.started"
        assert "retrieval.completed" in events
        assert "answer.delta" in events
        assert events[-2:] == ["answer.completed", "done"]

        messages = client.get(f"/api/conversations/{conversation_id}/messages")
        assert messages.status_code == 200
        stored = messages.json()["messages"]
        assert [message["role"] for message in stored[-2:]] == ["user", "assistant"]
        assert stored[-1]["status"] == "completed"


def test_conversation_follow_up_uses_recent_questions_for_retrieval():
    from app.main import app

    with TestClient(app) as client:
        knowledge_base_id = client.post(
            "/api/knowledge-bases",
            json={"name": "AlphaFlux isolated"},
        ).json()["knowledge_base"]["id"]
        upload = client.post(
            "/api/documents",
            data={"knowledge_base_id": knowledge_base_id},
            files={"file": ("alphaflux.md", b"# AlphaFlux\n\nAlphaFlux retains grounded citations after streaming completes.", "text/markdown")},
        )
        assert upload.status_code == 200
        conversation_id = client.post(
            "/api/conversations",
            json={"title": "Follow-up test", "knowledge_base_ids": [knowledge_base_id]},
        ).json()["conversation"]["id"]

        first = client.post(
            f"/api/conversations/{conversation_id}/messages:stream",
            json={"question": "What does AlphaFlux retain?", "query_rewrite": False},
        )
        assert "event: answer.completed" in first.text

        follow_up = client.post(
            f"/api/conversations/{conversation_id}/messages:stream",
            json={"question": "What does it retain?", "query_rewrite": False},
        )
        events = [
            json.loads(line.removeprefix("data: "))
            for line in follow_up.text.splitlines()
            if line.startswith("data: ")
        ]
        completed = next(event for event in events if event["type"] == "answer.completed")
        assert completed["response"]["retrieval_trace"]["conversation_context_used"] is True
        assert completed["response"]["citations"][0]["filename"] == "alphaflux.md"


def test_provider_status_never_exposes_secrets(monkeypatch):
    from app.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "answer_api_key", "sk-super-secret")
    with TestClient(app) as client:
        response = client.get("/api/providers/status")
    assert response.status_code == 200
    body = response.text
    assert "sk-super-secret" not in body
    assert "api_key" not in body.lower()
