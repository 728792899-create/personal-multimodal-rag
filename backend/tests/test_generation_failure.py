import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.models.domain import Chunk
from app.services.answer_generator import BaseAnswerGenerator
from app.services.rag_engine import RagEngine


class StaticEvidenceRetriever:
    embedding_provider = object()
    vector_store = SimpleNamespace(chunks={})

    def __init__(self):
        chunk = Chunk(
            chunk_id="chunk-evidence",
            document_id="document-evidence",
            chunk_index=0,
            text="RAG 升级使用可审计引用与受控降级。",
            file_name="evidence.md",
            page_number=2,
        )
        self.ranked = [
            {
                "chunk": chunk,
                "score": 0.92,
                "bm25_score": 0.8,
                "vector_score": 0.9,
                "rerank_score": 0.92,
                "matched_terms": ["RAG", "升级"],
                "parent_context": {
                    "strategy": "parent_child",
                    "text": chunk.text,
                    "chunk_ids": [chunk.chunk_id],
                },
            }
        ]

    def search(self, *_args, **_kwargs):
        return self.ranked, {
            "available_chunks": 1,
            "pipeline": {},
            "fallbacks": [],
        }


class FailingDeepSeekGenerator(BaseAnswerGenerator):
    name = "deepseek_official"

    def __init__(self):
        self.client = SimpleNamespace(model="deepseek-chat")

    def generate(self, _question, _citations, _trace):
        raise RuntimeError("upstream failed api_key=private-generation-secret")

    def stream(self, _question, _citations, _trace):
        raise RuntimeError("upstream failed api_key=private-generation-secret")
        yield  # pragma: no cover


def test_deepseek_generation_failure_returns_evidence_without_template_fallback():
    engine = RagEngine(
        StaticEvidenceRetriever(),
        answer_generator=FailingDeepSeekGenerator(),
        # Even a permissive developer profile must not invent a template answer
        # for a failed DeepSeek request.
        allow_generation_fallback=True,
    )

    response = engine.ask("RAG 升级使用什么机制？")

    assert response["answer"] == ""
    assert response["citations"][0]["id"] == "chunk-evidence"
    assert response["generation_trace"] == {
        "answer_provider": "deepseek_official",
        "answer_model": "deepseek-chat",
        "grounded": False,
        "status": "failed",
        "incomplete": True,
        "failure_stage": "generation",
        "error_code": "ANSWER_PROVIDER_FAILED",
        "message": "回答服务暂时不可用，已保留检索证据，请稍后重试。",
        "retryable": True,
    }
    assert response["retry"] == {
        "action": "resubmit_same_request",
        "preserve_retrieval_scope": True,
    }
    assert response["retrieval_trace"]["pipeline"]["generation"]["status"] == "failed"
    assert response["citation_audit"]["checked"] is False
    assert "template" not in str(response).lower()
    assert "private-generation-secret" not in str(response)


def test_openai_compatible_name_still_detects_deepseek_model():
    generator = FailingDeepSeekGenerator()
    generator.name = "openai_compatible_chat"
    engine = RagEngine(
        StaticEvidenceRetriever(),
        answer_generator=generator,
        allow_generation_fallback=True,
    )

    response = engine.ask("RAG 升级使用什么机制？")

    assert response["answer"] == ""
    assert response["generation_trace"]["status"] == "failed"
    assert response["citations"]


@pytest.mark.parametrize(
    "base_url",
    [
        "https://deepseek.com/v1",
        "https://api.deepseek.com/v1",
        "https://regional.api.deepseek.com./v1",
    ],
)
def test_official_deepseek_hostname_disables_template_fallback(base_url):
    generator = SimpleNamespace(
        name="openai_compatible_chat",
        client=SimpleNamespace(model="chat-model", base_url=base_url),
    )
    engine = RagEngine(StaticEvidenceRetriever(), allow_generation_fallback=True)

    assert engine._template_fallback_allowed(generator) is False


@pytest.mark.parametrize(
    "base_url",
    [
        "https://deepseek.com.evil.example/v1",
        "https://notdeepseek.com/v1",
        "https://api.deepseek.com@evil.example/v1",
        "https://evil.example/v1/deepseek.com",
        "https://api..deepseek.com/v1",
        "https://-api.deepseek.com/v1",
        "https://api_deepseek.com/v1",
        "https://api.deepseek.com%2eevil.example/v1",
    ],
)
def test_lookalike_deepseek_hostname_is_not_trusted(base_url):
    generator = SimpleNamespace(
        name="openai_compatible_chat",
        client=SimpleNamespace(model="chat-model", base_url=base_url),
    )
    engine = RagEngine(StaticEvidenceRetriever(), allow_generation_fallback=True)

    assert engine._template_fallback_allowed(generator) is True


def test_deepseek_stream_failure_never_emits_template_deltas():
    engine = RagEngine(
        StaticEvidenceRetriever(),
        answer_generator=FailingDeepSeekGenerator(),
        allow_generation_fallback=True,
    )
    stream = engine.stream("RAG 升级使用什么机制？")

    retrieval = next(stream)
    assert retrieval["type"] == "retrieval.completed"
    assert retrieval["response"]["citations"][0]["id"] == "chunk-evidence"
    with pytest.raises(RuntimeError):
        next(stream)


