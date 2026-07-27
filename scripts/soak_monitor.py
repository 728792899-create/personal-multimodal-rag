#!/usr/bin/env python3
"""Record health samples in an append-only SHA-256 chain for the 14-day soak."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


SCHEMA_VERSION = 1
STOP = False


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def event_hash(payload: dict) -> str:
    return hashlib.sha256(canonical(payload)).hexdigest()


def fetch_json(url: str, timeout: float) -> tuple[int, dict, float]:
    started = time.monotonic()
    try:
        with urlopen(url, timeout=timeout) as response:
            return response.status, json.load(response), (time.monotonic() - started) * 1000
    except HTTPError as exc:
        try:
            payload = json.load(exc)
        except (ValueError, OSError):
            payload = {}
        return exc.code, payload, (time.monotonic() - started) * 1000


def readiness_from_health(health: dict) -> dict:
    runtime = health.get("runtime")
    return runtime if isinstance(runtime, dict) else {}


def health_is_ready(status: int, payload: dict) -> bool:
    return status == 200 and (
        payload.get("ready") is True or payload.get("status") == "ready"
    )


def empty_state() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "started_at": "",
        "last_sample_at": "",
        "last_success_at": "",
        "continuous_since": "",
        "continuous_seconds": 0,
        "longest_continuous_seconds": 0,
        "sample_count": 0,
        "success_count": 0,
        "failure_count": 0,
        "last_event_hash": "",
    }


def load_state(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return empty_state()
    return {**empty_state(), **payload}


def atomic_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def sample(
    directory: Path,
    *,
    health_url: str,
    readiness_url: str,
    expected_mode: str,
    timeout: float,
    maximum_gap_seconds: float,
) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    state_path = directory / "soak-state.json"
    events_path = directory / "soak-events.jsonl"
    lock_path = directory / ".soak.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = load_state(state_path)
        observed = utc_now()
        error = ""
        health_status = 0
        readiness_status = 0
        readiness: dict = {}
        latency_ms = 0.0
        try:
            health_status, health, health_latency = fetch_json(health_url, timeout)
            if readiness_url:
                readiness_status, readiness, readiness_latency = fetch_json(
                    readiness_url, timeout
                )
            else:
                readiness = readiness_from_health(health)
                readiness_status = health_status
                readiness_latency = 0.0
            latency_ms = health_latency + readiness_latency
            healthy = (
                health_is_ready(health_status, health)
                and readiness_status == 200
                and bool(readiness.get("ready"))
                and readiness.get("mode") == expected_mode
            )
        except (OSError, ValueError, URLError) as exc:
            healthy = False
            error = type(exc).__name__

        previous_sample = datetime.fromisoformat(state["last_sample_at"]) if state["last_sample_at"] else None
        gap = (observed - previous_sample).total_seconds() if previous_sample else 0
        if healthy and (not previous_sample or (gap <= maximum_gap_seconds and state["continuous_since"])):
            continuous_since = (
                datetime.fromisoformat(state["continuous_since"])
                if state["continuous_since"]
                else observed
            )
        elif healthy:
            continuous_since = observed
        else:
            continuous_since = None
        continuous_seconds = (
            max(0, int((observed - continuous_since).total_seconds()))
            if continuous_since
            else 0
        )
        event = {
            "schema_version": SCHEMA_VERSION,
            "observed_at": iso(observed),
            "healthy": healthy,
            "health_status": health_status,
            "readiness_status": readiness_status,
            "mode": readiness.get("mode", ""),
            "configured": bool(readiness.get("configured")),
            "component_health": {
                key: bool(value.get("healthy", value.get("configured")))
                for key, value in readiness.get("components", {}).items()
                if isinstance(value, dict)
            },
            "latency_ms": round(latency_ms, 2),
            "gap_seconds": round(gap, 2),
            "error_type": error,
            "previous_hash": state["last_event_hash"],
        }
        event["event_hash"] = event_hash(event)
        with events_path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            output.flush()
            os.fsync(output.fileno())
        state.update(
            {
                "started_at": state["started_at"] or iso(observed),
                "last_sample_at": iso(observed),
                "last_success_at": iso(observed) if healthy else state["last_success_at"],
                "continuous_since": iso(continuous_since) if continuous_since else "",
                "continuous_seconds": continuous_seconds,
                "longest_continuous_seconds": max(
                    int(state["longest_continuous_seconds"]), continuous_seconds
                ),
                "sample_count": int(state["sample_count"]) + 1,
                "success_count": int(state["success_count"]) + int(healthy),
                "failure_count": int(state["failure_count"]) + int(not healthy),
                "last_event_hash": event["event_hash"],
            }
        )
        atomic_json(state_path, state)
        return {"event": event, "state": state}


def verify_chain(path: Path) -> dict:
    previous = ""
    count = 0
    last_observed_at = ""
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            event = json.loads(line)
            recorded = event.pop("event_hash", "")
            if event.get("previous_hash") != previous or event_hash(event) != recorded:
                raise ValueError(f"持续运行证据的哈希链在第 {line_number} 行无效。")
            previous = recorded
            last_observed_at = str(event.get("observed_at") or "")
            count += 1
    return {
        "valid": True,
        "events": count,
        "last_event_hash": previous,
        "last_observed_at": last_observed_at,
    }


def verify_evidence(
    directory: Path,
    *,
    now: datetime | None = None,
    maximum_age_seconds: float = 900,
) -> dict:
    chain = verify_chain(directory / "soak-events.jsonl")
    state = load_state(directory / "soak-state.json")
    observed_at = chain["last_observed_at"]
    try:
        observed = datetime.fromisoformat(observed_at)
        age_seconds = ((now or utc_now()) - observed).total_seconds()
    except (TypeError, ValueError):
        age_seconds = float("inf")
    wall_clock_fresh = -5 <= age_seconds <= max(1.0, maximum_age_seconds)
    try:
        state_consistent = (
            int(state.get("sample_count", -1)) == int(chain["events"])
            and state.get("last_event_hash") == chain["last_event_hash"]
            and state.get("last_sample_at") == observed_at
        )
    except (TypeError, ValueError):
        state_consistent = False
    return {
        **chain,
        "wall_clock_fresh": wall_clock_fresh,
        "last_event_age_seconds": (
            round(age_seconds, 2) if age_seconds != float("inf") else None
        ),
        "state_consistent": state_consistent,
        "eligible": bool(chain["valid"] and wall_clock_fresh and state_consistent),
        "state": state,
    }


def stop(_signum, _frame) -> None:
    global STOP
    STOP = True


def main() -> int:
    parser = argparse.ArgumentParser(description="记录或验证生产持续运行证据")
    parser.add_argument("--evidence-dir", type=Path, default=Path("data/validation"))
    parser.add_argument("--health-url", default="http://backend:8010/ready")
    parser.add_argument(
        "--readiness-url",
        default="http://backend:8010/api/system/readiness-report",
    )
    parser.add_argument("--expected-mode", default="production")
    parser.add_argument("--interval-seconds", type=float, default=300)
    parser.add_argument("--timeout-seconds", type=float, default=10)
    parser.add_argument("--maximum-age-seconds", type=float, default=900)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    directory = args.evidence_dir.expanduser().resolve()
    if args.verify:
        result = verify_evidence(
            directory,
            maximum_age_seconds=max(1.0, args.maximum_age_seconds),
        )
        print(json.dumps(result, indent=2))
        return 0 if result["eligible"] else 1
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    interval = max(30.0, args.interval_seconds)
    while not STOP:
        result = sample(
            directory,
            health_url=args.health_url,
            readiness_url=args.readiness_url,
            expected_mode=args.expected_mode,
            timeout=max(1.0, args.timeout_seconds),
            maximum_gap_seconds=interval * 2.5,
        )
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if args.once or STOP:
            break
        time.sleep(interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
