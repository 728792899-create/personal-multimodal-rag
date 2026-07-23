from __future__ import annotations

from pathlib import Path

import pytest

from app.services.object_store import MalwareDetected, ScannedObjectStore


class MemoryStore:
    def __init__(self):
        self.payloads: dict[str, bytes] = {}

    def put_file(self, source):
        return self.put_bytes(Path(source).read_bytes())

    def put_bytes(self, payload: bytes):
        from app.services.object_store import StoredObject

        self.payloads["ab/object"] = payload
        return StoredObject("ab", "ab/object", len(payload), None)

    def delete(self, object_key: str):
        return self.payloads.pop(object_key, None) is not None

    def read_bytes(self, object_key: str):
        return self.payloads[object_key]


class Scanner:
    def __init__(self, clean: bool):
        self.clean = clean
        self.scanned = 0

    def scan_bytes(self, payload: bytes):
        self.scanned += 1
        if not self.clean:
            raise MalwareDetected("upload rejected by malware scanner")


def test_scanned_store_rejects_before_persisting():
    store = MemoryStore()
    scanner = Scanner(clean=False)
    wrapped = ScannedObjectStore(store, scanner)

    with pytest.raises(MalwareDetected):
        wrapped.put_bytes(b"unsafe")

    assert store.payloads == {}


def test_scanned_store_persists_clean_payload():
    store = MemoryStore()
    scanner = Scanner(clean=True)
    wrapped = ScannedObjectStore(store, scanner)

    saved = wrapped.put_bytes(b"safe")
    assert scanner.scanned == 1
    assert wrapped.read_bytes(saved.object_key) == b"safe"
