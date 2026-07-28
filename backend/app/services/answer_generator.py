from __future__ import annotations

import json
from abc import ABC, abstractmethod

from app.services.responses_client import ResponsesClient


MAX_PROMPT_EVIDENCE_CHARS = 12_000
MAX_PROMPT_EVIDENCE_ITEM_CHARS = 2_400
MAX_PROMPT_EVIDENCE_ITEMS = 8


def _bounded_text(value: object, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _generation_trace_summary(trace: dict) -> dict:
    """Keep ranking diagnostics out of the generation context.

    Full retrieval traces can contain every candidate, graph path and score.
    They remain available to the UI and audit log, but sending that payload to
    a local model wastes context and can turn a normal answer into a timeout.
    """

    pipeline = trace.get("pipeline") if isinstance(trace.get("pipeline"), dict) else {}
    graph = pipeline.get("graph") if isinstance(pipeline.get("graph"), dict) else {}
    paths = graph.get("paths") if isinstance(graph.get("paths"), list) else []
    return {
        key: trace.get(key)
        for key in (
            "search_mode",
            "search_profile",
            "strategy",
            "refuse_reason",
        )
        if trace.get(key) not in {None, ""}
    } | {
        "decision": pipeline.get("decision", {}),
        "graph": {
            "status": graph.get("status", "skipped"),
            "reason": graph.get("reason", ""),
            "path_count": len(paths),
        },
    }


class BaseAnswerGenerator(ABC):
    name = "base"

    @abstractmethod
    def generate(self, question: str, citations: list[dict], trace: dict) -> dict:
        raise NotImplementedError

    def stream(self, question: str, citations: list[dict], trace: dict):
        generated = self.generate(question, citations, trace)
        answer = str(generated.get("answer") or "")
        for start in range(0, len(answer), 24):
            yield answer[start : start + 24]


class TemplateAnswerGenerator(BaseAnswerGenerator):
    name = "template"

    def generate(self, question: str, citations: list[dict], trace: dict) -> dict:
        lines = [
            "答案：",
            f"针对“{question}”，当前可检索证据支持以下结论：",
            "",
        ]
        for idx, item in enumerate(citations[:3], start=1):
            snippet = item["text"].replace("\n", " ")
            if len(snippet) > 150:
                snippet = snippet[:150] + "..."
            location = f"第 {item['page_number']} 页" if item.get("page_number") else f"chunk {item['index'] + 1}"
            lines.append(f"{idx}. {snippet} [{item['filename']}, {location}]")
        lines.extend(
            [
                "",
                "依据：",
                *[self._citation_line(item) for item in citations[:3]],
                "",
                "不确定性：",
                "当前回答严格依据检索片段生成；如果证据不足，系统会拒答或提示需要补充资料。",
            ]
        )
        return {
            "answer": "\n".join(lines),
            "generation_trace": {
                "answer_provider": self.name,
                "answer_model": "-",
                "grounded": True,
            },
        }

    def _citation_line(self, item: dict) -> str:
        location = f"第 {item['page_number']} 页" if item.get("page_number") else f"chunk {item['index'] + 1}"
        return f"- {item['filename']}，{location}，相关度 {item['score']:.4f}"


class ResponsesAnswerGenerator(BaseAnswerGenerator):
    name = "responses"

    def __init__(self, client: ResponsesClient):
        self.client = client

    def generate(self, question: str, citations: list[dict], trace: dict) -> dict:
        prompt = self._build_prompt(question, citations, trace)
        answer = self.client.create_text(prompt)
        if not answer:
            answer = "答案：\n无法确定。\n\n依据：\n模型未返回有效文本。\n\n不确定性：\n请检查答案生成 provider。"
        return {
            "answer": answer,
            "generation_trace": {
                "answer_provider": self.name,
                "answer_model": self.client.model,
                "grounded": True,
                "citation_count": len(citations),
            },
        }

    def stream(self, question: str, citations: list[dict], trace: dict):
        yield from self.client.stream_text(self._build_prompt(question, citations, trace))

    def _build_prompt(self, question: str, citations: list[dict], trace: dict) -> str:
        evidence = []
        remaining_characters = MAX_PROMPT_EVIDENCE_CHARS
        for idx, item in enumerate(citations[:MAX_PROMPT_EVIDENCE_ITEMS], start=1):
            parent_context = item.get("parent_context") if isinstance(item.get("parent_context"), dict) else {}
            source_text = parent_context.get("text") or item.get("text") or item.get("snippet") or ""
            text_limit = min(MAX_PROMPT_EVIDENCE_ITEM_CHARS, remaining_characters)
            bounded_source = _bounded_text(source_text, text_limit)
            if not bounded_source:
                continue
            remaining_characters -= len(bounded_source)
            evidence.append(
                {
                    "id": idx,
                    "filename": item["filename"],
                    "chunk": item["index"] + 1,
                    "page_number": item.get("page_number"),
                    "score": item["score"],
                    "text": bounded_source,
                }
            )
            if remaining_characters <= 0:
                break
        trace_summary = _generation_trace_summary(trace)
        return (
            "你是一个严谨的个人知识库 RAG 问答助手。\n"
            "只能根据下面 evidence 中的内容回答，不能使用外部知识补充事实。\n"
            "每个关键结论都必须标注引用编号，例如 [1]。\n"
            "如果 evidence 不足以回答，请明确说“无法确定”，并说明缺少什么资料。\n"
            "输出结构必须包含：答案、依据、不确定性、后续建议。\n\n"
            f"用户问题：{question}\n\n"
            f"检索摘要：{json.dumps(trace_summary, ensure_ascii=False)}\n\n"
            f"evidence：{json.dumps(evidence, ensure_ascii=False, indent=2)}"
        )


class GroundedChatAnswerGenerator(ResponsesAnswerGenerator):
    def __init__(self, client, provider_name: str):
        super().__init__(client)
        self.name = provider_name


class UnavailableAnswerGenerator(BaseAnswerGenerator):
    name = "unavailable"

    def __init__(self, provider_name: str, reason: str):
        self.provider_name = provider_name
        self.reason = reason
        self.name = provider_name

    def generate(self, question: str, citations: list[dict], trace: dict) -> dict:
        raise RuntimeError(self.reason)
