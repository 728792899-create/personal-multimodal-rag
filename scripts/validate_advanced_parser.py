#!/usr/bin/env python3
"""Submit a real fixture to the isolated parser and save a content-free report."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


REMOTE_CLIENT = r"""
import json
import sys
import time

import httpx

filename = sys.argv[1]
profile = sys.argv[2]
timeout_seconds = float(sys.argv[3])
payload = sys.stdin.buffer.read()
with httpx.Client(base_url="http://127.0.0.1:8090", timeout=180) as client:
    capabilities = client.get("/v1/capabilities")
    capabilities.raise_for_status()
    created = client.post(
        "/v1/jobs",
        files={"file": (filename, payload, "application/octet-stream")},
        data={"profile": profile},
    )
    created.raise_for_status()
    job_id = created.json()["id"]
    deadline = time.monotonic() + timeout_seconds
    status = created.json()
    while time.monotonic() < deadline:
        status = client.get(f"/v1/jobs/{job_id}").json()
        if status.get("status") in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(2)
    else:
        client.delete(f"/v1/jobs/{job_id}")
        status = {"id": job_id, "status": "timed_out", "error": "validation timeout"}
print(json.dumps({"capabilities": capabilities.json(), "job": status}))
"""


def run_validation(
    compose_file: Path,
    fixture: Path,
    *,
    profile: str,
    timeout_seconds: float,
) -> dict:
    payload = fixture.read_bytes()
    command = [
        "docker",
        "compose",
        "-f",
        str(compose_file),
        "--profile",
        "advanced-parser",
        "exec",
        "-T",
        "parser-worker",
        "python",
        "-c",
        REMOTE_CLIENT,
        fixture.name,
        profile,
        str(timeout_seconds),
    ]
    result = subprocess.run(
        command,
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    raw = json.loads(result.stdout.decode("utf-8").splitlines()[-1])
    job = raw.get("job") if isinstance(raw.get("job"), dict) else {}
    parsed = job.get("result") if isinstance(job.get("result"), dict) else {}
    content_list = (
        parsed.get("content_list")
        if isinstance(parsed.get("content_list"), list)
        else []
    )
    error = str(job.get("error") or "")
    error_type = error.split(":", 1)[0][:120] if error else ""
    capabilities = (
        raw.get("capabilities")
        if isinstance(raw.get("capabilities"), dict)
        else {}
    )
    image_id = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(compose_file),
            "--profile",
            "advanced-parser",
            "images",
            "-q",
            "parser-worker",
        ],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()
    return {
        "schema_version": 1,
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "passed": job.get("status") == "succeeded" and bool(content_list),
        "profile": profile,
        "job_id": str(job.get("id") or ""),
        "job_status": str(job.get("status") or ""),
        "parser": str(parsed.get("parser") or ""),
        "element_count": len(content_list),
        "error_type": error_type,
        "fixture": {
            "filename": fixture.name,
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        },
        "capabilities": capabilities.get("profiles", []),
        "image_id": image_id,
        "content_recorded": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--compose-file",
        type=Path,
        default=Path("docker-compose.yml"),
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path("samples/multimodal-fixtures/images/img-01.png"),
    )
    parser.add_argument(
        "--profile",
        choices=("auto", "mineru", "docling", "paddleocr"),
        default="mineru",
    )
    parser.add_argument("--timeout-seconds", type=float, default=3_600)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/validation/advanced-parser.json"),
    )
    args = parser.parse_args()
    report = run_validation(
        args.compose_file.expanduser().resolve(),
        args.fixture.expanduser().resolve(),
        profile=args.profile,
        timeout_seconds=max(30, args.timeout_seconds),
    )
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        subprocess.CalledProcessError,
    ) as exc:
        print(f"advanced parser validation failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1)
