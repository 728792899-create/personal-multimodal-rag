#!/usr/bin/env python3
"""Fail CI when tracked or pending text files contain likely live credentials."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()
SKIP_PARTS = {".git", "node_modules", "dist", "test-results", "playwright-report", "__pycache__", ".pytest_cache"}
PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "GitHub token": re.compile(r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9]{30,}\b"),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
}


def candidate_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    paths: list[Path] = []
    for raw in result.stdout.decode("utf-8", errors="surrogateescape").split("\0"):
        if not raw:
            continue
        path = ROOT / raw
        if path == SELF or any(part in SKIP_PARTS for part in path.parts) or not path.is_file():
            continue
        paths.append(path)
    return paths


def main() -> int:
    findings: list[str] = []
    for path in candidate_files():
        try:
            if path.stat().st_size > 2_000_000:
                continue
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for label, pattern in PATTERNS.items():
            for match in pattern.finditer(content):
                line = content.count("\n", 0, match.start()) + 1
                findings.append(f"{path.relative_to(ROOT)}:{line}: possible {label}")

    if findings:
        print("Secret scan failed:\n" + "\n".join(f"- {item}" for item in findings))
        return 1
    print(f"Secret scan passed ({len(candidate_files())} text/binary candidates inspected safely).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
