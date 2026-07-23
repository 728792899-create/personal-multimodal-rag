from __future__ import annotations

import hmac
import json
import re
import threading
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from app.services.auth import AuthService


_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_PUBLIC_AUTH_PATHS = {"/api/auth/login", "/api/auth/session"}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class RequestGuardMiddleware:
    """Optional bearer auth, bounded in-memory rate limiting, and request IDs.

    The limiter is deliberately process-local for the local/single-instance Beta.
    Production replicas should use the documented shared Redis adapter.
    """

    def __init__(
        self,
        app,
        *,
        auth_token: str = "",
        auth_service: AuthService | None = None,
        rate_limit_requests: int = 120,
        rate_limit_window_seconds: int = 60,
        login_rate_limit_requests: int = 8,
        login_rate_limit_window_seconds: int = 300,
    ):
        self.app = app
        self.auth_token = auth_token
        self.auth_service = auth_service
        self.rate_limit_requests = max(0, int(rate_limit_requests))
        self.rate_limit_window_seconds = max(1, int(rate_limit_window_seconds))
        self.login_rate_limit_requests = max(0, int(login_rate_limit_requests))
        self.login_rate_limit_window_seconds = max(1, int(login_rate_limit_window_seconds))
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._login_requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    async def __call__(self, scope, receive: Callable[[], Awaitable[dict]], send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        supplied_request_id = headers.get(b"x-request-id", b"").decode("latin-1")
        request_id = supplied_request_id if _REQUEST_ID.fullmatch(supplied_request_id) else uuid.uuid4().hex
        path = scope.get("path", "")
        method = scope.get("method", "GET").upper()
        identity = None
        if self.auth_service:
            cookie_header = headers.get(b"cookie", b"").decode("latin-1")
            identity = self.auth_service.resolve_cookie_header(cookie_header)
            scope.setdefault("state", {})["identity"] = identity

        if path.startswith("/api/") and method != "OPTIONS":
            if path == "/api/auth/login" and method == "POST":
                login_retry_after = self._retry_after_bucket(
                    scope,
                    self._login_requests,
                    self.login_rate_limit_requests,
                    self.login_rate_limit_window_seconds,
                )
                if login_retry_after is not None:
                    await self._json_response(
                        send,
                        429,
                        "Too many login attempts",
                        request_id,
                        extra_headers=[(b"retry-after", str(login_retry_after).encode("ascii"))],
                    )
                    return
            retry_after = self._retry_after(scope)
            if retry_after is not None:
                await self._json_response(
                    send,
                    429,
                    "Rate limit exceeded",
                    request_id,
                    extra_headers=[(b"retry-after", str(retry_after).encode("ascii"))],
                )
                return
            bearer_authorized = self.auth_token and self._authorized(
                headers.get(b"authorization", b"")
            )
            if path not in _PUBLIC_AUTH_PATHS:
                if self.auth_service and not (identity or bearer_authorized):
                    await self._json_response(send, 401, "Authentication required", request_id)
                    return
                if not self.auth_service and self.auth_token and not bearer_authorized:
                    await self._json_response(send, 401, "Authentication required", request_id)
                    return
                if (
                    identity
                    and method not in _SAFE_METHODS
                    and not self.auth_service.verify_csrf(
                        identity,
                        headers.get(b"x-csrf-token", b"").decode("latin-1"),
                    )
                ):
                    await self._json_response(send, 403, "CSRF token required", request_id)
                    return

        async def send_with_request_id(message: dict):
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": response_headers}
            await send(message)

        await self.app(scope, receive, send_with_request_id)

    def _authorized(self, authorization: bytes) -> bool:
        supplied = authorization.decode("latin-1")
        expected = f"Bearer {self.auth_token}"
        return hmac.compare_digest(supplied, expected)

    def _retry_after(self, scope) -> int | None:
        return self._retry_after_bucket(
            scope,
            self._requests,
            self.rate_limit_requests,
            self.rate_limit_window_seconds,
        )

    def _retry_after_bucket(
        self,
        scope,
        bucket: dict[str, deque[float]],
        request_limit: int,
        window_seconds: int,
    ) -> int | None:
        if request_limit <= 0:
            return None
        client = scope.get("client") or ("unknown", 0)
        key = str(client[0])
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            entries = bucket[key]
            while entries and entries[0] <= cutoff:
                entries.popleft()
            if len(entries) >= request_limit:
                return max(1, int(window_seconds - (now - entries[0]) + 0.999))
            entries.append(now)
        return None

    async def _json_response(
        self,
        send,
        status: int,
        detail: str,
        request_id: str,
        extra_headers: list[tuple[bytes, bytes]] | None = None,
    ) -> None:
        body = json.dumps({"detail": detail}, separators=(",", ":")).encode("utf-8")
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
            (b"x-request-id", request_id.encode("ascii")),
            *(extra_headers or []),
        ]
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})
