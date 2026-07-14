from __future__ import annotations

import json

import httpx

from app.services.embeddings import OllamaEmbeddingProvider
from app.services.provider_clients import OllamaChatClient, OpenAICompatibleChatClient


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


def test_ollama_chat_and_embedding_adapters_use_local_contracts():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        if request.url.path == "/api/embed":
            assert payload["input"] == ["one", "two"]
            return httpx.Response(200, json={"embeddings": [[1.0, 0.0], [0.0, 1.0]]})
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
    assert embeddings.embed_batch(["one", "two"]) == [[1.0, 0.0], [0.0, 1.0]]
