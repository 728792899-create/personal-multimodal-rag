from __future__ import annotations

import json
import time

import httpx


class ProviderResponseError(ValueError):
    """Raised when a provider returns a malformed or incomplete response."""


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
        thinking_mode: str = "",
        max_tokens: int = 0,
        http_client: httpx.Client | None = None,
    ):
        if not base_url:
            raise ValueError("A chat provider base URL is required")
        normalized_thinking = thinking_mode.strip().lower()
        if normalized_thinking not in {"", "enabled", "disabled"}:
            raise ValueError("Chat provider thinking mode must be enabled, disabled, or empty")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.thinking_mode = normalized_thinking
        self.max_tokens = max(0, int(max_tokens))
        self.http_client = http_client

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _payload(self, prompt: str, *, stream: bool) -> dict:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": stream,
        }
        if self.thinking_mode:
            payload["thinking"] = {"type": self.thinking_mode}
        if self.max_tokens > 0:
            payload["max_tokens"] = self.max_tokens
        return payload

    def create_text(self, prompt: str) -> str:
        request = {
            "url": f"{self.base_url}/chat/completions",
            "headers": self._headers(),
            "json": self._payload(prompt, stream=False),
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
            "json": self._payload(prompt, stream=True),
            "timeout": self.timeout_seconds,
        }
        stream = self.http_client.stream("POST", **request) if self.http_client is not None else httpx.stream("POST", **request)
        completed = False
        with stream as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw:
                    continue
                if raw == "[DONE]":
                    completed = True
                    break
                payload = json.loads(raw)
                if payload.get("error"):
                    raise ProviderResponseError("Chat provider stream reported an error")
                choices = payload.get("choices") or []
                choice = choices[0] if choices and isinstance(choices[0], dict) else {}
                delta = choice.get("delta", {}).get("content")
                if isinstance(delta, str) and delta:
                    yield delta
                if choice.get("finish_reason") is not None:
                    completed = True
                    break
        if not completed:
            raise ProviderResponseError("Chat provider stream ended without a terminal event")


class OllamaChatClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: float = 45,
        think: bool = False,
        num_ctx: int = 4096,
        num_predict: int = 256,
        http_client: httpx.Client | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.think = bool(think)
        self.num_ctx = max(512, int(num_ctx))
        self.num_predict = max(1, int(num_predict))
        self.http_client = http_client

    def _payload(self, prompt: str, *, stream: bool) -> dict:
        return {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": stream,
            "think": self.think,
            "options": {
                "num_ctx": self.num_ctx,
                "num_predict": self.num_predict,
            },
        }

    def create_text(self, prompt: str) -> str:
        request = {
            "url": f"{self.base_url}/api/chat",
            "json": self._payload(prompt, stream=False),
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
            "json": self._payload(prompt, stream=True),
            "timeout": self.timeout_seconds,
        }
        stream = self.http_client.stream("POST", **request) if self.http_client is not None else httpx.stream("POST", **request)
        started = time.monotonic()
        received_text = False
        completed = False
        with stream as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if time.monotonic() - started > self.timeout_seconds:
                    raise TimeoutError("Ollama answer stream exceeded its total timeout")
                if not line.strip():
                    continue
                payload = json.loads(line)
                if payload.get("error"):
                    raise ValueError("Ollama answer stream failed")
                delta = payload.get("message", {}).get("content")
                if isinstance(delta, str) and delta:
                    received_text = True
                    yield delta
                if payload.get("done"):
                    completed = True
                    break
        if not completed:
            raise ValueError("Ollama answer stream ended before completion")
        if not received_text:
            raise ValueError("Ollama returned no text output")


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
