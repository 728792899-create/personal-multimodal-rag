#!/usr/bin/env python3
"""Perform and verify an explicitly destructive PostgreSQL + S3 restore drill."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.chaos_compose import compose
except ModuleNotFoundError:  # Direct script execution.
    from chaos_compose import compose


SNAPSHOT_QUERY = """
SELECT json_build_object(
  'documents', (SELECT count(*) FROM documents),
  'document_ids', (SELECT count(DISTINCT document_id) FROM documents),
  'assets', (SELECT count(*) FROM assets),
  'elements', (SELECT count(*) FROM document_elements),
  'jobs', (SELECT count(*) FROM index_jobs),
  'eval_cases', (SELECT count(*) FROM eval_cases),
  'messages', (SELECT count(*) FROM conversation_messages),
  'operations', (SELECT count(*) FROM operation_logs),
  'vectors', (SELECT count(*) FROM rag_chunks),
  'vector_documents', (SELECT count(DISTINCT document_id) FROM rag_chunks),
  'vector_dimensions', (
    SELECT coalesce(json_agg(DISTINCT vector_dims(embedding)), '[]'::json)
    FROM rag_chunks
  ),
  'joined_citations', (
    SELECT count(*) FROM rag_chunks c JOIN documents d ON d.document_id = c.document_id
  ),
  'sample_object', (
    SELECT json_build_object(
      'object_key', object_key,
      'sha256', sha256,
      'size_bytes', size_bytes
    )
    FROM assets
    WHERE kind = 'source' AND object_key != ''
    ORDER BY asset_id
    LIMIT 1
  )
);
"""


def capture(command: list[str]) -> str:
    result = subprocess.run(
        command,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def compose_command(compose_file: Path, *args: str) -> list[str]:
    return ["docker", "compose", "-f", str(compose_file), *args]


def consistency_snapshot(compose_file: Path) -> dict:
    raw = capture(
        compose_command(
            compose_file,
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "rag",
            "-d",
            "personal_rag",
            "-At",
            "-c",
            SNAPSHOT_QUERY,
        )
    )
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("production consistency snapshot is invalid")
    return payload


def object_action(
    compose_file: Path,
    action: str,
    object_key: str,
) -> dict:
    if action not in {"verify", "delete"}:
        raise ValueError("unsupported object action")
    code = (
        "import hashlib,json,sys;"
        "from app.core.store import object_store;"
        "key=sys.argv[1];"
        + (
            "payload=object_store.read_bytes(key);"
            "print(json.dumps({'exists':True,'bytes':len(payload),"
            "'sha256':hashlib.sha256(payload).hexdigest()}))"
            if action == "verify"
            else "print(json.dumps({'deleted':bool(object_store.delete(key))}))"
        )
    )
    raw = capture(
        compose_command(
            compose_file,
            "run",
            "--rm",
            "-T",
            "--no-deps",
            "backend",
            "python",
            "-c",
            code,
            object_key,
        )
    )
    return json.loads(raw.splitlines()[-1])


def compare_snapshots(before: dict, after: dict, object_report: dict) -> dict:
    counted = (
        "documents",
        "document_ids",
        "assets",
        "elements",
        "jobs",
        "eval_cases",
        "messages",
        "operations",
        "vectors",
        "vector_documents",
        "joined_citations",
    )
    counts_match = all(before.get(key) == after.get(key) for key in counted)
    dimensions_match = (
        before.get("vector_dimensions") == after.get("vector_dimensions")
        and before.get("vector_dimensions") == [768]
    )
    sample = before.get("sample_object")
    object_matches = (
        isinstance(sample, dict)
        and object_report.get("exists") is True
        and object_report.get("sha256") == sample.get("sha256")
        and object_report.get("bytes") == sample.get("size_bytes")
    )
    citations_resolve = (
        int(after.get("vectors") or 0) > 0
        and after.get("joined_citations") == after.get("vectors")
    )
    return {
        "counts_match": counts_match,
        "vector_dimensions_match": dimensions_match,
        "object_hash_match": object_matches,
        "all_vector_citations_resolve": citations_resolve,
        "passed": (
            counts_match
            and dimensions_match
            and object_matches
            and citations_resolve
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--compose-file",
        type=Path,
        default=Path("compose.production.yml"),
    )
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/validation/restore-summary.json"),
    )
    parser.add_argument(
        "--confirm",
        default="",
        help='Required literal "DESTROY_AND_RESTORE"',
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.confirm != "DESTROY_AND_RESTORE":
        print(
            "refusing destructive drill: pass --confirm DESTROY_AND_RESTORE",
            file=sys.stderr,
        )
        return 2
    compose_file = args.compose_file.expanduser().resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bundle = (
        args.backup_dir.expanduser().resolve()
        if args.backup_dir
        else Path("data/validation/backups").resolve() / f"restore-drill-{stamp}"
    )
    before = consistency_snapshot(compose_file)
    sample = before.get("sample_object")
    if not isinstance(sample, dict) or not sample.get("object_key"):
        raise RuntimeError("restore drill requires at least one indexed source object")
    subprocess.run(
        [
            sys.executable,
            "scripts/production_backup.py",
            "--compose-file",
            str(compose_file),
            "--readiness-url",
            "http://127.0.0.1:5173/ready",
            "--output",
            str(bundle),
        ],
        check=True,
    )
    sentinel = f"restore-drill-sentinel-{stamp}"
    compose(
        compose_file,
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "rag",
        "-d",
        "personal_rag",
        "-c",
        (
            "INSERT INTO operation_logs "
            "(operation_id,event_type,level,payload,created_at) VALUES "
            f"('{sentinel}','restore_drill_sentinel','warning','{{}}','{stamp}');"
        ),
    )
    deleted = object_action(
        compose_file,
        "delete",
        str(sample["object_key"]),
    )
    if deleted.get("deleted") is not True:
        raise RuntimeError("failed to delete the selected object before restore")
    subprocess.run(
        [
            sys.executable,
            "scripts/production_restore.py",
            "--compose-file",
            str(compose_file),
            "--bundle",
            str(bundle),
            "--confirm",
            "RESTORE",
        ],
        check=True,
    )
    after = consistency_snapshot(compose_file)
    sentinel_count = int(
        capture(
            compose_command(
                compose_file,
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "rag",
                "-d",
                "personal_rag",
                "-At",
                "-c",
                (
                    "SELECT count(*) FROM operation_logs "
                    f"WHERE operation_id='{sentinel}';"
                ),
            )
        )
        or 0
    )
    object_report = object_action(
        compose_file,
        "verify",
        str(sample["object_key"]),
    )
    checks = compare_snapshots(before, after, object_report)
    report = {
        "schema_version": 1,
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "passed": checks["passed"] and sentinel_count == 0,
        "backup_bundle": str(bundle),
        "mutation": {
            "database_sentinel_removed": sentinel_count == 0,
            "object_deleted_before_restore": True,
        },
        "checks": checks,
        "before": before,
        "after": after,
        "restored_object": {
            "bytes": object_report.get("bytes"),
            "sha256": object_report.get("sha256"),
        },
    }
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, output)
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.CalledProcessError,
        json.JSONDecodeError,
    ) as exc:
        print(f"destructive restore drill failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
