#!/usr/bin/env python3
"""将许可明确的语料同步到 Production Compose，并记录哈希证据。"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen


TERMINAL = {"succeeded", "failed", "cancelled"}


class Session:
    def __init__(self, base_url: str, password_file: Path):
        self.base_url = base_url.rstrip("/") + "/"
        login, headers = self.request(
            "api/auth/login",
            method="POST",
            payload={
                "password": password_file.read_text(encoding="utf-8").strip()
            },
            authenticated=False,
        )
        session = login.get("session") if isinstance(login.get("session"), dict) else {}
        self.csrf = str(session.get("csrf_token") or "")
        self.cookie = str(headers.get("Set-Cookie") or "").split(";", 1)[0]
        if not self.csrf or not self.cookie:
            raise RuntimeError("生产环境登录未返回会话凭据")

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict | None = None,
        authenticated: bool = True,
        timeout: float = 180,
    ) -> tuple[dict, object]:
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers.update({"Cookie": self.cookie, "X-CSRF-Token": self.csrf})
        for attempt in range(6):
            request = Request(
                urljoin(self.base_url, path),
                data=json.dumps(payload).encode() if payload is not None else None,
                method=method,
                headers=headers,
            )
            try:
                with urlopen(request, timeout=timeout) as response:
                    return json.load(response), response.headers
            except HTTPError as exc:
                if exc.code not in {502, 503, 504} or attempt == 5:
                    raise
            except (TimeoutError, URLError, OSError):
                if attempt == 5:
                    raise
            time.sleep(min(2**attempt, 10))
        raise RuntimeError("生产环境验收重试流程进入了不可达状态")


def load_manifest(path: Path) -> tuple[dict, set[str]]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    documents = manifest.get("documents")
    if not isinstance(documents, list) or len(documents) != 200:
        raise ValueError("生产环境验收要求语料必须恰好包含 200 份文档")
    hashes = {str(item.get("sha256") or "") for item in documents}
    if "" in hashes or len(hashes) != 200:
        raise ValueError("语料清单中的哈希必须完整且唯一")
    return manifest, hashes


def ensure_source(session: Session, relative_path: str) -> dict:
    payload, _ = session.request("api/sources")
    sources = payload.get("sources") if isinstance(payload.get("sources"), list) else []
    existing = next(
        (
            source
            for source in sources
            if source.get("type") == "local_directory"
            and source.get("config", {}).get("relative_path") == relative_path
        ),
        None,
    )
    if existing:
        return existing
    roots = payload.get("capabilities", {}).get("directory_roots", [])
    if not roots:
        raise RuntimeError("生产服务未提供可用的数据源根目录")
    created, _ = session.request(
        "api/sources",
        method="POST",
        payload={
            "type": "local_directory",
            "name": "Licensed production validation corpus",
            "knowledge_base_id": "default",
            "config": {
                "root_id": roots[0]["id"],
                "relative_path": relative_path,
                "recursive": True,
            },
            "enabled": True,
        },
    )
    return created["source"]


def wait_for_jobs(session: Session, *, timeout_seconds: float) -> dict:
    deadline = time.monotonic() + timeout_seconds
    latest: list[dict] = []
    manually_retried: set[str] = set()
    while time.monotonic() < deadline:
        payload, _ = session.request("api/index-jobs?limit=500")
        latest = payload.get("jobs") if isinstance(payload.get("jobs"), list) else []
        for job in latest[:200]:
            job_id = str(job.get("id") or "")
            if job.get("status") == "failed" and job_id and job_id not in manually_retried:
                session.request(
                    f"api/index-jobs/{quote(job_id)}/retry",
                    method="POST",
                    payload={},
                )
                manually_retried.add(job_id)
        if len(latest) >= 200 and all(
            str(job.get("status") or "") in TERMINAL for job in latest[:200]
        ):
            break
        time.sleep(5)
    counts: dict[str, int] = {}
    for job in latest:
        status = str(job.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return {
        "jobs": latest,
        "counts": counts,
        "timed_out": time.monotonic() >= deadline,
        "manual_retry_count": len(manually_retried),
    }


def validate(
    *,
    session: Session,
    manifest_path: Path,
    relative_path: str,
    timeout_seconds: float,
) -> dict:
    manifest, expected_hashes = load_manifest(manifest_path)
    source = ensure_source(session, relative_path)
    sync, _ = session.request(
        f"api/sources/{quote(str(source['id']))}/sync",
        method="POST",
        payload={},
        timeout=600,
    )
    jobs = wait_for_jobs(session, timeout_seconds=timeout_seconds)
    source_detail, _ = session.request(f"api/sources/{quote(str(source['id']))}")
    documents_payload, _ = session.request("api/documents")
    documents = (
        documents_payload.get("documents")
        if isinstance(documents_payload.get("documents"), list)
        else []
    )
    indexed_hashes = {
        str(document.get("metadata", {}).get("content_hash") or "")
        for document in documents
    }
    indexed_hashes.discard("")
    items = source_detail.get("items") if isinstance(source_detail.get("items"), list) else []
    active_items = [item for item in items if item.get("status") == "active" and item.get("document_id")]
    hashes_match = indexed_hashes == expected_hashes
    passed = (
        sync.get("accepted") is True
        and jobs["counts"].get("succeeded") == 200
        and len(active_items) == 200
        and len(documents) == 200
        and hashes_match
    )
    return {
        "schema_version": 1,
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "passed": passed,
        "source_id": source["id"],
        "sync_run_id": sync.get("sync_run", {}).get("id", ""),
        "licensed_materials": int(manifest.get("licensed_materials") or 0),
        "expected_documents": len(expected_hashes),
        "indexed_documents": len(documents),
        "active_source_items": len(active_items),
        "job_counts": jobs["counts"],
        "manual_retry_count": jobs["manual_retry_count"],
        "timed_out": jobs["timed_out"],
        "hashes_match": hashes_match,
        "corpus_sha256": sorted(indexed_hashes) if hashes_match else [],
        "document_ids": sorted(str(item.get("id") or "") for item in documents),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="验证真实生产语料")
    parser.add_argument("--base-url", default="http://127.0.0.1:5173")
    parser.add_argument(
        "--password-file", type=Path, default=Path("secrets/operator_password")
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/sources/real-corpus/corpus-manifest.json"),
    )
    parser.add_argument("--relative-path", default="real-corpus")
    parser.add_argument("--timeout-seconds", type=float, default=7_200)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/validation/indexing-summary.json"),
    )
    args = parser.parse_args()
    session = Session(
        args.base_url,
        args.password_file.expanduser().resolve(),
    )
    report = validate(
        session=session,
        manifest_path=args.manifest.expanduser().resolve(),
        relative_path=args.relative_path,
        timeout_seconds=max(60, args.timeout_seconds),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
