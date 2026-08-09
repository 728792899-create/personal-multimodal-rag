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

    migrated_document = migrated.get_document(legacy.document_id)
    assert migrated_document.metadata["knowledge_base_id"] == "default"
    assert migrated_document.metadata["source_available"] is False
    assert migrated.schema_version == migrated.CURRENT_SCHEMA_VERSION
    assert list(tmp_path.glob("legacy.sqlite3.bak-*"))


def test_knowledge_base_delete_requires_force_when_it_contains_documents(tmp_path):
    registry = DocumentRegistry(str(tmp_path / "registry.sqlite3"))
    knowledge_base = registry.create_knowledge_base("Research")
    conversation = registry.create_conversation("Research chat", [knowledge_base["id"]])
    document = _document("research.md")
    document.metadata["knowledge_base_id"] = knowledge_base["id"]
    registry.save_document(document)
    with pytest.raises(ValueError, match="仍包含文档"):
        registry.delete_knowledge_base(knowledge_base["id"])
    job = registry.create_index_job(
        source_type="url",
        source_name="example.com/research",
        payload={"url": "https://example.com/research"},
        knowledge_base_id=knowledge_base["id"],
        idempotency_key="research-delete-job",
    )
    with pytest.raises(ValueError, match="运行中的索引任务"):
        registry.delete_knowledge_base(knowledge_base["id"], force=True)

    registry.request_index_job_cancel(job["id"])
    with pytest.raises(ValueError, match="仍包含文档"):
        registry.delete_knowledge_base(knowledge_base["id"])

    assert registry.delete_knowledge_base(knowledge_base["id"], force=True) is True
    assert registry.get_document(document.document_id) is None
    assert all(item["knowledge_base_id"] != knowledge_base["id"] for item in registry.list_index_jobs())
    assert registry.get_conversation(conversation["id"])["knowledge_base_ids"] == [DEFAULT_KNOWLEDGE_BASE_ID]
    with pytest.raises(ValueError, match="默认知识库"):
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


def test_running_index_job_cooperative_cancel_reaches_terminal_state(tmp_path):
    registry = DocumentRegistry(str(tmp_path / "registry.sqlite3"))
    job = registry.create_index_job(
        source_type="url",
        source_name="example.com/cancel",
        payload={"url": "https://example.com/cancel"},
        knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        idempotency_key="cooperative-cancel",
    )
    claimed = registry.claim_next_index_job(worker_id="worker-1", lease_seconds=30)
    assert claimed and claimed["id"] == job["id"]
    assert registry.request_index_job_cancel(job["id"])["status"] == "cancelling"

    cancelled = registry.complete_index_job_cancellation(job["id"])

    assert cancelled["status"] == "cancelled"
    assert cancelled["stage"] == "cancelled"
    assert cancelled["completed_at"]
    with registry.transaction() as connection:
        row = connection.execute(
            "SELECT worker_id, lease_expires_at FROM index_jobs WHERE job_id = ?",
            (job["id"],),
        ).fetchone()
    assert row["worker_id"] == "" and row["lease_expires_at"] == ""
    assert registry.claim_next_index_job(worker_id="worker-2") is None


def test_stale_cancelling_job_recovers_as_cancelled_instead_of_stuck_queued(tmp_path):
    registry = DocumentRegistry(str(tmp_path / "registry.sqlite3"))
    job = registry.create_index_job(
        source_type="url",
        source_name="example.com/stale-cancel",
        payload={"url": "https://example.com/stale-cancel"},
        knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        idempotency_key="stale-cancel",
    )
    claimed = registry.claim_next_index_job(worker_id="worker-1", lease_seconds=0)
    assert claimed and claimed["id"] == job["id"]
    assert registry.request_index_job_cancel(job["id"])["status"] == "cancelling"

    assert registry.recover_stale_index_jobs() == 1

    recovered = registry.get_index_job(job["id"])
    assert recovered["status"] == "cancelled"
    assert recovered["completed_at"]
    assert registry.claim_next_index_job(worker_id="worker-2") is None


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