def test_sync_ask_api_exposes_retry_endpoint_for_structured_generation_failure(
    monkeypatch,
):
    from app.api.routers import retrieval
    from app.main import app

    snapshot = SimpleNamespace(name="deepseek_official")
    failed_response = {
        "answer": "",
        "citations": [
            {
                "id": "chunk-sync",
                "document_id": "document-sync",
                "filename": "sync-evidence.md",
                "index": 0,
                "text": "同步问答的检索证据。",
                "snippet": "同步问答的检索证据。",
                "score": 0.8,
            }
        ],
        "retrieval_trace": {"pipeline": {"generation": {"status": "failed"}}},
        "generation_trace": {
            "answer_provider": "deepseek_official",
            "status": "failed",
            "retryable": True,
        },
        "retryable": True,
        "retry": {"action": "resubmit_same_request"},
        "confidence": 0.8,
        "diagnostics": [],
        "trust": {"label": "证据较弱"},
        "citation_audit": {"checked": False},
    }
    recorded: list[tuple[str, str]] = []

    class Metrics:
        def record_provider_error(self, *, provider, operation):
            recorded.append((provider, operation))

        def record_answer(self, *_args, **_kwargs):
            raise AssertionError("failed generation must not be counted as an answer")

    monkeypatch.setattr(
        retrieval.rag_engine,
        "snapshot_answer_generator",
        lambda: snapshot,
    )
    monkeypatch.setattr(
        retrieval.rag_engine,
        "ask",
        lambda *_args, **_kwargs: failed_response,
    )
    monkeypatch.setattr(retrieval, "production_metrics", Metrics())

    with TestClient(app) as client:
        result = client.post(
            "/api/ask",
            json={"question": "测试同步生成失败", "query_rewrite": False},
        )

    assert result.status_code == 200
    payload = result.json()
    assert payload["answer"] == ""
    assert payload["citations"][0]["id"] == "chunk-sync"
    assert payload["generation_trace"]["status"] == "failed"
    assert payload["retry"] == {
        "action": "resubmit_same_request",
        "method": "POST",
        "endpoint": "/api/ask",
        "preserve_retrieval_scope": True,
    }
    assert recorded == [("deepseek_official", "ask")]


def test_conversation_error_event_returns_evidence_and_retry_entry(monkeypatch):
    from app.api.routers import conversations
    from app.main import app

    snapshot = SimpleNamespace(name="deepseek_official")

    def failing_stream(*_args, answer_generator_snapshot=None, **_kwargs):
        assert answer_generator_snapshot is snapshot
        yield {
            "type": "retrieval.completed",
            "response": {
                "citations": [
                    {
                        "id": "chunk-stream",
                        "filename": "stream-evidence.md",
                        "snippet": "流式生成失败前的可用证据。",
                    }
                ],
                "retrieval_trace": {
                    "pipeline": {"decision": {"status": "answered"}}
                },
                "generation_trace": {
                    "answer_provider": "deepseek_official",
                    "answer_model": "deepseek-chat",
                    "status": "pending",
                },
                "confidence": 0.7,
                "diagnostics": [],
            },
        }
        raise RuntimeError("provider failed api_key=private-stream-secret")

    monkeypatch.setattr(
        conversations.rag_engine,
        "snapshot_answer_generator",
        lambda: snapshot,
    )
    monkeypatch.setattr(conversations.rag_engine, "stream", failing_stream)

    with TestClient(app) as client:
        conversation_id = client.post(
            "/api/conversations",
            json={
                "title": "Controlled generation failure",
                "knowledge_base_ids": ["default"],
            },
        ).json()["conversation"]["id"]
        result = client.post(
            f"/api/conversations/{conversation_id}/messages:stream",
            json={"question": "保留检索证据", "query_rewrite": False},
        )
        messages = client.get(
            f"/api/conversations/{conversation_id}/messages"
        ).json()["messages"]

    frames = [
        json.loads(line.removeprefix("data: "))
        for line in result.text.splitlines()
        if line.startswith("data: ")
    ]
    error = next(item for item in frames if item["type"] == "error")
    failed = error["response"]
    expected_endpoint = (
        f"/api/conversations/{conversation_id}/messages:stream"
    )

    assert error["retryable"] is True
    assert error["retry"]["endpoint"] == expected_endpoint
    assert failed["answer"] == ""
    assert failed["citations"][0]["id"] == "chunk-stream"
    assert failed["generation_trace"]["status"] == "failed"
    assert failed["generation_trace"]["retryable"] is True
    assert failed["retry"]["endpoint"] == expected_endpoint
    assert failed["citation_audit"]["checked"] is False
    assert frames[-1]["type"] == "done"
    assert frames[-1]["retryable"] is True
    assert messages[-1]["metadata"]["response"] == failed
    assert "private-stream-secret" not in result.text
    assert "template" not in result.text.lower()
