from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

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


class DeepSeekReranker(BaseReranker):
    """Strict JSON reranker for a DeepSeek/OpenAI-compatible chat client.

    The provider may only score the supplied candidate ids. Any missing, new, or
    duplicated id invalidates the response so the retriever can preserve RRF order.
    """

    name = "deepseek"

    def __init__(self, client: Any, *, max_candidates: int = 16, max_chars_per_candidate: int = 1200):
        if not hasattr(client, "create_json") and not hasattr(client, "create_text"):
            raise TypeError("DeepSeek reranker client must provide create_json or create_text")
        self.client = client
        self.max_candidates = max(1, min(int(max_candidates), 16))
        self.max_chars_per_candidate = max(200, int(max_chars_per_candidate))

    def rerank(self, question: str, candidates: list[dict], top_k: int) -> list[dict]:
        active = candidates[: self.max_candidates]
        if not active:
            return []
        candidate_rows = [
            {
                "candidate_id": item["chunk"].chunk_id,
                "section_path": list(item["chunk"].heading_path),
                "text": item["chunk"].text[: self.max_chars_per_candidate],
            }
            for item in active
        ]
        expected_ids = [row["candidate_id"] for row in candidate_rows]
        if len(set(expected_ids)) != len(expected_ids):
            raise ValueError("rerank candidates must have unique ids")
        prompt = (
            "你是知识库候选片段重排器。只能评分给定候选，不得新增、删除或改写 candidate_id。\n"
            "请为每个候选输出 0 到 1 的相关性分数。只输出 JSON，"
            '格式为 {"scores":[{"candidate_id":"...","score":0.0}]}。\n'
            f"问题：{question}\n"
            f"候选：{json.dumps(candidate_rows, ensure_ascii=False)}"
        )
        if hasattr(self.client, "create_json"):
            payload = self.client.create_json(prompt)
        else:
            payload = self._parse_json(self.client.create_text(prompt))
        scores = self._validated_scores(payload, expected_ids)
        for item in active:
            item["deepseek_score"] = scores[item["chunk"].chunk_id]
            item["rerank_score"] = scores[item["chunk"].chunk_id]
        return sorted(
            active,
            key=lambda row: (-row["rerank_score"], -float(row.get("score", 0.0))),
        )[:top_k]

    @staticmethod
    def _validated_scores(payload: Any, expected_ids: list[str]) -> dict[str, float]:
        if not isinstance(payload, dict) or set(payload) != {"scores"}:
            raise ValueError("reranker output must contain only scores")
        rows = payload.get("scores")
        if not isinstance(rows, list) or len(rows) != len(expected_ids):
            raise ValueError("reranker must score every supplied candidate")
        scores: dict[str, float] = {}
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"candidate_id", "score"}:
                raise ValueError("reranker score row has an invalid shape")
            candidate_id = row.get("candidate_id")
            score = row.get("score")
            if candidate_id not in expected_ids or candidate_id in scores:
                raise ValueError("reranker returned an unknown or duplicate candidate id")
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= float(score) <= 1:
                raise ValueError("reranker score is out of range")
            scores[str(candidate_id)] = float(score)
        if set(scores) != set(expected_ids):
            raise ValueError("reranker candidate ids do not match the request")
        return scores

    @staticmethod
    def _parse_json(text: str) -> dict:
        cleaned = str(text).strip()
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("reranker returned invalid JSON")
            payload = json.loads(cleaned[start : end + 1])
        if not isinstance(payload, dict):
            raise ValueError("reranker returned a non-object")
        return payload