def test_conversation_retrieval_traces_feed_health_rollups_without_content(tmp_path):
    registry = DocumentRegistry(str(tmp_path / "registry.sqlite3"))
    conversation = registry.create_conversation(
        "Health trace", [DEFAULT_KNOWLEDGE_BASE_ID]
    )
    trace = {
        "pipeline": {
            "retrieval_health": {
                "eligible": True,
                "status": "healthy",
                "alerts": [],
            }
        }
    }
    registry.save_conversation_message(
        conversation["id"],
        "assistant",
        "private answer content",
        metadata={"response": {"retrieval_trace": trace}},
    )
    registry.save_conversation_message(
        conversation["id"], "user", "private question content"
    )

    assert registry.conversation_retrieval_traces() == [trace]


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

    with pytest.raises(ValueError, match="Office 文档"):
        DocumentProcessor().parse_file(path)


def test_docx_validation_rejects_suspicious_expansion(tmp_path):
    path = tmp_path / "bomb.docx"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", io.BytesIO(b"A" * 2_000_000).getvalue())

    processor = DocumentProcessor(docx_max_uncompressed_bytes=128_000)
    with pytest.raises(ValueError, match="解压后大小"):
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
        assert detail["document"]["metadata"]["enrichment"]["provider"] == "template"
        assert detail["document"]["metadata"]["graph"]["node_count"] >= 2
        graph = client.get(f"/api/knowledge-bases/{knowledge_base_id}/graph")
        assert graph.status_code == 200
        assert graph.json()["summary"]["evidence_element_count"] >= 1

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


def test_conversation_sse_localizes_provider_failures(monkeypatch):
    from app.api.routers import conversations
    from app.main import app

    def failing_stream(*_args, **_kwargs):
        raise RuntimeError("provider request failed at https://private.example")
        yield  # pragma: no cover - keeps this function a generator

    monkeypatch.setattr(conversations.rag_engine, "stream", failing_stream)
    with TestClient(app) as client:
        conversation_id = client.post(
            "/api/conversations",
            json={"title": "Failure localization", "knowledge_base_ids": ["default"]},
        ).json()["conversation"]["id"]
        response = client.post(
            f"/api/conversations/{conversation_id}/messages:stream",
            json={"question": "测试失败提示", "query_rewrite": False},
        )
        payloads = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]

        error = next(item for item in payloads if item["type"] == "error")
        assert error["code"] == "STREAM_FAILED"
        assert error["message"] == "流式回答失败，请稍后重试；如问题持续，请查看服务状态。"
        assert "provider request failed" not in response.text
        assert payloads[-1]["type"] == "done"
        assert payloads[-1]["status"] == "failed"

        stored = client.get(f"/api/conversations/{conversation_id}/messages").json()["messages"]
        assert stored[-1]["status"] == "failed"
        assert stored[-1]["metadata"]["error"] == error["message"]


def test_conversation_sse_keeps_the_proxy_connection_alive_during_provider_wait(monkeypatch):
    from app.api.routers import conversations
    from app.main import app

    def delayed_timeout(*_args, **_kwargs):
        import time

        time.sleep(0.04)
        raise TimeoutError("provider exceeded its answer budget")
        yield  # pragma: no cover - keeps this function a generator

    monkeypatch.setattr(conversations, "SSE_HEARTBEAT_SECONDS", 0.01, raising=False)
    monkeypatch.setattr(conversations.rag_engine, "stream", delayed_timeout)
    with TestClient(app) as client:
        conversation_id = client.post(
            "/api/conversations",
            json={"title": "Heartbeat test", "knowledge_base_ids": ["default"]},
        ).json()["conversation"]["id"]

        response = client.post(
            f"/api/conversations/{conversation_id}/messages:stream",
            json={"question": "等待本地模型", "query_rewrite": False},
        )

    assert ": keep-alive" in response.text
    payloads = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert payloads[-2]["type"] == "error"
    assert payloads[-2]["code"] == "ANSWER_PROVIDER_TIMEOUT"
    assert payloads[-1]["type"] == "done"
    assert payloads[-1]["status"] == "failed"


