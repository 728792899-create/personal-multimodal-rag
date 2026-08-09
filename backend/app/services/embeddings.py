from __future__ import annotations

import hashlib
import math
import httpx
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from app.models.domain import Chunk
from app.services.text_utils import tokenize


class BaseEmbeddingProvider(ABC):
    @abstractmethod
    def embed_text(self, text: str) -> list[float]:
        raise NotImplementedError

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class MockEmbeddingProvider(BaseEmbeddingProvider):
    """Stable local embedding for tests and offline demos."""

    def __init__(self, vector_dim: int = 256):
        self.vector_dim = vector_dim

    def embed_text(self, text: str) -> list[float]:
        tokens = tokenize(text)
        vec = [0.0] * self.vector_dim
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % self.vector_dim
            sign = 1 if digest[4] % 2 == 0 else -1
            vec[idx] += sign
        norm = math.sqrt(sum(value * value for value in vec))
        return [value / norm for value in vec] if norm else vec

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(text) for text in texts]


class OpenAICompatibleEmbeddingProvider(BaseEmbeddingProvider):
    """OpenAI-compatible embedding provider.

    Works with OpenAI and other services exposing the OpenAI embeddings API.
    """

    def __init__(
        self,
        api_key: str = "",
        model: str = "text-embedding-3-large",
        base_url: Optional[str] = None,
        dimensions: Optional[int] = 1536,
        batch_size: int = 64,
        api_key_file: str | Path | None = None,
    ):
        api_key = _secret_value(api_key, api_key_file)
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required when EMBEDDING_PROVIDER=openai")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Install openai to use OpenAICompatibleEmbeddingProvider") from exc

        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = OpenAI(**kwargs)
        self.model = model
        self.dimensions = dimensions
        self.batch_size = max(1, min(int(batch_size), 2048))
        self.input_tokens_used = 0

    def embed_text(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts or any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("Embedding input cannot be empty")
        embeddings: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            payload = {"model": self.model, "input": batch, "encoding_format": "float"}
            if self.dimensions:
                payload["dimensions"] = self.dimensions
            response = self.client.embeddings.create(**payload)
            ordered = sorted(response.data, key=lambda item: item.index)
            embeddings.extend([list(item.embedding) for item in ordered])
            usage = getattr(response, "usage", None)
            self.input_tokens_used = getattr(self, "input_tokens_used", 0) + int(
                getattr(usage, "prompt_tokens", 0)
                or getattr(usage, "total_tokens", 0)
                or 0
            )
        return embeddings


def _secret_value(value: str, file_path: str | Path | None) -> str:
    if value:
        return value
    if not file_path:
        return ""
    try:
        return Path(file_path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError("Unable to read OPENAI_API_KEY_FILE") from exc


def embedding_text_for_chunk(chunk: Chunk) -> str:
    """Return retrieval-only text without changing citation-visible text."""

    value = str(chunk.metadata.get("embedding_text") or "").strip()
    return value or chunk.text


class LocalSentenceTransformerEmbeddingProvider(BaseEmbeddingProvider):
    """Local embedding provider backed by sentence-transformers."""

    def __init__(self, model_name: str, normalize: bool = True):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "Install sentence-transformers to use LocalSentenceTransformerEmbeddingProvider"
            ) from exc
        self.model_name = model_name
        self.normalize = normalize
        self.model = SentenceTransformer(model_name)

    def embed_text(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        embeddings = self.model.encode(
            texts,
            normalize_embeddings=self.normalize,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [row.astype(float).tolist() for row in embeddings]


class OllamaEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: float = 45,
        http_client: httpx.Client | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.http_client = http_client

    def embed_text(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts or any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("Embedding input cannot be empty")
        request = {
            "url": f"{self.base_url}/api/embed",
            "json": {"model": self.model, "input": texts},
            "timeout": self.timeout_seconds,
        }
        response = self.http_client.post(**request) if self.http_client is not None else httpx.post(**request)
        response.raise_for_status()
        embeddings = response.json().get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise ValueError("Ollama returned an invalid embeddings payload")
        return [[float(value) for value in row] for row in embeddings]
