#!/usr/bin/env python3
"""Create a versioned PostgreSQL + object-store production backup bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact(path: Path) -> dict:
    return {"file": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def compose_command(compose_file: Path, *args: str) -> list[str]:
    return ["docker", "compose", "-f", str(compose_file), *args]


def capture(command: list[str], destination: Path) -> None:
    with destination.open("wb") as output:
        result = subprocess.run(command, stdout=output, stderr=subprocess.PIPE, check=False)
    if result.returncode:
        destination.unlink(missing_ok=True)
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[-2000:])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Back up the production data plane")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(os.getenv("RAG_BACKUP_OUTPUT", "")) if os.getenv("RAG_BACKUP_OUTPUT") else None,
    )
    parser.add_argument("--compose-file", type=Path, default=Path("compose.production.yml"))
    parser.add_argument(
        "--readiness-url",
        default="http://127.0.0.1:5173/ready",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output is None:
        raise SystemExit("set RAG_BACKUP_OUTPUT or pass --output /secure/backup/directory")
    if args.output.exists() and any(args.output.iterdir()):
        raise SystemExit("backup output directory must be empty")
    args.output.mkdir(parents=True, exist_ok=True)
    postgres_dump = args.output / "postgres.dump"
    objects_tar = args.output / "minio-objects.tar"
    compose_config = args.output / "compose-config.txt"

    try:
        with urlopen(args.readiness_url, timeout=10) as response:
            readiness = json.load(response)
    except Exception:
        readiness = {"ready": False, "status": "unavailable-at-backup"}
    subprocess.run(
        compose_command(args.compose_file, "stop", "frontend", "backend", "worker"),
        check=True,
    )
    try:
        capture(
            compose_command(
                args.compose_file,
                "exec",
                "-T",
                "postgres",
                "pg_dump",
                "-U",
                "rag",
                "-d",
                "personal_rag",
                "-Fc",
            ),
            postgres_dump,
        )
        capture(
            compose_command(
                args.compose_file,
                "run",
                "--rm",
                "-T",
                "--no-deps",
                "backend",
                "python",
                "/app/scripts/s3_archive.py",
                "export",
            ),
            objects_tar,
        )
        capture(compose_command(args.compose_file, "config"), compose_config)
    finally:
        subprocess.run(
            compose_command(
                args.compose_file,
                "up",
                "--wait",
                "--wait-timeout",
                "300",
                "-d",
            ),
            check=False,
        )
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "release": "0.4.0-rc.1",
        "source_of_truth": ["postgres.dump", "minio-objects.tar"],
        "redis_policy": "not backed up; Redis Streams are reconstructed from PostgreSQL outbox",
        "readiness": {
            "status": readiness.get("status")
            or ("ready" if readiness.get("ready") else "degraded"),
            "schema_version": readiness.get("schema_version"),
        },
        "artifacts": [artifact(postgres_dump), artifact(objects_tar), artifact(compose_config)],
    }
    manifest_path = args.output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"backup": str(args.output), "manifest": str(manifest_path)}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"backup failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
