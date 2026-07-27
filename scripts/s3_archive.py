#!/usr/bin/env python3
"""无需本地暂存，以流式方式备份或恢复 S3 兼容 bucket。"""

from __future__ import annotations

import argparse
import sys
import tarfile
from pathlib import PurePosixPath

ROOT = PurePosixPath(__file__).parents[1]


def safe_object_key(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or value.startswith(("/", "\\"))
        or "\\" in value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("归档中包含不安全的 S3 对象 key。")
    return path.as_posix()


def create_client():
    sys.path.insert(0, str(ROOT / "backend"))
    from app.config import settings

    if not settings.s3_bucket:
        raise ValueError("必须配置 S3_BUCKET。")
    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
    )
    client.head_bucket(Bucket=settings.s3_bucket)
    return client, settings.s3_bucket


def list_objects(client, bucket: str):
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        yield from page.get("Contents", [])


def export_bucket(client, bucket: str, output) -> int:
    count = 0
    with tarfile.open(fileobj=output, mode="w|") as archive:
        for item in list_objects(client, bucket):
            key = safe_object_key(str(item["Key"]))
            size = int(item["Size"])
            response = client.get_object(Bucket=bucket, Key=key)
            info = tarfile.TarInfo(key)
            info.size = size
            info.mode = 0o600
            archive.addfile(info, response["Body"])
            response["Body"].close()
            count += 1
    return count


def _delete_existing(client, bucket: str) -> int:
    pending: list[dict[str, str]] = []
    deleted = 0
    for item in list_objects(client, bucket):
        pending.append({"Key": safe_object_key(str(item["Key"]))})
        if len(pending) == 1000:
            client.delete_objects(Bucket=bucket, Delete={"Objects": pending, "Quiet": True})
            deleted += len(pending)
            pending = []
    if pending:
        client.delete_objects(Bucket=bucket, Delete={"Objects": pending, "Quiet": True})
        deleted += len(pending)
    return deleted


def restore_bucket(client, bucket: str, source) -> tuple[int, int]:
    deleted = _delete_existing(client, bucket)
    restored = 0
    with tarfile.open(fileobj=source, mode="r|*") as archive:
        for member in archive:
            if not member.isfile():
                raise ValueError("S3 归档中只允许包含普通文件。")
            key = safe_object_key(member.name)
            payload = archive.extractfile(member)
            if payload is None:
                raise ValueError("S3 归档成员无法读取。")
            body = payload.read()
            if len(body) != member.size:
                raise ValueError("S3 归档成员大小与 header 不一致。")
            metadata = {}
            digest = PurePosixPath(key).name
            if len(digest) == 64 and all(char in "0123456789abcdef" for char in digest.lower()):
                metadata["sha256"] = digest.lower()
            client.put_object(
                Bucket=bucket,
                Key=key,
                Body=body,
                Metadata=metadata,
            )
            restored += 1
    return deleted, restored


def main() -> int:
    parser = argparse.ArgumentParser(description="以流式方式备份或恢复 S3 bucket")
    parser.add_argument("action", choices=("export", "restore"))
    args = parser.parse_args()
    client, bucket = create_client()
    if args.action == "export":
        count = export_bucket(client, bucket, sys.stdout.buffer)
        print(f"已导出 {count} 个 S3 对象。", file=sys.stderr)
    else:
        deleted, restored = restore_bucket(client, bucket, sys.stdin.buffer)
        print(f"已删除 {deleted} 个并恢复 {restored} 个 S3 对象。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"S3 归档操作失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
