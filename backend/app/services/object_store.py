from __future__ import annotations

import hashlib
import os
import socket
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class StoredObject:
    sha256: str
    object_key: str
    size_bytes: int
    path: Path | None


class MalwareDetected(ValueError):
    pass


class ObjectStore(Protocol):
    def put_file(self, source: str | Path) -> StoredObject: ...
    def put_bytes(self, payload: bytes) -> StoredObject: ...
    def path_for(self, object_key: str) -> Path: ...
    def read_bytes(self, object_key: str) -> bytes: ...
    def delete(self, object_key: str) -> bool: ...
    def health(self) -> bool: ...


class ContentScanner(Protocol):
    def scan_bytes(self, payload: bytes) -> None: ...


class LocalObjectStore:
    """Content-addressed local object storage with atomic writes.

    Object keys never contain user supplied filenames. Database records retain
    display names and media types separately from the filesystem path.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put_file(self, source: str | Path) -> StoredObject:
        source_path = Path(source)
        digest = hashlib.sha256()
        size = 0
        with source_path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
                size += len(block)
        return self._persist(source_path, digest.hexdigest(), size)

    def put_bytes(self, payload: bytes) -> StoredObject:
        sha256 = hashlib.sha256(payload).hexdigest()
        object_key = self._key(sha256)
        destination = self.path_for(object_key)
        if destination.is_file():
            return StoredObject(sha256, object_key, destination.stat().st_size, destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="object-", dir=str(destination.parent))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return StoredObject(sha256, object_key, len(payload), destination)

    def path_for(self, object_key: str) -> Path:
        normalized = Path(object_key)
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ValueError("Invalid object key")
        candidate = (self.root / normalized).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("Invalid object key")
        return candidate

    def delete(self, object_key: str) -> bool:
        path = self.path_for(object_key)
        if not path.is_file():
            return False
        path.unlink()
        try:
            path.parent.rmdir()
        except OSError:
            pass
        return True

    def read_bytes(self, object_key: str) -> bytes:
        return self.path_for(object_key).read_bytes()

    def health(self) -> bool:
        return self.root.is_dir() and os.access(self.root, os.R_OK | os.W_OK)

    def _persist(self, source: Path, sha256: str, size: int) -> StoredObject:
        object_key = self._key(sha256)
        destination = self.path_for(object_key)
        if destination.is_file():
            return StoredObject(sha256, object_key, destination.stat().st_size, destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="object-", dir=str(destination.parent))
        try:
            with source.open("rb") as reader, os.fdopen(fd, "wb") as writer:
                for block in iter(lambda: reader.read(1024 * 1024), b""):
                    writer.write(block)
                writer.flush()
                os.fsync(writer.fileno())
            os.replace(temporary, destination)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return StoredObject(sha256, object_key, size, destination)

    @staticmethod
    def _key(sha256: str) -> str:
        return f"{sha256[:2]}/{sha256}"


class S3ObjectStore:
    """Content-addressed S3-compatible store with a bounded local read cache."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
        cache_root: str | Path = "./data/object-cache",
        client=None,
    ):
        if not endpoint_url or not bucket:
            raise ValueError("S3 endpoint and bucket are required")
        if client is None:
            try:
                import boto3
            except ImportError as exc:
                raise RuntimeError("Install boto3 to use S3ObjectStore") from exc
            client = boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                region_name=region,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
            )
        self.client = client
        self.bucket = bucket
        self.cache = LocalObjectStore(cache_root)
        self.client.head_bucket(Bucket=bucket)

    def put_file(self, source: str | Path) -> StoredObject:
        source_path = Path(source)
        payload = source_path.read_bytes()
        return self.put_bytes(payload)

    def put_bytes(self, payload: bytes) -> StoredObject:
        sha256 = hashlib.sha256(payload).hexdigest()
        object_key = LocalObjectStore._key(sha256)
        try:
            self.client.head_object(Bucket=self.bucket, Key=object_key)
        except Exception:
            self.client.put_object(
                Bucket=self.bucket,
                Key=object_key,
                Body=payload,
                ContentType="application/octet-stream",
                Metadata={"sha256": sha256},
            )
        cached = self.cache.put_bytes(payload)
        return StoredObject(sha256, object_key, len(payload), cached.path)

    def path_for(self, object_key: str) -> Path:
        cached = self.cache.path_for(object_key)
        if cached.is_file():
            return cached
        response = self.client.get_object(Bucket=self.bucket, Key=object_key)
        payload = response["Body"].read()
        stored = self.cache.put_bytes(payload)
        if stored.object_key != object_key:
            raise ValueError("S3 object checksum does not match its content-addressed key")
        return self.cache.path_for(object_key)

    def read_bytes(self, object_key: str) -> bytes:
        return self.path_for(object_key).read_bytes()

    def delete(self, object_key: str) -> bool:
        self.client.delete_object(Bucket=self.bucket, Key=object_key)
        self.cache.delete(object_key)
        return True

    def health(self) -> bool:
        self.client.head_bucket(Bucket=self.bucket)
        return True


class ClamAVScanner:
    """Minimal clamd INSTREAM client; payloads are never written by the scanner."""

    def __init__(self, host: str, port: int = 3310, timeout_seconds: float = 10.0):
        if not host:
            raise ValueError("CLAMAV_HOST is required")
        self.host = host
        self.port = int(port)
        self.timeout_seconds = float(timeout_seconds)

    def scan_bytes(self, payload: bytes) -> None:
        with socket.create_connection(
            (self.host, self.port),
            timeout=self.timeout_seconds,
        ) as connection:
            connection.sendall(b"zINSTREAM\0")
            for offset in range(0, len(payload), 1024 * 1024):
                block = payload[offset : offset + 1024 * 1024]
                connection.sendall(len(block).to_bytes(4, "big"))
                connection.sendall(block)
            connection.sendall((0).to_bytes(4, "big"))
            response = connection.recv(4096).decode("utf-8", errors="replace")
        if "FOUND" in response:
            raise MalwareDetected("Upload rejected by malware scanner")
        if "OK" not in response:
            raise RuntimeError("Malware scanner returned an indeterminate result")

    def health(self) -> bool:
        with socket.create_connection(
            (self.host, self.port),
            timeout=self.timeout_seconds,
        ) as connection:
            connection.sendall(b"zPING\0")
            response = connection.recv(128).decode("utf-8", errors="replace")
        return "PONG" in response


class ScannedObjectStore:
    def __init__(self, store: ObjectStore, scanner: ContentScanner):
        self.store = store
        self.scanner = scanner

    def put_file(self, source: str | Path) -> StoredObject:
        payload = Path(source).read_bytes()
        return self.put_bytes(payload)

    def put_bytes(self, payload: bytes) -> StoredObject:
        self.scanner.scan_bytes(payload)
        return self.store.put_bytes(payload)

    def path_for(self, object_key: str) -> Path:
        return self.store.path_for(object_key)

    def read_bytes(self, object_key: str) -> bytes:
        return self.store.read_bytes(object_key)

    def delete(self, object_key: str) -> bool:
        return self.store.delete(object_key)

    def health(self) -> bool:
        return self.store.health() and self.scanner.health()
