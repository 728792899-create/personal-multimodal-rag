#!/usr/bin/env python3
"""Exercise real Ollama and OpenAI-compatible HTTP contracts without paid APIs."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "host.docker.internal"}


def call(
    base_url: str,
    path: str,
    *,
    payload: dict | None = None,
    api_key: str = "",
    timeout: float = 180,
) -> tuple[int, dict, float]:
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(
        urljoin(base_url.rstrip("/") + "/", path.lstrip("/")),
        data=body,
        method="POST" if payload is not None else "GET",
        headers=headers,
    )
    started = time.monotonic()
    try:
        with urlopen(request, timeout=timeout) as response:
            return (
                response.status,
                json.load(response),
                (time.monotonic() - started) * 1000,
            )
    except HTTPError as exc:
        try:
            error = json.load(exc)
        except (ValueError, OSError):
            error = {"error": type(exc).__name__}
        return exc.code, error, (time.monotonic() - started) * 1000


def validate(
    *,
    base_url: str,
    chat_model: str,
    embedding_model: str,
    api_key: str = "",
) -> dict:
    results: dict[str, dict] = {}

    def record(name: str, path: str, payload: dict | None = None) -> dict:
        try:
            status, response, elapsed = call(
                base_url,
                path,
                payload=payload,
                api_key=api_key,
            )
            item = {
                "passed": status == 200,
                "status": status,
                "latency_ms": round(elapsed, 2),
            }
            results[name] = item
            return response
        except (OSError, URLError, TimeoutError) as exc:
            results[name] = {
                "passed": False,
                "status": 0,
                "latency_ms": 0,
                "error_type": type(exc).__name__,
            }
            return {}

    version = record("ollama.version", "/api/version")
    models = record("ollama.models", "/api/tags")
    native_embedding = record(
        "ollama.embed",
        "/api/embed",
        {"model": embedding_model, "input": "retrieval validation"},
    )
    compatible_models = record("openai_compatible.models", "/v1/models")
    compatible_embedding = record(
        "openai_compatible.embeddings",
        "/v1/embeddings",
        {"model": embedding_model, "input": "retrieval validation"},
    )
    native_chat = record(
        "ollama.chat",
        "/api/chat",
        {
            "model": chat_model,
            "stream": False,
            "messages": [{"role": "user", "content": "Reply with exactly: READY"}],
            "options": {"temperature": 0},
        },
    )
    compatible_chat = record(
        "openai_compatible.chat_completions",
        "/v1/chat/completions",
        {
            "model": chat_model,
            "stream": False,
            "messages": [{"role": "user", "content": "Reply with exactly: READY"}],
            "temperature": 0,
        },
    )
    responses = record(
        "openai_compatible.responses",
        "/v1/responses",
        {
            "model": chat_model,
            "stream": False,
            "store": False,
            "input": "Reply with exactly: READY",
        },
    )
    native_vectors = native_embedding.get("embeddings")
    compatible_data = compatible_embedding.get("data")
    model_items = models.get("models") if isinstance(models.get("models"), list) else []
    results["ollama.embed"]["dimension"] = (
        len(native_vectors[0])
        if isinstance(native_vectors, list)
        and native_vectors
        and isinstance(native_vectors[0], list)
        else 0
    )
    results["openai_compatible.embeddings"]["dimension"] = (
        len(compatible_data[0].get("embedding", []))
        if isinstance(compatible_data, list)
        and compatible_data
        and isinstance(compatible_data[0], dict)
        else 0
    )
    return {
        "schema_version": 1,
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "endpoint_host": urlparse(base_url).hostname,
        "endpoint_is_local": urlparse(base_url).hostname in LOCAL_HOSTS,
        "ollama_version": str(version.get("version") or ""),
        "available_models": sorted(
            str(item.get("name") or item.get("model") or "")
            for item in model_items
            if isinstance(item, dict)
        ),
        "configured_models": {
            "chat": chat_model,
            "embedding": embedding_model,
        },
        "results": results,
        "passed": all(item.get("passed") is True for item in results.values()),
        "response_content_recorded": False,
        "credential_recorded": False,
        "contract_notes": {
            "native_chat_response_present": bool(
                native_chat.get("message", {}).get("content")
                if isinstance(native_chat.get("message"), dict)
                else False
            ),
            "compatible_chat_response_present": bool(
                compatible_chat.get("choices")
            ),
            "responses_output_present": bool(
                responses.get("output") or responses.get("output_text")
            ),
            "compatible_model_list_present": bool(
                compatible_models.get("data")
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate external provider contracts")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--chat-model", default="qwen3:8b")
    parser.add_argument("--embedding-model", default="nomic-embed-text")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/validation/external-providers.json"),
    )
    parser.add_argument("--allow-remote", action="store_true")
    args = parser.parse_args()
    host = urlparse(args.base_url).hostname
    if host not in LOCAL_HOSTS and not args.allow_remote:
        raise SystemExit("remote provider validation requires --allow-remote")
    report = validate(
        base_url=args.base_url,
        chat_model=args.chat_model,
        embedding_model=args.embedding_model,
        api_key=os.getenv("EXTERNAL_PROVIDER_API_KEY", ""),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
