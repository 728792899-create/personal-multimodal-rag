from __future__ import annotations

import json

import httpx


def _parse_json_object(text: str, provider: str) -> dict:
    cleaned = text.strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError(f"{provider} returned invalid structured JSON")
        try:
            payload = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"{provider} returned invalid structured JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{provider} returned a non-object structured response")
    return payload


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


class OpenAICompatibleVisionClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout_seconds: float = 45,
        http_client: httpx.Client | None = None,
    ):
        if not base_url:
            raise ValueError("A vision provider base URL is required")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.http_client = http_client

    def create_structured(self, prompt: str, *, schema: dict, image_data_url: str = "", image_detail: str = "auto") -> dict:
        content: list[dict] = [{"type": "text", "text": prompt}]
        if image_data_url:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": image_data_url,
                        "detail": image_detail if image_detail in {"low", "high", "auto"} else "auto",
                    },
                }
            )
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = {
            "url": f"{self.base_url}/chat/completions",
            "headers": headers,
            "json": {
                "model": self.model,
                "messages": [{"role": "user", "content": content}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "multimodal_enrichment", "strict": True, "schema": schema},
                },
                "stream": False,
            },
            "timeout": self.timeout_seconds,
        }
        response = self.http_client.post(**request) if self.http_client is not None else httpx.post(**request)
        response.raise_for_status()
        content_text = response.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        if not isinstance(content_text, str):
            raise ValueError("Compatible vision provider returned no structured output")
        return _parse_json_object(content_text, "Compatible vision provider")


class OllamaVisionClient:
    def __init__(self, base_url: str, model: str, timeout_seconds: float = 45, http_client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.http_client = http_client

    def create_structured(self, prompt: str, *, schema: dict, image_data_url: str = "", image_detail: str = "auto") -> dict:
        images: list[str] = []
        if image_data_url:
            images.append(image_data_url.split(",", 1)[1] if "," in image_data_url else image_data_url)
        message = {"role": "user", "content": prompt}
        if images:
            message["images"] = images
        request = {
            "url": f"{self.base_url}/api/chat",
            "json": {
                "model": self.model,
                "messages": [message],
                "format": schema,
                "stream": False,
            },
            "timeout": self.timeout_seconds,
        }
        response = self.http_client.post(**request) if self.http_client is not None else httpx.post(**request)
        response.raise_for_status()
        content_text = response.json().get("message", {}).get("content", "")
        if not isinstance(content_text, str):
            raise ValueError("Ollama vision returned no structured output")
        return _parse_json_object(content_text, "Ollama vision")
