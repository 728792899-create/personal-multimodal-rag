#!/usr/bin/env python3
"""根据可审计的本地产物生成私有 v1.0 RC 就绪度清单。"""

from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.soak_monitor import verify_evidence
except ModuleNotFoundError:  # Direct `python scripts/...` execution.
    from soak_monitor import verify_evidence


SCHEMA_VERSION = 2
CANDIDATE_VERSION = "1.0.0-rc.1"


def load(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def optional_number(payload: dict, key: str) -> int | float | None:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    if not math.isfinite(numeric):
        return None
    return value


def optional_boolean(payload: dict, key: str) -> bool | None:
    value = payload.get(key)
    return value if isinstance(value, bool) else None


def numeric_mapping(payload: dict, key: str) -> dict[str, int | float] | None:
    value = payload.get(key)
    if not isinstance(value, dict) or not value:
        return None
    result: dict[str, int | float] = {}
    for name, observed in value.items():
        if (
            not isinstance(name, str)
            or isinstance(observed, bool)
            or not isinstance(observed, (int, float))
            or not math.isfinite(float(observed))
        ):
            return None
        result[name] = observed
    return result


def build(evidence_dir: Path, corpus_manifest: Path) -> dict:
    corpus = load(corpus_manifest)
    documents = corpus.get("documents") if isinstance(corpus.get("documents"), list) else []
    indexing = load(evidence_dir / "indexing-summary.json")
    annotations = load(evidence_dir / "annotation-summary.json")
    usage = load(evidence_dir / "usage-summary.json")
    restore = load(evidence_dir / "restore-summary.json")
    chaos = load(evidence_dir / "chaos-summary.json")
    security = load(evidence_dir / "security-summary.json")
    quality = load(evidence_dir / "real-benchmark.json")
    ann = load(evidence_dir / "ann-benchmark.json")
    comparison = load(evidence_dir / "regression-summary.json")
    reranking = load(evidence_dir / "rerank-summary.json")
    performance = load(evidence_dir / "performance-summary.json")
    soak_state = load(evidence_dir / "soak-state.json")

    chain_valid = False
    try:
        chain_valid = bool(verify_evidence(evidence_dir).get("eligible"))
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        pass

    continuous_seconds = optional_number(soak_state, "continuous_seconds") if chain_valid else None
    sample_count = optional_number(soak_state, "sample_count") if chain_valid else None
    success_count = optional_number(soak_state, "success_count") if chain_valid else None
    if success_count is None:
        failure_count = optional_number(soak_state, "failure_count") if chain_valid else None
        if sample_count is not None and failure_count is not None:
            success_count = max(0, sample_count - failure_count)
    availability = (
        success_count / sample_count
        if sample_count is not None and sample_count > 0 and success_count is not None
        else None
    )

    indexed_hashes = indexing.get("corpus_sha256")
    expected_hashes = {str(item.get("sha256") or "") for item in documents if isinstance(item, dict)}
    hash_match = (
        bool(documents)
        and isinstance(indexed_hashes, list)
        and set(map(str, indexed_hashes)) == expected_hashes
        and len(expected_hashes) == len(documents)
    )

    quality_keys = (
        "recall_at_5",
        "mrr_at_10",
        "multihop_chain_at_10",
        "table_recall_at_10",
        "image_recall_at_10",
        "formula_recall_at_10",
        "citation_accuracy",
        "factual_coverage",
        "fabricated_or_invalid_citations",
        "refusal_f1",
        "answerable_false_refusal_rate",
        "blind_test_cases",
        "blind_acceptance_rate",
    )
    performance_keys = (
        "benchmark_chunks",
        "benchmark_concurrency",
        "hnsw_p95_ms",
        "simple_retrieval_p95_ms",
        "complex_retrieval_p95_ms",
        "simple_ttft_p95_ms",
        "complex_ttft_p95_ms",
        "automatic_routing_cost_ratio",
    )
    security_count_keys = (
        "permission_bypass_incidents",
        "index_pollution_incidents",
        "data_loss_incidents",
        "fabricated_citation_incidents",
        "secret_leak_incidents",
        "unresolved_sev1",
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "candidate_version": CANDIDATE_VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "corpus": {
            "licensed_materials": optional_number(corpus, "licensed_materials"),
            "non_fixture_documents": (
                optional_number(indexing, "indexed_documents") if hash_match else None
            ),
            "annotated_questions": optional_number(annotations, "human_reviewed"),
            "locked_regression_questions": optional_number(annotations, "locked_regression"),
            "second_reviewed_questions": optional_number(annotations, "second_reviewed"),
            "label_agreement_kappa": optional_number(annotations, "label_agreement_kappa"),
            "evidence_agreement_f1": optional_number(annotations, "evidence_agreement_f1"),
            "licenses": sorted(
                {
                    str(item.get("license_name") or "")
                    for item in documents
                    if isinstance(item, dict) and item.get("license_name")
                }
            ),
        },
        "usage": {
            "representative_queries": optional_number(usage, "human_originated_questions"),
        },
        "operations": {
            "soak_days": (
                round(float(continuous_seconds) / 86_400, 6)
                if continuous_seconds is not None
                else None
            ),
            "availability": round(float(availability), 8) if availability is not None else None,
            "provider_failure_contract_passed": optional_boolean(
                chaos, "provider_failure_contract_passed"
            ),
            "rbac_authorization_pass_rate": optional_number(
                security, "rbac_authorization_pass_rate"
            ),
            "restore_drill_passed": optional_boolean(restore, "passed"),
            "full_stack_rollback_passed": optional_boolean(
                restore, "full_stack_rollback_passed"
            ),
            "rollback_rto_minutes": optional_number(restore, "rollback_rto_minutes"),
            "source_rpo_lost_records": optional_number(restore, "source_rpo_lost_records"),
            "five_xx_rollback_trigger_verified": optional_boolean(
                chaos, "five_xx_rollback_trigger_verified"
            ),
            **{key: optional_number(security, key) for key in security_count_keys},
        },
        "quality": {key: optional_number(quality, key) for key in quality_keys},
        "ann": {
            "hnsw_recall_at_50": optional_number(ann, "hnsw_recall_at_50"),
            "primary_strata_recall_at_50": numeric_mapping(
                ann, "primary_strata_recall_at_50"
            ),
        },
        "comparison": {
            "difficult_core_best_improvement": optional_number(
                comparison, "difficult_core_best_improvement"
            ),
            "overall_worst_regression": optional_number(
                comparison, "overall_worst_regression"
            ),
        },
        "reranking": {
            "enabled": optional_boolean(reranking, "enabled"),
            "trigger_subset_mrr_improvement": optional_number(
                reranking, "trigger_subset_mrr_improvement"
            ),
            "trigger_rate": optional_number(reranking, "trigger_rate"),
        },
        "performance": {
            key: optional_number(performance, key) for key in performance_keys
        },
        "audit": {
            "corpus_manifest_present": bool(documents),
            "indexed_hashes_match": hash_match,
            "soak_chain_valid": chain_valid,
            "soak_samples": sample_count,
            "source_artifacts": {
                "annotations": bool(annotations),
                "usage": bool(usage),
                "restore": bool(restore),
                "chaos": bool(chaos),
                "security": bool(security),
                "quality": bool(quality),
                "ann": bool(ann),
                "comparison": bool(comparison),
                "reranking": bool(reranking),
                "performance": bool(performance),
            },
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
    parser = argparse.ArgumentParser(description="根据真实产物生成发布证据")
    parser.add_argument("--evidence-dir", type=Path, default=Path("data/validation"))
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
