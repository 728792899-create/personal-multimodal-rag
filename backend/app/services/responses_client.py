from __future__ import annotations

import json
from typing import Any

import httpx


class ResponsesClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float = 45,
    ):
        if not api_key:
            raise ValueError("Responses API key is required")
        if not base_url:
            raise ValueError("Responses base_url is required")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def create_text(self, prompt: str) -> str:
        payload = {"model": self.model, "input": prompt}
        response = httpx.post(
            f"{self.base_url}/responses",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return self._extract_text(response.json()).strip()

    def create_json(self, prompt: str) -> Any:
        text = self.create_text(prompt)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                return json.loads(text[start : end + 1])
            raise

    def _extract_text(self, payload: dict) -> str:
        if isinstance(payload.get("output_text"), str):
            return payload["output_text"]
        fragments: list[str] = []
        for output in payload.get("output", []) or []:
            for content in output.get("content", []) or []:
                if isinstance(content.get("text"), str):
                    fragments.append(content["text"])
        if fragments:
            return "\n".join(fragments)
        if isinstance(payload.get("text"), str):
            return payload["text"]
        return ""
