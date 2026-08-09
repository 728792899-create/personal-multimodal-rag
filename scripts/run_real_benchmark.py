#!/usr/bin/env python3
"""验证运维人员提供的真实语料证据，不补写或伪造结果。"""

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
        "# 真实语料 1.0 就绪度报告",
        "",
        f"- 候选版本：`{report['candidate_version']}`",
        f"- 目标版本：`{report['target_version']}`",
        f"- 状态：**{report['status']}**",
        f"- 证据更新时间：`{report['evidence_updated_at'] or '未记录'}`",
        "",
        "| 门槛 | 实际 | 要求 | 结果 |",
        "| --- | ---: | ---: | :---: |",
    ]
    for gate in report["gates"]:
        lines.append(
            f"| {gate['label']} | {gate['observed']} | {gate['required']} | "
            f"{'通过' if gate['passed'] else '未达标'} |"
        )
    if report["errors"]:
        lines.extend(["", "## 证据错误", ""])
        lines.extend(f"- {item}" for item in report["errors"])
    lines.extend(
        [
            "",
            "> 本报告仅接受运维人员持有的证据；仓库内 fixture 不计入真实部署证明。",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="验证 1.0 真实语料与运维证据")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(os.getenv("RAG_REAL_BENCHMARK_MANIFEST", "")) if os.getenv("RAG_REAL_BENCHMARK_MANIFEST") else None,
        help="由运维人员提供的私有 JSON 证据清单",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "eval" / "reports" / "real-readiness.md",
    )
    parser.add_argument(
        "--contract-only",
        action="store_true",
        help="仅验证脱敏的未达标示例；供 CI 使用，不代表真实基准测试结果",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = args.manifest
    if args.contract_only:
        manifest = ROOT / "eval" / "real" / "manifest.example.json"
    if manifest is None:
        print(
            "必须设置 RAG_REAL_BENCHMARK_MANIFEST。请将 eval/real/manifest.example.json "
            "复制到仓库外，并使用许可明确、非 fixture 的真实证据填写。",
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
