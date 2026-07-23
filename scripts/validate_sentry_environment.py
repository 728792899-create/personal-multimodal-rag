#!/usr/bin/env python3
"""Record a content-free Sentry environment preflight without exposing its DSN."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


GIB = 1024**3
ERRORS_ONLY_MIN_GIB = 7
FULL_MIN_GIB = 14


def command_output(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def main() -> int:
    dsn = os.getenv("SENTRY_DSN", "").strip()
    docker_memory = int(command_output(["docker", "info", "--format", "{{.MemTotal}}"]) or 0)
    host_memory = int(command_output(["sysctl", "-n", "hw.memsize"]) or 0)
    parsed = urlparse(dsn) if dsn else None
    report = {
        "schema_version": 1,
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sdk_configured": bool(dsn),
        "dsn_scheme": parsed.scheme if parsed else "",
        "dsn_host_present": bool(parsed and parsed.hostname),
        "dsn_recorded": False,
        "docker_memory_bytes": docker_memory,
        "host_memory_bytes": host_memory,
        "self_hosted_resource_preflight": {
            "errors_only_min_gib": ERRORS_ONLY_MIN_GIB,
            "full_min_gib": FULL_MIN_GIB,
            "errors_only_memory_floor_met": docker_memory >= ERRORS_ONLY_MIN_GIB * GIB,
            "full_memory_floor_met": docker_memory >= FULL_MIN_GIB * GIB,
        },
        "event_delivery_verified": False,
        "passed": False,
        "blocking_reason": (
            "SENTRY_DSN is not configured; no real event can be delivered"
            if not dsn
            else "a real scrubbed event still must be confirmed in the target Sentry project"
        ),
    }
    output = Path("data/validation/sentry-environment.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, output)
    print(json.dumps(report, indent=2))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
