from __future__ import annotations

from abc import ABC, abstractmethod

from app.services.text_utils import retrieval_tokens, tokenize


class BaseReranker(ABC):
    name = "base"

    @abstractmethod
    def rerank(self, question: str, candidates: list[dict], top_k: int) -> list[dict]:
        raise NotImplementedError


class NoopReranker(BaseReranker):
    name = "none"

    def rerank(self, question: str, candidates: list[dict], top_k: int) -> list[dict]:
        for item in candidates:
            item["rerank_score"] = item["score"]
        return candidates[:top_k]


class KeywordReranker(BaseReranker):
    name = "keyword"

    def rerank(self, question: str, candidates: list[dict], top_k: int) -> list[dict]:
        query_tokens = set(retrieval_tokens(question))
        reranked = []
        for item in candidates:
            chunk = item["chunk"]
            chunk_tokens = set(tokenize(chunk.text))
            overlap = len(query_tokens & chunk_tokens)
            coverage = overlap / max(len(query_tokens), 1)
            phrase_bonus = 0.12 if question.strip() and question.strip() in chunk.text else 0
            heading_bonus = 0.05 if any(token in " ".join(chunk.heading_path).lower() for token in query_tokens) else 0
            rerank_score = 0.72 * item["score"] + 0.2 * coverage + phrase_bonus + heading_bonus
            item["rerank_score"] = rerank_score
            reranked.append(item)
        return sorted(reranked, key=lambda row: row["rerank_score"], reverse=True)[:top_k]


class CrossEncoderReranker(BaseReranker):
    name = "cross-encoder"

    def __init__(self, model_name: str):
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RuntimeError("Install sentence-transformers to use CrossEncoderReranker") from exc
        self.model_name = model_name
        self.model = CrossEncoder(model_name)

    def rerank(self, question: str, candidates: list[dict], top_k: int) -> list[dict]:
        if not candidates:
            return []
        pairs = [(question, item["chunk"].text) for item in candidates]
        scores = self.model.predict(pairs)
        for item, score in zip(candidates, scores):
            item["cross_encoder_score"] = float(score)
            item["rerank_score"] = 0.55 * float(score) + 0.45 * item["score"]
        return sorted(candidates, key=lambda row: row["rerank_score"], reverse=True)[:top_k]