def test_conversation_sse_metrics_use_the_request_provider_snapshot(
    monkeypatch,
):
    from types import SimpleNamespace

    from app.api.routers import conversations
    from app.main import app

    snapshot = SimpleNamespace(name="deepseek_official")
    recorded: list[tuple[str, str]] = []

    class Metrics:
        def record_answer(self, _response, *, provider):
            recorded.append(("answer", provider))

        def record_provider_error(self, *, provider, operation):
            recorded.append((operation, provider))

    def completed_stream(*_args, answer_generator_snapshot=None, **_kwargs):
        assert answer_generator_snapshot is snapshot
        response = {
            "answer": "根据证据无法确定。",
            "citations": [],
            "retrieval_trace": {
                "pipeline": {"decision": {"status": "refused"}}
            },
            "generation_trace": {
                "answer_provider": "deepseek_official",
                "skipped": True,
            },
            "confidence": 0,
            "diagnostics": [],
            "citation_audit": {},
            "trust": {},
        }
        yield {"type": "retrieval.completed", "response": response}
        yield {"type": "refusal", "response": response}

    monkeypatch.setattr(
        conversations.rag_engine,
        "snapshot_answer_generator",
        lambda: snapshot,
    )
    monkeypatch.setattr(
        conversations.rag_engine,
        "stream",
        completed_stream,
    )
    monkeypatch.setattr(conversations, "production_metrics", Metrics())

    with TestClient(app) as client:
        conversation_id = client.post(
            "/api/conversations",
            json={
                "title": "Provider metric snapshot",
                "knowledge_base_ids": ["default"],
            },
        ).json()["conversation"]["id"]
        response = client.post(
            f"/api/conversations/{conversation_id}/messages:stream",
            json={"question": "无法回答的问题", "query_rewrite": False},
        )

    assert response.status_code == 200
    assert recorded == [("answer", "deepseek_official")]


def test_conversation_sse_error_metric_and_trace_use_provider_snapshot(
    monkeypatch,
):
    from types import SimpleNamespace

    from app.api.routers import conversations
    from app.main import app

    snapshot = SimpleNamespace(name="deepseek_official")
    recorded: list[tuple[str, str]] = []

    class Metrics:
        def record_answer(self, _response, *, provider):
            recorded.append(("answer", provider))

        def record_provider_error(self, *, provider, operation):
            recorded.append((operation, provider))

    def failing_stream(*_args, answer_generator_snapshot=None, **_kwargs):
        assert answer_generator_snapshot is snapshot
        yield {
            "type": "retrieval.completed",
            "response": {
                "citations": [],
                "retrieval_trace": {},
                "generation_trace": {
                    "answer_provider": "deepseek_official",
                    "status": "pending",
                },
                "confidence": 0.4,
                "diagnostics": [],
            },
        }
        raise RuntimeError("provider failed api_key=telemetry-canary")

    monkeypatch.setattr(
        conversations.rag_engine,
        "snapshot_answer_generator",
        lambda: snapshot,
    )
    monkeypatch.setattr(conversations.rag_engine, "stream", failing_stream)
    monkeypatch.setattr(conversations, "production_metrics", Metrics())

    with TestClient(app) as client:
        conversation_id = client.post(
            "/api/conversations",
            json={
                "title": "Provider error metric snapshot",
                "knowledge_base_ids": ["default"],
            },
        ).json()["conversation"]["id"]
        response = client.post(
            f"/api/conversations/{conversation_id}/messages:stream",
            json={"question": "触发错误", "query_rewrite": False},
        )
        stored = client.get(
            f"/api/conversations/{conversation_id}/messages"
        ).json()["messages"]

    assert response.status_code == 200
    assert recorded == [("stream", "deepseek_official")]
    persisted = stored[-1]["metadata"]["response"]
    assert (
        persisted["generation_trace"]["answer_provider"]
        == "deepseek_official"
    )
    assert "telemetry-canary" not in response.text


