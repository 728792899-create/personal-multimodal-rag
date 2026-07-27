from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass

from app.services.safe_logging import public_error_message


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QueueMessage:
    message_id: str
    event_type: str
    aggregate_id: str
    payload: dict


class RedisJobQueue:
    stream_name = "rag:index-jobs"
    group_name = "rag-index-workers"

    def __init__(self, redis_url: str, *, consumer_name: str, client=None):
        if not redis_url:
            raise ValueError("REDIS_URL is required")
        if client is None:
            try:
                import redis
            except ImportError as exc:
                raise RuntimeError("Install redis to use RedisJobQueue") from exc
            client = redis.Redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=5,
            )
        self.client = client
        self.consumer_name = consumer_name
        self.client.ping()
        try:
            self.client.xgroup_create(
                self.stream_name,
                self.group_name,
                id="0",
                mkstream=True,
            )
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def publish(self, event: dict) -> str:
        return str(
            self.client.xadd(
                self.stream_name,
                {
                    "event_type": event["event_type"],
                    "aggregate_id": event["aggregate_id"],
                    "payload": json.dumps(event["payload"], ensure_ascii=False),
                },
                maxlen=100_000,
                approximate=True,
            )
        )

    def wait(self, timeout_seconds: float = 1.0) -> QueueMessage | None:
        response = self.client.xreadgroup(
            self.group_name,
            self.consumer_name,
            {self.stream_name: ">"},
            count=1,
            block=max(1, int(timeout_seconds * 1000)),
        )
        if not response:
            return None
        _, entries = response[0]
        message_id, fields = entries[0]
        try:
            payload = json.loads(fields.get("payload") or "{}")
        except json.JSONDecodeError:
            payload = {}
        return QueueMessage(
            message_id=str(message_id),
            event_type=str(fields.get("event_type") or ""),
            aggregate_id=str(fields.get("aggregate_id") or ""),
            payload=payload,
        )

    def acknowledge(self, message_id: str) -> None:
        self.client.xack(self.stream_name, self.group_name, message_id)

    def health(self) -> bool:
        return bool(self.client.ping())


class OutboxDispatcher:
    def __init__(self, registry, queue: RedisJobQueue, poll_seconds: float = 0.5):
        self.registry = registry
        self.queue = queue
        self.poll_seconds = max(0.05, float(poll_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="rag-outbox-dispatcher",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)
        self._thread = None

    def dispatch_once(self) -> int:
        published = 0
        for event in self.registry.list_pending_outbox_events(100):
            try:
                self.queue.publish(event)
                self.registry.mark_outbox_published(event["id"])
                published += 1
            except Exception as exc:
                self.registry.mark_outbox_failed(
                    event["id"],
                    public_error_message(
                        exc,
                        "任务投递暂时失败，将自动重试。",
                    ),
                )
        return published

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                published = self.dispatch_once()
            except Exception as exc:
                logger.warning(
                    "outbox dispatch poll failed; retrying error_type=%s",
                    type(exc).__name__,
                )
                published = 0
            if not published:
                self._stop.wait(self.poll_seconds)
