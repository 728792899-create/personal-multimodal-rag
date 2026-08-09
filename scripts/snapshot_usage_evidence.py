#!/usr/bin/env python3
"""保存不含问题正文、且经过明确声明的生产使用量汇总快照。"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.run_production_corpus_validation import Session
except ModuleNotFoundError:  # Direct script execution.
    from run_production_corpus_validation import Session


ALLOWED_FIELDS = {
    "human_originated_questions",
    "target",
    "remaining_for_1_0",
    "conversation_count",
    "first_recorded_at",
    "last_recorded_at",
    "attestation",
}


def snapshot(session: Session) -> dict:
    payload, _ = session.request("api/system/usage-evidence")
    if not isinstance(payload, dict):
        raise ValueError("使用量证据接口返回了无效数据")
    unexpected = set(payload) - ALLOWED_FIELDS
    if unexpected:
        raise ValueError(
            f"使用量证据包含不受支持的字段：{sorted(unexpected)}"
        )
    if payload.get("attestation") != "human-originated":
        raise ValueError("使用量证据缺少来源声明")
    return {
        "schema_version": 1,
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **payload,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="保存生产使用量汇总证据快照"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:5173")
    parser.add_argument(
        "--password-file",
        type=Path,
        default=Path("secrets/operator_password"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/validation/usage-summary.json"),
    )
    args = parser.parse_args()
    session = Session(
        args.base_url,
        args.password_file.expanduser().resolve(),
    )
    report = snapshot(session)
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
