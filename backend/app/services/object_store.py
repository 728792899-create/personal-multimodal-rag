from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StoredObject:
    sha256: str
    object_key: str
    size_bytes: int
    path: Path


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
