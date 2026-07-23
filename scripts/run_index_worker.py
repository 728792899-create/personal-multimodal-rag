from __future__ import annotations

import os
import signal
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.store import ingestion_worker, outbox_dispatcher


def main() -> int:
    stopped = threading.Event()
    heartbeat_path = Path(
        os.getenv("WORKER_HEARTBEAT_PATH", "/tmp/worker-heartbeat")
    )

    def stop(*_):
        stopped.set()

    def heartbeat() -> None:
        while not stopped.is_set():
            if ingestion_worker.is_alive():
                heartbeat_path.touch()
            stopped.wait(5)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    if outbox_dispatcher:
        outbox_dispatcher.start()
    ingestion_worker.start()
    heartbeat_thread = threading.Thread(
        target=heartbeat,
        name="rag-worker-health",
        daemon=True,
    )
    heartbeat_thread.start()
    stopped.wait()
    ingestion_worker.stop()
    if outbox_dispatcher:
        outbox_dispatcher.stop()
    heartbeat_thread.join(timeout=1)
    heartbeat_path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
