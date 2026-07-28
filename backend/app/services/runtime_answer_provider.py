from __future__ import annotations

from copy import deepcopy
from threading import Lock, RLock

import httpx

from app.services.answer_generator import GroundedChatAnswerGenerator
from app.services.provider_clients import OpenAICompatibleChatClient


DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-v4-flash"


class RuntimeAnswerProviderError(RuntimeError):
    """Base class for safe, application-owned runtime provider failures."""


class RuntimeAnswerProviderConfigurationError(RuntimeAnswerProviderError):
    """Raised before I/O when a runtime provider is outside the allowlist."""


class RuntimeAnswerProviderValidationError(RuntimeAnswerProviderError):
    """Raised when the allowlisted provider cannot validate a credential."""


class RuntimeAnswerProviderManager:
    """Atomically install an in-memory answer provider after a minimal probe.

    The manager deliberately has no registry or filesystem dependency. The
    active credential lives only inside the provider client referenced by the
    current process and is discarded when the override is cleared or the
    process exits.
    """

    def __init__(
        self,
        rag_engine,
        *,
        timeout_seconds: float = 45,
        max_tokens: int = 0,
        client_factory=OpenAICompatibleChatClient,
        probe_client: httpx.Client | None = None,
    ):
        self._rag_engine = rag_engine
        self._startup_generator = rag_engine.answer_generator
        self._timeout_seconds = max(1.0, float(timeout_seconds))
        self._max_tokens = max(0, int(max_tokens))
        self._client_factory = client_factory
        self._probe_client = probe_client
        self._state_lock = RLock()
        self._operation_lock = Lock()
        self._active_status: dict | None = None

    def connect_deepseek(
        self,
        *,
        api_key: str,
        base_url: str = DEEPSEEK_BASE_URL,
        model: str = DEEPSEEK_MODEL,
    ) -> dict:
        normalized_url = str(base_url or "").strip().rstrip("/")
        normalized_model = str(model or "").strip()
        credential = str(api_key or "").strip()
        if normalized_url != DEEPSEEK_BASE_URL:
            raise RuntimeAnswerProviderConfigurationError(
                "仅允许连接 DeepSeek 官方 API 地址。"
            )
        if normalized_model != DEEPSEEK_MODEL:
            raise RuntimeAnswerProviderConfigurationError(
                "仅允许使用 deepseek-v4-flash 模型。"
            )
        if len(credential) < 8 or len(credential) > 512:
            raise RuntimeAnswerProviderConfigurationError(
                "DeepSeek API Key 格式无效。"
            )

        with self._operation_lock:
            try:
                self._probe_deepseek(credential)
            except Exception:
                raise RuntimeAnswerProviderValidationError(
                    "无法验证 DeepSeek 凭据或服务可用性，请检查后重试。"
                ) from None

            active_client = self._new_client(
                api_key=credential,
                max_tokens=self._max_tokens,
                timeout_seconds=self._timeout_seconds,
            )
            generator = GroundedChatAnswerGenerator(
                active_client,
                "deepseek_official",
            )
            status = {
                "provider": "deepseek_official",
                "configured": True,
                "health": "ready",
                "mode": "external",
                "capabilities": ["answer", "stream"],
                "model": DEEPSEEK_MODEL,
                "base_url": DEEPSEEK_BASE_URL,
                "runtime_override": True,
                "credential_state": "configured",
                "connected": True,
                "active": True,
                "temporary": True,
                "status": "ready",
                "health_basis": "validated_on_connect",
                "live_probe": "not_run_by_readiness",
            }
            with self._state_lock:
                self._rag_engine.answer_generator = generator
                self._active_status = status
                return deepcopy(status)

    def clear(self) -> bool:
        with self._operation_lock:
            with self._state_lock:
                was_active = self._active_status is not None
                self._rag_engine.answer_generator = self._startup_generator
                self._active_status = None
                return was_active

    def status(self) -> dict | None:
        with self._state_lock:
            return (
                deepcopy(self._active_status)
                if self._active_status is not None
                else None
            )

    def _new_client(
        self,
        *,
        api_key: str,
        max_tokens: int,
        timeout_seconds: float,
    ):
        return self._client_factory(
            base_url=DEEPSEEK_BASE_URL,
            model=DEEPSEEK_MODEL,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            thinking_mode="disabled",
            max_tokens=max_tokens,
        )

    def _probe_deepseek(self, api_key: str) -> None:
        request = {
            "url": f"{DEEPSEEK_BASE_URL}/models",
            "headers": {
                "Accept": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            "timeout": min(self._timeout_seconds, 15.0),
            "follow_redirects": False,
        }
        response = (
            self._probe_client.get(**request)
            if self._probe_client is not None
            else httpx.get(**request)
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("invalid model list")
        models = payload.get("data")
        if payload.get("object") != "list" or not isinstance(models, list):
            raise ValueError("invalid model list")
        if not any(
            isinstance(item, dict)
            and item.get("id") == DEEPSEEK_MODEL
            for item in models
        ):
            raise ValueError("required model unavailable")