def test_conversation_stream_heartbeat_queue_snapshots_mutable_events():
    from app.api.routers import conversations

    trace = {"pipeline": {"decision": {"status": "answered"}}}

    def mutable_stream():
        yield {
            "type": "retrieval.completed",
            "response": {
                "citations": [],
                "retrieval_trace": trace,
                "confidence": 0.4,
                "diagnostics": [],
            },
        }
        trace["pipeline"]["citation_audit"] = {"status": "checked"}
        yield {"type": "answer.delta", "delta": "正文"}

    wrapped = conversations._stream_with_heartbeats(mutable_stream())
    retrieval_event = next(wrapped)
    wrapped.close()

    assert retrieval_event is not None
    assert "citation_audit" not in retrieval_event["response"]["retrieval_trace"]["pipeline"]


def test_conversation_sse_fails_closed_when_engine_ends_without_a_terminal_answer(monkeypatch):
    from app.api.routers import conversations
    from app.main import app

    def incomplete_stream(*_args, **_kwargs):
        yield {
            "type": "retrieval.completed",
            "response": {
                "citations": [],
                "retrieval_trace": {},
                "confidence": 0.4,
                "diagnostics": [],
            },
        }

    monkeypatch.setattr(conversations.rag_engine, "stream", incomplete_stream)
    with TestClient(app) as client:
        conversation_id = client.post(
            "/api/conversations",
            json={"title": "Incomplete stream", "knowledge_base_ids": ["default"]},
        ).json()["conversation"]["id"]
        response = client.post(
            f"/api/conversations/{conversation_id}/messages:stream",
            json={"question": "回答不能消失", "query_rewrite": False},
        )

        payloads = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        stored = client.get(f"/api/conversations/{conversation_id}/messages").json()["messages"]

    assert [item["type"] for item in payloads][-2:] == ["error", "done"]
    assert payloads[-1]["status"] == "failed"
    assert stored[-1]["status"] == "failed"


def test_conversation_sse_persists_partial_answer_when_provider_fails(monkeypatch):
    from app.api.routers import conversations
    from app.main import app

    def partial_stream(*_args, **_kwargs):
        yield {
            "type": "retrieval.completed",
            "response": {
                "citations": [{"id": "chunk-1", "filename": "evidence.md", "snippet": "可恢复证据"}],
                "retrieval_trace": {"pipeline": {"decision": {"status": "answered"}}},
                "confidence": 0.4,
                "diagnostics": [{"level": "info", "title": "证据已找到"}],
            },
        }
        yield {"type": "answer.delta", "delta": "已经生成的可靠片段"}
        raise RuntimeError("provider disconnected")

    monkeypatch.setattr(conversations.rag_engine, "stream", partial_stream)
    with TestClient(app) as client:
        conversation_id = client.post(
            "/api/conversations",
            json={"title": "Partial answer", "knowledge_base_ids": ["default"]},
        ).json()["conversation"]["id"]
        response = client.post(
            f"/api/conversations/{conversation_id}/messages:stream",
            json={"question": "保留部分正文", "query_rewrite": False},
        )
        stored = client.get(f"/api/conversations/{conversation_id}/messages").json()["messages"]

    assert "event: error" in response.text
    assert stored[-1]["status"] == "failed"
    assert stored[-1]["content"] == "已经生成的可靠片段"
    persisted_response = stored[-1]["metadata"]["response"]
    assert persisted_response["answer"] == "已经生成的可靠片段"
    assert persisted_response["citations"][0]["id"] == "chunk-1"
    assert persisted_response["retrieval_trace"]["pipeline"]["decision"]["status"] == "answered"
    assert persisted_response["generation_trace"]["status"] == "failed"
    assert persisted_response["generation_trace"]["incomplete"] is True


