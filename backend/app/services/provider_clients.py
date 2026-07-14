from __future__ import annotations

import json

import httpx


class OpenAICompatibleChatClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout_seconds: float = 45,
        http_client: httpx.Client | None = None,
    ):
        if not base_url:
            raise ValueError("A chat provider base URL is required")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.http_client = http_client

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def create_text(self, prompt: str) -> str:
        request = {
            "url": f"{self.base_url}/chat/completions",
            "headers": self._headers(),
            "json": {"model": self.model, "messages": [{"role": "user", "content": prompt}], "stream": False},
            "timeout": self.timeout_seconds,
        }
        response = self.http_client.post(**request) if self.http_client is not None else httpx.post(**request)
        response.raise_for_status()
        payload = response.json()
        content = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Chat provider returned no text output")
        return content.strip()

    def stream_text(self, prompt: str):
        request = {
            "url": f"{self.base_url}/chat/completions",
            "headers": {**self._headers(), "Accept": "text/event-stream"},
            "json": {"model": self.model, "messages": [{"role": "user", "content": prompt}], "stream": True},
            "timeout": self.timeout_seconds,
        }
        stream = self.http_client.stream("POST", **request) if self.http_client is not None else httpx.stream("POST", **request)
        with stream as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw:
                    continue
                if raw == "[DONE]":
                    return
                payload = json.loads(raw)
                delta = payload.get("choices", [{}])[0].get("delta", {}).get("content")
                if isinstance(delta, str) and delta:
                    yield delta


class OllamaChatClient:
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

    def create_text(self, prompt: str) -> str:
        request = {
            "url": f"{self.base_url}/api/chat",
            "json": {"model": self.model, "messages": [{"role": "user", "content": prompt}], "stream": False},
            "timeout": self.timeout_seconds,
        }
        response = self.http_client.post(**request) if self.http_client is not None else httpx.post(**request)
        response.raise_for_status()
        text = response.json().get("message", {}).get("content", "")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Ollama returned no text output")
        return text.strip()

    def stream_text(self, prompt: str):
        request = {
            "url": f"{self.base_url}/api/chat",
            "json": {"model": self.model, "messages": [{"role": "user", "content": prompt}], "stream": True},
            "timeout": self.timeout_seconds,
        }
        stream = self.http_client.stream("POST", **request) if self.http_client is not None else httpx.stream("POST", **request)
        with stream as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.strip():
                    continue
                payload = json.loads(line)
                delta = payload.get("message", {}).get("content")
                if isinstance(delta, str) and delta:
                    yield delta
                if payload.get("done"):
                    return
