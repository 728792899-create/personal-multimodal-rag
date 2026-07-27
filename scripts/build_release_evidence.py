#!/usr/bin/env python3
"""根据可审计的本地产物生成私有 1.0 就绪度清单。"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.soak_monitor import verify_evidence
except ModuleNotFoundError:  # Direct `python scripts/...` execution.
    from soak_monitor import verify_evidence


QUALITY_KEYS = (
    "recall_at_5",
    "mrr",
    "citation_accuracy",
    "citation_coverage",
    "refusal_accuracy",
    "answer_acceptance",
)


def load(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def build(evidence_dir: Path, corpus_manifest: Path) -> dict:
    corpus = load(corpus_manifest)
    documents = (
        corpus.get("documents")
        if isinstance(corpus.get("documents"), list)
        else []
    )
    licensed_materials = int(corpus.get("licensed_materials") or 0)
    indexing = load(evidence_dir / "indexing-summary.json")
    annotations = load(evidence_dir / "annotation-summary.json")
    usage = load(evidence_dir / "usage-summary.json")
    restore = load(evidence_dir / "restore-summary.json")
    chaos = load(evidence_dir / "chaos-summary.json")
    quality = load(evidence_dir / "real-benchmark.json")
    soak_state = load(evidence_dir / "soak-state.json")
    chain_valid = False
    try:
        chain_valid = bool(verify_evidence(evidence_dir).get("eligible"))
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        pass
    continuous_seconds = (
        int(soak_state.get("continuous_seconds") or 0) if chain_valid else 0
    )
    indexed_hashes = indexing.get("corpus_sha256")
    expected_hashes = {str(item.get("sha256") or "") for item in documents}
    hash_match = (
        isinstance(indexed_hashes, list)
        and set(map(str, indexed_hashes)) == expected_hashes
        and len(expected_hashes) == len(documents)
    )
    return {
        "schema_version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "corpus": {
            "licensed_materials": licensed_materials,
            "non_fixture_documents": (
                int(indexing.get("indexed_documents") or 0) if hash_match else 0
            ),
            "annotated_questions": int(
                annotations.get("human_reviewed") or 0
            ),
            "licenses": sorted(
                {
                    str(item.get("license_name") or "")
                    for item in documents
                    if item.get("license_name")
                }
            ),
        },
        "usage": {
            "real_questions": int(
                usage.get("human_originated_questions") or 0
            )
        },
        "operations": {
            "soak_days": round(continuous_seconds / 86_400, 6),
            "restore_drill_passed": restore.get("passed") is True,
            "no_data_loss_defect": (
                restore.get("passed") is True
                and chaos.get("passed") is True
                and chain_valid
                and continuous_seconds >= 14 * 86_400
            ),
        },
        "quality": {
            key: float(quality.get(key) or 0) for key in QUALITY_KEYS
        },
        "audit": {
            "corpus_manifest_present": bool(documents),
            "indexed_hashes_match": hash_match,
            "soak_chain_valid": chain_valid,
            "soak_samples": int(soak_state.get("sample_count") or 0),
            "restore_report_present": bool(restore),
            "chaos_report_present": bool(chaos),
        },
    }


def atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="根据真实产物生成发布证据"
    )
    parser.add_argument(
        "--evidence-dir", type=Path, default=Path("data/validation")
    )
    parser.add_argument(
        "--corpus-manifest",
        type=Path,
        default=Path("data/sources/real-corpus/corpus-manifest.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/validation/release-evidence.json"),
    )
    args = parser.parse_args()
    payload = build(
        args.evidence_dir.expanduser().resolve(),
        args.corpus_manifest.expanduser().resolve(),
    )
    atomic_write(args.output.expanduser().resolve(), payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
