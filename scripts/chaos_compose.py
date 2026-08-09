#!/usr/bin/env python3
"""执行有边界、需明确确认且带一致性检查的 Compose 故障注入。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
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
    parser = argparse.ArgumentParser(description="注入一个可恢复的生产 Compose 故障")
    parser.add_argument(
        "--scenario",
        choices=[*sorted(SCENARIOS), "all"],
        default="worker",
    )
    parser.add_argument("--compose-file", type=Path, default=Path("compose.production.yml"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def scenario_plan(scenario: str) -> dict:
    service = SCENARIOS[scenario]
    return {
        "scenario": scenario,
        "service": service,
        "actions": [
            "capture PostgreSQL document/job/outbox counts",
            f"kill {service}",
            f"recreate and health-check {service}",
            "wait for the complete production stack",
            "assert document IDs and idempotency keys remain unique",
        ],
    }


def run_scenario(compose_file: Path, scenario: str) -> dict:
    plan = scenario_plan(scenario)
    before = consistency_snapshot(compose_file)
    compose(compose_file, "kill", plan["service"])
    compose(
        compose_file,
        "up",
        "--wait",
        "--wait-timeout",
        "300",
        "-d",
        plan["service"],
    )
    compose(compose_file, "up", "--wait", "--wait-timeout", "300", "-d")
    after = consistency_snapshot(compose_file)
    unique = (
        after["documents"] == after["document_ids"]
        and after["jobs"] == after["job_keys"]
        and after["documents"] >= before["documents"]
    )
    return {**plan, "before": before, "after": after, "passed": unique}


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    args = parse_args()
    selected = sorted(SCENARIOS) if args.scenario == "all" else [args.scenario]
    plans = [scenario_plan(scenario) for scenario in selected]
    if not args.execute:
        print(json.dumps({"dry_run": True, "scenarios": plans}, indent=2))
        return 0
    if os.getenv("RAG_CHAOS_CONFIRM") != "I_UNDERSTAND":
        print("执行 --execute 前请设置 RAG_CHAOS_CONFIRM=I_UNDERSTAND。", file=sys.stderr)
        return 2
    results = [
        run_scenario(args.compose_file, scenario)
        for scenario in selected
    ]
    report = {
        "schema_version": 1,
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dry_run": False,
        "passed": all(item["passed"] for item in results),
        "scenarios": results,
    }
    if args.output:
        write_report(args.output.expanduser().resolve(), report)
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"混沌演练失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
