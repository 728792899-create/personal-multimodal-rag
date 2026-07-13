from __future__ import annotations

import json
from typing import Any

import httpx


class ResponsesClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "",
        timeout_seconds: float = 45,
        http_client: httpx.Client | None = None,
    ):
        if not api_key:
            raise ValueError("Responses API key is required")
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.timeout_seconds = timeout_seconds
        # Build the default client lazily so provider selection remains offline
        # and does not fail merely because a host proxy runtime is incomplete.
        self.http_client = http_client

    def create_text(self, prompt: str) -> str:
        payload = {"model": self.model, "input": prompt}
        request = {
            "url": f"{self.base_url}/responses",
            "headers": {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            "json": payload,
            "timeout": self.timeout_seconds,
        }
        if self.http_client is not None:
            response = self.http_client.post(**request)
        else:
            response = httpx.post(**request)
        response.raise_for_status()
        text = self._extract_text(response.json()).strip()
        if not text:
            raise ValueError("Responses API returned no text output")
        return text

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
                if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                    fragments.append(content["text"])
        if fragments:
            return "\n".join(fragments)
        if isinstance(payload.get("text"), str):
            return payload["text"]
        return ""
