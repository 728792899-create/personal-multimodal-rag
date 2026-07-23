#!/usr/bin/env python3
"""Bounded Compose fault injection with explicit opt-in and consistency checks."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

SCENARIOS = {
    "api": "backend",
    "worker": "worker",
    "redis": "redis",
    "postgres": "postgres",
    "object-store": "minio",
}


def compose(compose_file: Path, *args: str, capture: bool = False) -> str:
    result = subprocess.run(
        ["docker", "compose", "-f", str(compose_file), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout.strip() if capture else ""


def consistency_snapshot(compose_file: Path) -> dict:
    query = """
    SELECT json_build_object(
      'documents', (SELECT count(*) FROM documents),
      'document_ids', (SELECT count(DISTINCT document_id) FROM documents),
      'jobs', (SELECT count(*) FROM index_jobs),
      'job_keys', (SELECT count(DISTINCT idempotency_key) FROM index_jobs),
      'outbox_unpublished', (SELECT count(*) FROM outbox_events WHERE published_at IS NULL)
    );
    """
    raw = compose(
        compose_file,
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "rag",
        "-d",
        "personal_rag",
        "-At",
        "-c",
        query,
        capture=True,
    )
    return json.loads(raw)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inject one recoverable production Compose failure")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="worker")
    parser.add_argument("--compose-file", type=Path, default=Path("compose.production.yml"))
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    service = SCENARIOS[args.scenario]
    plan = {
        "scenario": args.scenario,
        "service": service,
        "actions": [
            "capture PostgreSQL document/job/outbox counts",
            f"kill {service}",
            f"recreate and health-check {service}",
            "wait for the complete production stack",
            "assert document IDs and idempotency keys remain unique",
        ],
    }
    if not args.execute:
        print(json.dumps({"dry_run": True, **plan}, indent=2))
        return 0
    if os.getenv("RAG_CHAOS_CONFIRM") != "I_UNDERSTAND":
        print("set RAG_CHAOS_CONFIRM=I_UNDERSTAND before --execute", file=sys.stderr)
        return 2
    before = consistency_snapshot(args.compose_file)
    compose(args.compose_file, "kill", service)
    compose(args.compose_file, "up", "--wait", "--wait-timeout", "300", "-d", service)
    compose(args.compose_file, "up", "--wait", "--wait-timeout", "300", "-d")
    after = consistency_snapshot(args.compose_file)
    unique = (
        after["documents"] == after["document_ids"]
        and after["jobs"] == after["job_keys"]
        and after["documents"] >= before["documents"]
    )
    report = {"dry_run": False, **plan, "before": before, "after": after, "unique": unique}
    print(json.dumps(report, indent=2))
    return 0 if unique else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"chaos drill failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
