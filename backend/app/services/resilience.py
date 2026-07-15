from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, TypeVar

import httpx


T = TypeVar("T")


class CircuitOpenError(RuntimeError):
    pass


def is_transient_error(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, httpx.TimeoutException, httpx.TransportError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return False


@dataclass
class CircuitBreaker:
    name: str
    failure_threshold: int = 3
    reset_timeout_seconds: float = 30.0
    _failures: int = 0
    _opened_at: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def before_call(self) -> None:
        with self._lock:
            if not self._opened_at:
                return
            if time.monotonic() - self._opened_at >= self.reset_timeout_seconds:
                self._opened_at = 0.0
                self._failures = 0
                return
            raise CircuitOpenError(f"{self.name} is temporarily unavailable")

    def success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = 0.0

    def failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= max(1, self.failure_threshold):
                self._opened_at = time.monotonic()

    @property
    def state(self) -> str:
        with self._lock:
            return "open" if self._opened_at else "closed"


class ResilientExecutor:
    def __init__(
        self,
        name: str,
        *,
        attempts: int = 3,
        base_delay_seconds: float = 0.1,
        max_delay_seconds: float = 2.0,
        jitter_ratio: float = 0.2,
        breaker: CircuitBreaker | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        random_source: Callable[[], float] = random.random,
    ):
        self.name = name
        self.attempts = max(1, attempts)
        self.base_delay_seconds = max(0.0, base_delay_seconds)
        self.max_delay_seconds = max(self.base_delay_seconds, max_delay_seconds)
        self.jitter_ratio = max(0.0, min(jitter_ratio, 1.0))
        self.breaker = breaker or CircuitBreaker(name)
        self.sleeper = sleeper
        self.random_source = random_source

    def run(self, operation: Callable[[], T], *, retryable: Callable[[Exception], bool] = is_transient_error) -> T:
        self.breaker.before_call()
        for attempt in range(1, self.attempts + 1):
            try:
                value = operation()
            except Exception as exc:
                if not retryable(exc) or attempt >= self.attempts:
                    self.breaker.failure()
                    raise
                delay = min(self.base_delay_seconds * (2 ** (attempt - 1)), self.max_delay_seconds)
                jitter = delay * self.jitter_ratio * self.random_source()
                self.sleeper(delay + jitter)
            else:
                self.breaker.success()
                return value
        raise RuntimeError(f"{self.name} retry loop exhausted")
