from __future__ import annotations

import threading
from types import SimpleNamespace

from app.services.document_registry import DocumentRegistry
from app.services.ingestion_jobs import IngestionWorker
from app.services.job_queue import OutboxDispatcher, QueueMessage, RedisJobQueue
from datetime import datetime


class RecordingQueue:
    def __init__(self):
        self.events: list[dict] = []

    def publish(self, event: dict) -> str:
        self.events.append(event)
        return f"message-{len(self.events)}"


class FakeRedisStream:
    def __init__(self, *, reclaimed=None, fresh=None):
        self.reclaimed = list(reclaimed or [])
        self.fresh = list(fresh or [])
        self.acknowledged: list[str] = []
        self.autoclaim_calls: list[dict] = []

    def ping(self):
        return True

    def xgroup_create(self, *_args, **_kwargs):
        return True

    def xautoclaim(self, name, groupname, consumername, min_idle_time, start_id, *, count):
        self.autoclaim_calls.append(
            {
                "name": name,
                "group": groupname,
                "consumer": consumername,
                "min_idle_time": min_idle_time,
                "start_id": start_id,
                "count": count,
            }
        )
        entries = self.reclaimed[:count]
        self.reclaimed = self.reclaimed[count:]
        return ["0-0", entries, []]

    def xreadgroup(self, *_args, **_kwargs):
        if not self.fresh:
            return []
        entries = list(self.fresh)
        self.fresh = []
        return [[RedisJobQueue.stream_name, entries]]

    def xack(self, _stream, _group, message_id):
        self.acknowledged.append(str(message_id))
        return 1


def _job(registry: DocumentRegistry, key: str = "durable-job") -> dict:
    return registry.create_index_job(
        source_type="url",
        source_name="example.org",
        payload={"url": "https://example.org/guide"},
        idempotency_key=key,
    )


def test_redis_queue_reclaims_stale_pending_before_reading_new_messages():
    stale = (
        "1710000000000-0",
        {
            "event_type": "index_job.queued",
            "aggregate_id": "job-stale",
            "payload": '{"job_id":"job-stale"}',
        },
    )
    client = FakeRedisStream(reclaimed=[stale])
    queue = RedisJobQueue(
        "redis://unused",
        consumer_name="worker-recovery",
        client=client,
        stale_pending_ms=123_000,
    )

    message = queue.wait(timeout_seconds=0.01)

    assert message == QueueMessage(
        message_id="1710000000000-0",
        event_type="index_job.queued",
        aggregate_id="job-stale",
        payload={"job_id": "job-stale"},
    )
    assert client.autoclaim_calls[0]["min_idle_time"] == 123_000


def test_worker_acks_reclaimed_terminal_signal_without_polling_for_another_job():
    registry = DocumentRegistry(":memory:")
    job = _job(registry, "terminal-signal")
    registry.claim_next_index_job("original-worker")
    registry.complete_index_job(job["id"], "document-1")
    message = QueueMessage(
        message_id="1710000000001-0",
        event_type="index_job.queued",
        aggregate_id=job["id"],
        payload={"job_id": job["id"]},
    )

    class TerminalQueue:
        def __init__(self):
            self.acknowledged: list[str] = []
            self.delivered = False
            self.worker = None

        def wait(self, _timeout_seconds: float):
            if self.delivered:
                return None
            self.delivered = True
            return message

        def acknowledge(self, message_id: str):
            self.acknowledged.append(message_id)
            self.worker._stop.set()

    worker = IngestionWorker.__new__(IngestionWorker)
    worker.registry = registry
    worker.job_signal_queue = TerminalQueue()
    worker.job_signal_queue.worker = worker
    worker.settings = SimpleNamespace(ingestion_poll_seconds=0.01)
    worker._stop = threading.Event()
    job_polls: list[bool] = []
    worker.run_once = lambda: job_polls.append(True) or False

    worker._loop()

    assert job_polls == []
    assert worker.job_signal_queue.acknowledged == [message.message_id]
    assert registry.get_index_job(job["id"])["status"] == "succeeded"
    assert registry.get_index_job(job["id"])["attempts"] == 1