def test_conversation_sse_persists_retrieval_evidence_when_client_cancels(monkeypatch):
    import anyio
    from fastapi import Request

    from app.api.routers import conversations
    from app.main import app
    from app.models.schemas import ConversationMessageRequest

    def retrieval_only_stream(*_args, **_kwargs):
        yield {
            "type": "retrieval.completed",
            "response": {
                "citations": [{"id": "chunk-cancelled", "filename": "source.md", "snippet": "取消前证据"}],
                "retrieval_trace": {"pipeline": {"retrieval": {"status": "complete"}}},
                "confidence": 0.5,
                "diagnostics": [],
            },
        }
        yield {"type": "answer.delta", "delta": "不应继续消费"}

    monkeypatch.setattr(conversations.rag_engine, "stream", retrieval_only_stream)
    monkeypatch.setattr(conversations, "_stream_with_heartbeats", lambda items: items)
    with TestClient(app) as client:
        conversation_id = client.post(
            "/api/conversations",
            json={"title": "Cancelled evidence", "knowledge_base_ids": ["default"]},
        ).json()["conversation"]["id"]
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": f"/api/conversations/{conversation_id}/messages:stream",
                "headers": [],
                "state": {},
            }
        )
        response = conversations.stream_conversation_message(
            conversation_id,
            ConversationMessageRequest(question="取消后保留证据", query_rewrite=False),
            request,
        )

        async def consume_until_retrieval_completed() -> None:
            async for chunk in response.body_iterator:
                if "event: retrieval.completed" in str(chunk):
                    break
            await response.body_iterator.aclose()

        anyio.run(consume_until_retrieval_completed)
        stored = client.get(f"/api/conversations/{conversation_id}/messages").json()["messages"]

    assert stored[-1]["status"] == "cancelled"
    persisted_response = stored[-1]["metadata"]["response"]
    assert persisted_response["answer"] == ""
    assert persisted_response["citations"][0]["id"] == "chunk-cancelled"
    assert persisted_response["retrieval_trace"]["pipeline"]["retrieval"]["status"] == "complete"
    assert persisted_response["generation_trace"]["status"] == "cancelled"
    assert persisted_response["generation_trace"]["incomplete"] is True


def test_conversation_sse_disconnect_after_completed_event_does_not_revert_message(monkeypatch):
    import anyio
    from fastapi import Request

    from app.api.routers import conversations
    from app.main import app
    from app.models.schemas import ConversationMessageRequest

    completed_response = {
        "answer": "已完成回答",
        "citations": [],
        "retrieval_trace": {},
        "generation_trace": {"answer_provider": "template"},
        "confidence": 0.4,
        "diagnostics": [],
        "citation_audit": {},
        "trust": {},
    }

    def completed_stream(*_args, **_kwargs):
        yield {
            "type": "retrieval.completed",
            "response": {
                "citations": [],
                "retrieval_trace": {},
                "confidence": 0.4,
                "diagnostics": [],
            },
        }
        yield {"type": "answer.delta", "delta": "已完成回答"}
        yield {"type": "answer.completed", "response": completed_response}

    monkeypatch.setattr(conversations.rag_engine, "stream", completed_stream)
    with TestClient(app) as client:
        conversation_id = client.post(
            "/api/conversations",
            json={"title": "Completed disconnect", "knowledge_base_ids": ["default"]},
        ).json()["conversation"]["id"]
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": f"/api/conversations/{conversation_id}/messages:stream",
                "headers": [],
                "state": {},
            }
        )
        response = conversations.stream_conversation_message(
            conversation_id,
            ConversationMessageRequest(question="完成后断开", query_rewrite=False),
            request,
        )

        async def consume_until_answer_completed() -> None:
            async for chunk in response.body_iterator:
                if "event: answer.completed" in str(chunk):
                    break
            await response.body_iterator.aclose()

        anyio.run(consume_until_answer_completed)
        stored = client.get(f"/api/conversations/{conversation_id}/messages").json()["messages"]

    assert stored[-1]["status"] == "completed"
    assert stored[-1]["content"] == "已完成回答"


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

        independent = client.post(
            f"/api/conversations/{conversation_id}/messages:stream",
            json={"question": "What is the payroll reconciliation policy?", "query_rewrite": False},
        )
        independent_events = [
            json.loads(line.removeprefix("data: "))
            for line in independent.text.splitlines()
            if line.startswith("data: ")
        ]
        refused = next(event for event in independent_events if event["type"] == "refusal")
        assert refused["response"]["retrieval_trace"]["conversation_context_used"] is False
        assert refused["response"]["citations"] == []


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
