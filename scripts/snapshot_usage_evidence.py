#!/usr/bin/env python3
"""Snapshot aggregate, explicitly attested production usage without question text."""

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
        raise ValueError("usage evidence endpoint returned an invalid payload")
    unexpected = set(payload) - ALLOWED_FIELDS
    if unexpected:
        raise ValueError(
            f"usage evidence contains unsupported fields: {sorted(unexpected)}"
        )
    if payload.get("attestation") != "human-originated":
        raise ValueError("usage evidence attestation is missing")
    return {
        "schema_version": 1,
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **payload,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Snapshot aggregate production usage evidence"
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
