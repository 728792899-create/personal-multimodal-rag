from __future__ import annotations

import hashlib
import math
from abc import ABC, abstractmethod
from typing import Optional

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
        api_key: str,
        model: str = "text-embedding-3-small",
        base_url: Optional[str] = None,
        dimensions: Optional[int] = None,
        batch_size: int = 64,
    ):
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
        self.batch_size = batch_size

    def embed_text(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            payload = {"model": self.model, "input": batch}
            if self.dimensions:
                payload["dimensions"] = self.dimensions
            response = self.client.embeddings.create(**payload)
            ordered = sorted(response.data, key=lambda item: item.index)
            embeddings.extend([list(item.embedding) for item in ordered])
        return embeddings


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
