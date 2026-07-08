from __future__ import annotations

from abc import ABC, abstractmethod

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
