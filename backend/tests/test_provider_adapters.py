from __future__ import annotations

import json

import httpx
import pytest

from app.services.embeddings import OllamaEmbeddingProvider
from app.services.answer_generator import (
    MAX_PROMPT_EVIDENCE_CHARS,
    ResponsesAnswerGenerator,
)
from app.services.provider_clients import (
    OllamaChatClient,
    OpenAICompatibleChatClient,
    ProviderResponseError,
)


def test_generation_prompt_is_bounded_and_does_not_embed_full_debug_trace():
    class FakeClient:
        model = "test-model"

    generator = ResponsesAnswerGenerator(FakeClient())
    citations = [
        {
            "filename": f"source-{index}.md",
            "index": index,
            "page_number": index + 1,
            "score": 0.9,
            "text": "正文" * 8_000,
            "parent_context": {"text": "父级证据" * 8_000},
        }
        for index in range(12)
    ]
    prompt = generator._build_prompt(
        "请根据证据回答。",
        citations,
        {
            "search_mode": "hybrid",
            "pipeline": {
                "decision": {"status": "answered"},
                "candidates": [{"private_debug_blob": "不应进入生成上下文" * 10_000}],
            },
        },
    )

    assert "不应进入生成上下文" not in prompt
    assert prompt.count('"filename"') == 10
    assert "source-9.md" in prompt
    assert "source-10.md" not in prompt
    assert len(prompt) < MAX_PROMPT_EVIDENCE_CHARS + 4_000
    assert "父级证据" in prompt


def test_openai_compatible_chat_supports_json_and_sse_without_leaking_protocol_frames():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        calls.append(payload)
        if payload.get("stream"):
            return httpx.Response(
                200,
                text=(
                    'data: {"choices":[{"delta":{"content":"local "}}]}\n\n'
                    'data: {"choices":[{"delta":{"content":"answer"}}]}\n\n'
                    "data: [DONE]\n\n"
                ),
            )
        return httpx.Response(200, json={"choices": [{"message": {"content": "local answer"}}]})

    client = OpenAICompatibleChatClient(
        base_url="https://provider.test/v1",
        model="local-model",
        api_key="test-token",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert client.create_text("grounded prompt") == "local answer"
    assert list(client.stream_text("grounded prompt")) == ["local ", "answer"]
    assert calls[1]["stream"] is True


def test_openai_compatible_chat_can_disable_thinking_and_limit_output():
    payloads = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.read()))
        if payloads[-1]["stream"]:
            return httpx.Response(
                200,
                text=(
                    'data: {"choices":[{"delta":{"content":"证据回答"},"finish_reason":"stop"}]}\n\n'
                    "data: [DONE]\n\n"
                ),
            )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "证据回答"}}]},
        )

    client = OpenAICompatibleChatClient(
        "https://api.deepseek.example",
        "deepseek-v4-flash",
        api_key="test-key",
        thinking_mode="disabled",
        max_tokens=512,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert client.create_text("prompt") == "证据回答"
    assert list(client.stream_text("prompt")) == ["证据回答"]
    assert [payload["thinking"] for payload in payloads] == [
        {"type": "disabled"},
        {"type": "disabled"},
    ]
    assert [payload["max_tokens"] for payload in payloads] == [512, 512]


def test_openai_compatible_chat_structured_calls_use_json_mode_and_zero_temperature():
    payloads = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.read()))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"route":"semantic"}'}}]},
        )

    client = OpenAICompatibleChatClient(
        "https://api.deepseek.example",
        "deepseek-planner",
        api_key="test-key",
        temperature=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert client.create_json("route this query") == {"route": "semantic"}
    assert payloads[0]["temperature"] == 0
    assert payloads[0]["response_format"] == {"type": "json_object"}


def test_openai_compatible_chat_rejects_partial_stream_without_terminal_event():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"partial answer"}}]}\n\n',
            headers={"content-type": "text/event-stream"},
        )

    client = OpenAICompatibleChatClient(
        base_url="https://provider.test/v1",
        model="local-model",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    stream = client.stream_text("grounded prompt")
    assert next(stream) == "partial answer"
    with pytest.raises(ProviderResponseError, match="terminal event"):
        next(stream)


def test_ollama_chat_and_embedding_adapters_use_local_contracts():
    chat_payloads = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        if request.url.path == "/api/embed":
            assert payload["input"] == ["one", "two"]
            return httpx.Response(200, json={"embeddings": [[1.0, 0.0], [0.0, 1.0]]})
        chat_payloads.append(payload)
        if payload.get("stream"):
            return httpx.Response(
                200,
                text='{"message":{"content":"local "},"done":false}\n{"message":{"content":"rag"},"done":true}\n',
            )
        return httpx.Response(200, json={"message": {"content": "local rag"}})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    chat = OllamaChatClient("http://ollama.test", "qwen", http_client=http_client)
    embeddings = OllamaEmbeddingProvider("http://ollama.test", "nomic", http_client=http_client)

    assert chat.create_text("prompt") == "local rag"
    assert list(chat.stream_text("prompt")) == ["local ", "rag"]
    assert [payload["think"] for payload in chat_payloads] == [False, False]
    assert [payload["options"] for payload in chat_payloads] == [
        {"num_ctx": 4096, "num_predict": 256},
        {"num_ctx": 4096, "num_predict": 256},
    ]
    assert embeddings.embed_batch(["one", "two"]) == [[1.0, 0.0], [0.0, 1.0]]


def test_ollama_chat_rejects_a_thinking_only_stream_without_answer_text():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=(
                '{"message":{"thinking":"checking evidence"},"done":false}\n'
                '{"message":{"content":""},"done":true,"done_reason":"stop"}\n'
            ),
        )

    client = OllamaChatClient(
        "http://ollama.test",
        "qwen3:8b",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(ValueError, match="no text output"):
        list(client.stream_text("grounded prompt"))