def test_index_job_and_outbox_commit_together_and_dispatch_once():
    registry = DocumentRegistry(":memory:")
    queue = RecordingQueue()
    first = _job(registry)
    duplicate = _job(registry)

    assert duplicate["id"] == first["id"]
    assert len(registry.list_pending_outbox_events()) == 1

    dispatcher = OutboxDispatcher(registry, queue)
    assert dispatcher.dispatch_once() == 1
    assert dispatcher.dispatch_once() == 0
    assert queue.events[0]["aggregate_id"] == first["id"]


def test_outbox_dispatch_failure_stores_localized_operator_message():
    class FailingQueue:
        def publish(self, _event: dict) -> str:
            raise RuntimeError("redis auth token=secret")

    registry = DocumentRegistry(":memory:")
    _job(registry, "localized-outbox-error")

    assert OutboxDispatcher(registry, FailingQueue()).dispatch_once() == 0
    with registry._connection() as connection:
        stored = connection.execute(
            "SELECT error_message FROM outbox_events WHERE status = 'pending'"
        ).fetchone()["error_message"]

    assert stored == "任务投递暂时失败，将自动重试。"
    assert "secret" not in stored


def test_terminal_job_failure_is_retained_in_dead_letter_queue():
    registry = DocumentRegistry(":memory:")
    job = registry.create_index_job(
        source_type="url",
        source_name="example.org",
        payload={"url": "https://example.org/guide"},
        idempotency_key="dead-letter-job",
        max_attempts=1,
    )
    registry.claim_next_index_job("worker-1")

    failed = registry.fail_index_job(job["id"], "PROVIDER_UNAVAILABLE", "provider token=secret")
    dead_letters = registry.list_dead_letter_jobs()

    assert failed and failed["status"] == "failed"
    assert len(dead_letters) == 1
    assert dead_letters[0]["job_id"] == job["id"]
    assert dead_letters[0]["error_code"] == "PROVIDER_UNAVAILABLE"
    assert "secret" not in dead_letters[0]["error_message"]
    assert "[REDACTED]" in dead_letters[0]["error_message"]


def test_only_the_claiming_worker_can_renew_a_running_job_lease():
    registry = DocumentRegistry(":memory:")
    job = _job(registry, "lease-heartbeat")
    registry.claim_next_index_job("worker-1", lease_seconds=1)
    with registry._connection() as connection:
        original = datetime.fromisoformat(
            connection.execute(
                "SELECT lease_expires_at FROM index_jobs WHERE job_id = ?",
                (job["id"],),
            ).fetchone()["lease_expires_at"]
        )

    assert registry.renew_index_job_lease(
        job["id"],
        "worker-2",
        lease_seconds=300,
    ) is False
    assert registry.renew_index_job_lease(
        job["id"],
        "worker-1",
        lease_seconds=300,
    ) is True

    with registry._connection() as connection:
        renewed = datetime.fromisoformat(
            connection.execute(
                "SELECT lease_expires_at FROM index_jobs WHERE job_id = ?",
                (job["id"],),
            ).fetchone()["lease_expires_at"]
        )
    assert renewed > original


def test_outbox_dispatcher_survives_a_transient_registry_failure():
    recovered = threading.Event()

    class FlakyRegistry:
        calls = 0

        def list_pending_outbox_events(self, _limit):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary database failure")
            recovered.set()
            return []

    dispatcher = OutboxDispatcher(FlakyRegistry(), RecordingQueue(), poll_seconds=0.01)
    dispatcher.start()
    try:
        assert recovered.wait(0.5)
    finally:
        dispatcher.stop()


def test_ingestion_worker_loop_survives_a_transient_registry_failure():
    recovered = threading.Event()
    worker = IngestionWorker.__new__(IngestionWorker)
    worker._stop = threading.Event()
    worker.settings = SimpleNamespace(ingestion_poll_seconds=0.01)
    worker.job_signal_queue = None
    calls = 0

    def run_once():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary database failure")
        recovered.set()
        worker._stop.set()
        return False

    worker.run_once = run_once
    thread = threading.Thread(target=worker._loop)
    thread.start()
    try:
        assert recovered.wait(0.5)
    finally:
        worker._stop.set()
        thread.join(1)
