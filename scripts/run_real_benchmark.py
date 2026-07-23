#!/usr/bin/env python3
"""Validate operator-supplied real-corpus evidence without inventing results."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.release_readiness import build_release_readiness  # noqa: E402


def markdown(report: dict) -> str:
    lines = [
        "# Real-corpus 1.0 readiness report",
        "",
        f"- Candidate: `{report['candidate_version']}`",
        f"- Target: `{report['target_version']}`",
        f"- Status: **{report['status']}**",
        f"- Evidence updated: `{report['evidence_updated_at'] or 'not recorded'}`",
        "",
        "| Gate | Observed | Required | Result |",
        "| --- | ---: | ---: | :---: |",
    ]
    for gate in report["gates"]:
        lines.append(
            f"| {gate['label']} | {gate['observed']} | {gate['required']} | "
            f"{'pass' if gate['passed'] else 'blocked'} |"
        )
    if report["errors"]:
        lines.extend(["", "## Evidence errors", ""])
        lines.extend(f"- {item}" for item in report["errors"])
    lines.extend(
        [
            "",
            "> This report accepts only operator-owned evidence. Repository fixtures are not counted as real deployment proof.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate 1.0 real-corpus and operational evidence")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(os.getenv("RAG_REAL_BENCHMARK_MANIFEST", "")) if os.getenv("RAG_REAL_BENCHMARK_MANIFEST") else None,
        help="Private/operator-supplied JSON evidence manifest",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "eval" / "reports" / "real-readiness.md",
    )
    parser.add_argument(
        "--contract-only",
        action="store_true",
        help="Validate the sanitized blocked example; used by CI and does not claim a benchmark result",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = args.manifest
    if args.contract_only:
        manifest = ROOT / "eval" / "real" / "manifest.example.json"
    if manifest is None:
        print(
            "RAG_REAL_BENCHMARK_MANIFEST is required. Copy eval/real/manifest.example.json "
            "outside the repository and populate it from licensed, non-fixture evidence.",
            file=sys.stderr,
        )
        return 2
    report = build_release_readiness(manifest)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report["status"],
                "passed_gates": report["passed_gates"],
                "total_gates": report["total_gates"],
                "report": str(args.report),
                "contract_only": args.contract_only,
            },
            indent=2,
        )
    )
    if args.contract_only:
        return 0 if report["status"] == "blocked" and report["production_ready_claim"] is False else 1
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
