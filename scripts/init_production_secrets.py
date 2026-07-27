#!/usr/bin/env python3
"""创建完整的本地生产密钥集，不在终端输出密钥值。"""

from __future__ import annotations

import argparse
import os
import secrets
from pathlib import Path


SECRET_FILES = {
    "postgres_password",
    "metadata_dsn",
    "redis_password",
    "redis_url",
    "s3_access_key",
    "s3_secret_key",
    "admin_password_hash",
    "session_secret",
    "grafana_admin_user",
    "grafana_admin_password",
    "operator_password",
}


def build_secrets() -> dict[str, str]:
    try:
        from argon2 import PasswordHasher
    except ImportError as exc:
        raise RuntimeError(
            "需要安装 argon2-cffi；请运行 `uv run --with argon2-cffi "
            "scripts/init_production_secrets.py`"
        ) from exc
    postgres_password = secrets.token_urlsafe(32)
    redis_password = secrets.token_urlsafe(32)
    operator_password = secrets.token_urlsafe(24)
    return {
        "postgres_password": postgres_password,
        "metadata_dsn": f"postgresql://rag:{postgres_password}@postgres:5432/personal_rag",
        "redis_password": redis_password,
        "redis_url": f"redis://:{redis_password}@redis:6379/0",
        "s3_access_key": f"rag{secrets.token_hex(8)}",
        "s3_secret_key": secrets.token_urlsafe(40),
        "admin_password_hash": PasswordHasher().hash(operator_password),
        "session_secret": secrets.token_urlsafe(64),
        "grafana_admin_user": "admin",
        "grafana_admin_password": secrets.token_urlsafe(32),
        "operator_password": operator_password,
    }


def write_secrets(directory: Path, values: dict[str, str], *, force: bool = False) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    existing = sorted(path.name for path in directory.iterdir() if path.name in SECRET_FILES)
    if existing and not force:
        raise FileExistsError(
            "为保护现有生产密钥，已拒绝覆盖：" + ", ".join(existing)
        )
    written: list[Path] = []
    for name, value in values.items():
        target = directory / name
        temporary = target.with_suffix(".tmp")
        temporary.write_text(value, encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        written.append(target)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化本地生产密钥文件")
    parser.add_argument("--directory", type=Path, default=Path("secrets"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        written = write_secrets(
            args.directory.expanduser().resolve(),
            build_secrets(),
            force=args.force,
        )
    except (RuntimeError, FileExistsError) as exc:
        parser.error(str(exc))
    print(f"已在 {args.directory} 创建 {len(written)} 个密钥文件；密钥值未输出到终端。")
    print(f"管理员登录密码保存在 {args.directory / 'operator_password'}。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
