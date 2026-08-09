from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from app.services.responses_client import ResponsesClient


class BaseQueryRewriter(ABC):
    name = "base"

    @abstractmethod
    def rewrite(self, question: str) -> list[str]:
        raise NotImplementedError


class NoopQueryRewriter(BaseQueryRewriter):
    name = "none"

    def rewrite(self, question: str) -> list[str]:
        return [question]


class ResponsesQueryRewriter(BaseQueryRewriter):
    name = "responses"

    def __init__(self, client: ResponsesClient, rewrite_count: int = 2):
        self.client = client
        self.rewrite_count = rewrite_count

    def rewrite(self, question: str) -> list[str]:
        prompt = (
            "请把用户问题改写成适合知识库检索的查询语句。\n"
            "要求：\n"
            "1. 保留原始问题的核心意图。\n"
            "2. 输出 JSON，格式为 {\"queries\": [\"...\"]}。\n"
            f"3. 最多输出 {self.rewrite_count} 条改写查询。\n"
            "4. 不要解释。\n\n"
            f"用户问题：{question}"
        )
        try:
            payload = self.client.create_json(prompt)
        except Exception:
            return [question]
        queries = payload.get("queries", []) if isinstance(payload, dict) else []
        deduped = [question]
        for item in queries:
            if isinstance(item, str):
                cleaned = item.strip()
                if cleaned and cleaned not in deduped:
                    deduped.append(cleaned)
            if len(deduped) >= self.rewrite_count + 1:
                break
        return deduped


class StructuredQueryRewriter(BaseQueryRewriter):
    """Strict JSON query rewriter for create_json/create_text cloud clients."""

    name = "structured"

    def __init__(self, client: Any, rewrite_count: int = 2):
        if not hasattr(client, "create_json") and not hasattr(client, "create_text"):
            raise TypeError("Structured rewriter client must provide create_json or create_text")
        self.client = client
        self.rewrite_count = max(1, min(int(rewrite_count), 2))

    def rewrite(self, question: str) -> list[str]:
        prompt = (
            "你是知识库检索查询改写器。只输出 JSON 对象，不要解释。\n"
            "保留原始意图和所有实体、编号、日期与范围限制；不得新增事实。\n"
            f"最多输出 {self.rewrite_count} 个变体，格式为 "
            '{"queries":["..."]}。\n'
            f"原问：{question}"
        )
        if hasattr(self.client, "create_json"):
            payload = self.client.create_json(prompt)
        else:
            payload = self._parse_json(self.client.create_text(prompt))
        if not isinstance(payload, dict) or set(payload) != {"queries"}:
            raise ValueError("query rewriter output must contain only queries")
        queries = payload.get("queries")
        if not isinstance(queries, list) or len(queries) > self.rewrite_count:
            raise ValueError("query rewriter returned an invalid query list")
        deduped = [question]
        for item in queries:
            if not isinstance(item, str):
                raise ValueError("query rewrite must be text")
            cleaned = item.strip()
            if not cleaned or len(cleaned) > 500:
                raise ValueError("query rewrite length is invalid")
            if cleaned not in deduped:
                deduped.append(cleaned)
        return deduped

    @staticmethod
    def _parse_json(text: str) -> dict:
        cleaned = str(text).strip()
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("query rewriter returned invalid JSON")
            payload = json.loads(cleaned[start : end + 1])
        if not isinstance(payload, dict):
            raise ValueError("query rewriter returned a non-object")
        return payload


class DeepSeekQueryRewriter(StructuredQueryRewriter):
    name = "deepseek"
