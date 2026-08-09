#!/usr/bin/env python3
"""仅在明确确认破坏性操作后恢复生产备份。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from production_backup import compose_command, sha256_file


def verify_manifest(bundle: Path) -> dict:
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("不支持的备份清单版本。")
    for item in manifest.get("artifacts", []):
        path = bundle / str(item["file"])
        if not path.is_file():
            raise ValueError(f"缺少备份产物：{path.name}")
        if path.stat().st_size != int(item["bytes"]) or sha256_file(path) != item["sha256"]:
            raise ValueError(f"备份产物校验和不一致：{path.name}")
    return manifest


def run(command: list[str], *, stdin_path: Path | None = None, check: bool = True) -> None:
    handle = stdin_path.open("rb") if stdin_path else None
    try:
        subprocess.run(command, stdin=handle, check=check)
    finally:
        if handle:
            handle.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="恢复生产数据平面")
    parser.add_argument(
        "--bundle",
        type=Path,
        default=Path(os.getenv("RAG_BACKUP_BUNDLE", "")) if os.getenv("RAG_BACKUP_BUNDLE") else None,
    )
    parser.add_argument("--compose-file", type=Path, default=Path("compose.production.yml"))
    parser.add_argument(
        "--confirm",
        default="",
        help='必须明确传入 "RESTORE"；此操作会替换 PostgreSQL 和 MinIO 内容',
    )
    parser.add_argument("--verify-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.bundle is None:
        print("请设置 RAG_BACKUP_BUNDLE，或传入 --bundle /secure/backup/directory。", file=sys.stderr)
        return 2
    manifest = verify_manifest(args.bundle)
    if args.verify_only:
        print(json.dumps({"verified": True, "created_at": manifest.get("created_at")}, indent=2))
        return 0
    if args.confirm != "RESTORE":
        print("已拒绝破坏性恢复：请先审核备份包，再传入 --confirm RESTORE。", file=sys.stderr)
        return 2

    run(compose_command(args.compose_file, "stop", "frontend", "backend", "worker"))
    try:
        run(
            compose_command(
                args.compose_file,
                "exec",
                "-T",
                "postgres",
                "pg_restore",
                "-U",
                "rag",
                "-d",
                "personal_rag",
                "--clean",
                "--if-exists",
                "--no-owner",
            ),
            stdin_path=args.bundle / "postgres.dump",
        )
        run(
            compose_command(
                args.compose_file,
                "run",
                "--rm",
                "-T",
                "--no-deps",
                "backend",
                "python",
                "/app/scripts/s3_archive.py",
                "restore",
            ),
            stdin_path=args.bundle / "minio-objects.tar",
        )
    finally:
        run(
            compose_command(args.compose_file, "up", "--wait", "--wait-timeout", "300", "-d"),
            check=False,
        )
    print(json.dumps({"restored": True, "bundle": str(args.bundle)}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"恢复失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
