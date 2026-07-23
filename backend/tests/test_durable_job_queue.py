from __future__ import annotations

from app.services.document_registry import DocumentRegistry
from app.services.job_queue import OutboxDispatcher
from datetime import datetime


class RecordingQueue:
    def __init__(self):
        self.events: list[dict] = []

    def publish(self, event: dict) -> str:
        self.events.append(event)
        return f"message-{len(self.events)}"


def _job(registry: DocumentRegistry, key: str = "durable-job") -> dict:
    return registry.create_index_job(
        source_type="url",
        source_name="example.org",
        payload={"url": "https://example.org/guide"},
        idempotency_key=key,
    )


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
