from __future__ import annotations

import signal
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.store import ingestion_worker, outbox_dispatcher


def main() -> int:
    stopped = threading.Event()

    def stop(*_):
        stopped.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    if outbox_dispatcher:
        outbox_dispatcher.start()
    ingestion_worker.start()
    stopped.wait()
    ingestion_worker.stop()
    if outbox_dispatcher:
        outbox_dispatcher.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
