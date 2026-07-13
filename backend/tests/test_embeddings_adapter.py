from types import SimpleNamespace

import pytest

from app.services.embeddings import OpenAICompatibleEmbeddingProvider


class FakeEmbeddings:
    def __init__(self):
        self.calls = []

    def create(self, **payload):
        self.calls.append(payload)
        rows = [
            SimpleNamespace(index=index, embedding=[float(index), 1.0])
            for index, _ in reversed(list(enumerate(payload["input"])))
        ]
        return SimpleNamespace(data=rows)


def provider_without_sdk_init() -> OpenAICompatibleEmbeddingProvider:
    provider = OpenAICompatibleEmbeddingProvider.__new__(OpenAICompatibleEmbeddingProvider)
    provider.client = SimpleNamespace(embeddings=FakeEmbeddings())
    provider.model = "text-embedding-3-small"
    provider.dimensions = 256
    provider.batch_size = 2
    return provider


def test_embedding_adapter_requests_float_encoding_and_preserves_input_order():
    provider = provider_without_sdk_init()

    result = provider.embed_batch(["first", "second", "third"])

    assert result == [[0.0, 1.0], [1.0, 1.0], [0.0, 1.0]]
    assert provider.client.embeddings.calls[0] == {
        "model": "text-embedding-3-small",
        "input": ["first", "second"],
        "encoding_format": "float",
        "dimensions": 256,
    }


@pytest.mark.parametrize("texts", [[], [""], ["valid", "  "]])
def test_embedding_adapter_rejects_empty_inputs_before_network(texts):
    provider = provider_without_sdk_init()

    with pytest.raises(ValueError, match="empty"):
        provider.embed_batch(texts)

    assert provider.client.embeddings.calls == []
