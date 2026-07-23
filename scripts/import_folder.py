#!/usr/bin/env python3
"""Incrementally enqueue a local folder through the public ingestion API."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx


SUPPORTED = {".txt", ".md", ".markdown", ".pdf", ".docx", ".png", ".jpg", ".jpeg"}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def discover(root: Path, recursive: bool) -> list[Path]:
    iterator = root.rglob("*") if recursive else root.glob("*")
    return sorted(path for path in iterator if path.is_file() and path.suffix.lower() in SUPPORTED)


def upload(path: Path, args, headers: dict[str, str]) -> dict:
    with path.open("rb") as handle, httpx.Client(timeout=args.timeout) as client:
        response = client.post(
            f"{args.api.rstrip('/')}/api/ingestions/file",
            headers=headers,
            data={"knowledge_base_id": args.knowledge_base, "parser_profile": args.parser},
            files={"file": (path.name, handle, "application/octet-stream")},
        )
    response.raise_for_status()
    return response.json()["job"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Incrementally enqueue supported documents")
    parser.add_argument("folder", type=Path)
    parser.add_argument("--api", default="http://127.0.0.1:8010")
    parser.add_argument("--knowledge-base", default="default")
    parser.add_argument("--parser", choices=["builtin", "auto", "mineru", "docling", "paddleocr"], default="builtin")
    parser.add_argument("--recursive", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-concurrency", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()

    root = args.folder.expanduser().resolve()
    if not root.is_dir():
        parser.error(f"Folder does not exist: {root}")
    manifest_path = args.manifest or root / ".rag-import-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        manifest = {"version": 1, "files": {}}
    candidates = []
    for path in discover(root, args.recursive):
        content_hash = digest(path)
        relative = str(path.relative_to(root))
        if manifest.get("files", {}).get(relative, {}).get("sha256") == content_hash:
            continue
        candidates.append((path, relative, content_hash))

    if args.dry_run:
        print(json.dumps({"root": str(root), "count": len(candidates), "files": [item[1] for item in candidates]}, ensure_ascii=False, indent=2))
        return 0

    token = os.getenv("API_AUTH_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    failures: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, min(args.max_concurrency, 8))) as pool:
        futures = {pool.submit(upload, path, args, headers): (relative, content_hash) for path, relative, content_hash in candidates}
        for future in as_completed(futures):
            relative, content_hash = futures[future]
            try:
                job = future.result()
                manifest.setdefault("files", {})[relative] = {"sha256": content_hash, "job_id": job["id"]}
                print(f"queued\t{relative}\t{job['id']}")
            except Exception as exc:
                failures.append({"file": relative, "error": f"{type(exc).__name__}: {exc}"})
                print(f"failed\t{relative}\t{type(exc).__name__}")
    temporary = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, manifest_path)
    if failures:
        print(json.dumps({"failures": failures}, ensure_ascii=False, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
