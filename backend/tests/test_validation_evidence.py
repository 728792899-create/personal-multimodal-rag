from __future__ import annotations

import json
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models.schemas import ConversationMessageRequest
from app.services.document_registry import DocumentRegistry
from scripts import (
    build_release_evidence,
    curate_real_corpus,
    init_production_secrets,
    prepare_annotation_queue,
    run_production_restore_drill,
    snapshot_usage_evidence,
    soak_monitor,
)


def test_secret_initializer_is_private_and_refuses_overwrite(tmp_path):
    values = {
        name: f"value-{index}"
        for index, name in enumerate(sorted(init_production_secrets.SECRET_FILES))
    }
    written = init_production_secrets.write_secrets(tmp_path, values)
    assert {path.name for path in written} == init_production_secrets.SECRET_FILES
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in written)
    with pytest.raises(FileExistsError):
        init_production_secrets.write_secrets(tmp_path, values)


def test_soak_monitor_builds_and_verifies_hash_chain(tmp_path, monkeypatch):
    calls = iter(
        [
            (200, {"ready": True}, 2.5),
            (
                200,
                {
                    "ready": True,
                    "configured": True,
                    "mode": "production",
                    "components": {"metadata": {"healthy": True}},
                },
                3.5,
            ),
            (503, {"ready": False}, 1.0),
            (
                503,
                {
                    "ready": False,
                    "configured": True,
                    "mode": "production",
                    "components": {"metadata": {"healthy": False}},
                },
                1.0,
            ),
        ]
    )
    monkeypatch.setattr(soak_monitor, "fetch_json", lambda *_args, **_kwargs: next(calls))
    healthy = soak_monitor.sample(
        tmp_path,
        health_url="http://health",
        readiness_url="http://readiness",
        expected_mode="production",
        timeout=1,
        maximum_gap_seconds=30,
    )
    failed = soak_monitor.sample(
        tmp_path,
        health_url="http://health",
        readiness_url="http://readiness",
        expected_mode="production",
        timeout=1,
        maximum_gap_seconds=30,
    )
    assert healthy["event"]["healthy"] is True
    assert failed["event"]["healthy"] is False
    assert failed["state"]["sample_count"] == 2
    assert failed["state"]["failure_count"] == 1
    assert soak_monitor.verify_chain(tmp_path / "soak-events.jsonl")["events"] == 2


def test_soak_monitor_uses_public_ready_payload_without_private_report(
    tmp_path, monkeypatch
):
    responses = iter(
        [
            (
                200,
                {
                    "status": "ready",
                    "runtime": {
                        "ready": True,
                        "configured": True,
                        "mode": "production",
                        "components": {"metadata": {"healthy": True}},
                    },
                },
                4.0,
            )
        ]
    )
    monkeypatch.setattr(soak_monitor, "fetch_json", lambda *_args, **_kwargs: next(responses))

    result = soak_monitor.sample(
        tmp_path,
        health_url="http://health",
        readiness_url="",
        expected_mode="production",
        timeout=1,
        maximum_gap_seconds=30,
    )

    assert result["event"]["healthy"] is True
    assert result["event"]["readiness_status"] == 200
    assert result["event"]["component_health"] == {"metadata": True}


def test_soak_monitor_rejects_tampered_evidence(tmp_path, monkeypatch):
    responses = iter(
        [
            (200, {"ready": True}, 1.0),
            (
                200,
                {"ready": True, "configured": True, "mode": "production", "components": {}},
                1.0,
            ),
        ]
    )
    monkeypatch.setattr(soak_monitor, "fetch_json", lambda *_args, **_kwargs: next(responses))
    soak_monitor.sample(
        tmp_path,
        health_url="http://health",
        readiness_url="http://readiness",
        expected_mode="production",
        timeout=1,
        maximum_gap_seconds=30,
    )
    path = tmp_path / "soak-events.jsonl"
    event = json.loads(path.read_text(encoding="utf-8"))
    event["healthy"] = False
    path.write_text(json.dumps(event) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="哈希链"):
        soak_monitor.verify_chain(path)


def test_soak_verification_requires_fresh_wall_clock_and_consistent_state(
    tmp_path, monkeypatch
):
    observed = datetime(2026, 7, 25, 5, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(soak_monitor, "utc_now", lambda: observed)
    monkeypatch.setattr(
        soak_monitor,
        "fetch_json",
        lambda *_args, **_kwargs: (
            200,
            {
                "status": "ready",
                "runtime": {
                    "ready": True,
                    "configured": True,
                    "mode": "production",
                    "components": {"metadata": {"healthy": True}},
                },
            },
            1.0,
        ),
    )
    soak_monitor.sample(
        tmp_path,
        health_url="http://health",
        readiness_url="",
        expected_mode="production",
        timeout=1,
        maximum_gap_seconds=30,
    )

    current = soak_monitor.verify_evidence(
        tmp_path,
        now=observed + timedelta(seconds=10),
        maximum_age_seconds=30,
    )
    assert current["eligible"] is True
    assert current["wall_clock_fresh"] is True
    assert current["state_consistent"] is True

    stale = soak_monitor.verify_evidence(
        tmp_path,
        now=observed + timedelta(seconds=31),
        maximum_age_seconds=30,
    )
    assert stale["eligible"] is False
    assert stale["wall_clock_fresh"] is False
    assert stale["last_event_age_seconds"] == 31

    state_path = tmp_path / "soak-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["last_event_hash"] = "mismatched"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    inconsistent = soak_monitor.verify_evidence(
        tmp_path,
        now=observed + timedelta(seconds=10),
        maximum_age_seconds=30,
    )
    assert inconsistent["eligible"] is False
    assert inconsistent["state_consistent"] is False


def test_frontend_proxy_resolves_backend_at_request_time():
    nginx = (
        Path(__file__).resolve().parents[2] / "frontend" / "nginx.conf"
    ).read_text(encoding="utf-8")

    assert "resolver 127.0.0.11" in nginx
    assert "set $backend_upstream backend:8010;" in nginx
    assert "proxy_pass http://$backend_upstream" in nginx
    assert "location ~ ^/api/conversations/[^/]+/messages:stream$" in nginx
    assert "proxy_buffering off;" in nginx
    assert "proxy_cache off;" in nginx
    assert "proxy_read_timeout 210s;" in nginx


def test_real_corpus_manifest_requires_unique_licensed_sources(tmp_path):
    payload = b"# Licensed live article\n\n" + b"evidence " * 200
    document = tmp_path / "en-1-evidence.md"
    document.write_bytes(payload)
    manifest = {
        "documents": [
            {
                "file": document.name,
                "sha256": curate_real_corpus.sha256(payload),
                "source_url": "https://en.wikipedia.org/wiki/Evidence",
                "license_name": "CC BY-SA",
                "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
            }
        ]
    }
    result = curate_real_corpus.verify_manifest(tmp_path, manifest, minimum_documents=1)
    assert result["valid"] is True
    manifest["documents"][0]["license_url"] = ""
    assert curate_real_corpus.verify_manifest(
        tmp_path, manifest, minimum_documents=1
    )["valid"] is False


def test_annotation_queue_is_deterministic_and_never_claims_human_review(tmp_path):
    document = tmp_path / "guide.md"
    document.write_text("# Retrieval\n\nUse hybrid retrieval.", encoding="utf-8")
    digest = curate_real_corpus.sha256(document.read_bytes())
    manifest = tmp_path / "corpus-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "file": document.name,
                        "title": "RAG guide",
                        "language": "en",
                        "source_url": "https://example.test/guide",
                        "sha256": digest,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "annotations.jsonl"

    first = prepare_annotation_queue.build_queue(manifest, output, limit=1)
    second = prepare_annotation_queue.build_queue(manifest, output, limit=1)

    assert first == second
    assert first[0]["counts_as_human_annotation"] is False
    assert first[0]["status"] == "draft"
    assert "Retrieval" in first[0]["question"]


def test_real_usage_requires_explicit_human_attestation():
    with pytest.raises(ValidationError, match="human-originated"):
        ConversationMessageRequest(
            question="A question",
            record_as_real_usage=True,
        )
    with pytest.raises(ValidationError, match="只有启用 record_as_real_usage"):
        ConversationMessageRequest(
            question="A question",
            usage_attestation="human-originated",
        )
    payload = ConversationMessageRequest(
        question="A question",
        record_as_real_usage=True,
        usage_attestation="human-originated",
    )
    assert payload.record_as_real_usage is True


def test_real_usage_summary_counts_only_provenance_backed_user_messages():
    registry = DocumentRegistry(":memory:")
    conversation = registry.create_conversation("Evidence", ["default"])
    registry.save_conversation_message(
        conversation["id"],
        "user",
        "not attested",
        metadata={},
    )
    registry.save_conversation_message(
        conversation["id"],
        "user",
        "confirmed",
        metadata={
            "usage_evidence": {
                "attestation": "human-originated",
                "recorded_at": "2026-07-23T08:00:00+00:00",
                "user_id": "owner",
                "workspace_id": "default",
            }
        },
    )
    registry.save_conversation_message(
        conversation["id"],
        "assistant",
        "answer",
        metadata={
            "usage_evidence": {
                "attestation": "human-originated",
                "user_id": "owner",
                "workspace_id": "default",
            }
        },
    )

    summary = registry.real_usage_summary()

    assert summary["human_originated_questions"] == 1
    assert summary["remaining_for_1_0"] == 99
    assert summary["conversation_count"] == 1


def test_usage_snapshot_rejects_question_content():
    class Session:
        @staticmethod
        def request(_path):
            return {
                "human_originated_questions": 1,
                "target": 100,
                "remaining_for_1_0": 99,
                "conversation_count": 1,
                "first_recorded_at": "2026-07-23T08:00:00+00:00",
                "last_recorded_at": "2026-07-23T08:00:00+00:00",
                "attestation": "human-originated",
                "question": "private text",
            }, {}

    with pytest.raises(ValueError, match="不受支持的字段"):
        snapshot_usage_evidence.snapshot(Session())


def test_restore_evidence_requires_counts_vectors_objects_and_citations():
    before = {
        "documents": 200,
        "document_ids": 200,
        "assets": 200,
        "elements": 500,
        "jobs": 200,
        "eval_cases": 200,
        "messages": 0,
        "operations": 10,
        "vectors": 1_000,
        "vector_documents": 200,
        "joined_citations": 1_000,
        "vector_dimensions": [768],
        "sample_object": {
            "sha256": "a" * 64,
            "size_bytes": 42,
        },
    }
    report = run_production_restore_drill.compare_snapshots(
        before,
        dict(before),
        {"exists": True, "sha256": "a" * 64, "bytes": 42},
    )
    assert report["passed"] is True

    wrong_dimension = {**before, "vector_dimensions": [1536]}
    assert run_production_restore_drill.compare_snapshots(
        wrong_dimension,
        dict(wrong_dimension),
        {"exists": True, "sha256": "a" * 64, "bytes": 42},
    )["passed"] is False


def test_release_evidence_refuses_to_count_unmatched_or_unreviewed_artifacts(tmp_path):
    corpus_dir = tmp_path / "corpus"
    evidence_dir = tmp_path / "evidence"
    corpus_dir.mkdir()
    evidence_dir.mkdir()
    manifest = corpus_dir / "corpus-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "licensed_materials": 20,
                "documents": [
                    {"sha256": "expected", "license_name": "MIT"}
                ],
            }
        ),
        encoding="utf-8",
    )
    (evidence_dir / "indexing-summary.json").write_text(
        json.dumps(
            {"indexed_documents": 200, "corpus_sha256": ["different"]}
        ),
        encoding="utf-8",
    )
    (evidence_dir / "annotation-summary.json").write_text(
        json.dumps({"drafts": 200, "human_reviewed": 0}),
        encoding="utf-8",
    )

    result = build_release_evidence.build(evidence_dir, manifest)

    assert result["corpus"]["licensed_materials"] == 20
    assert result["corpus"]["non_fixture_documents"] is None
    assert result["corpus"]["annotated_questions"] == 0
    assert result["operations"]["soak_days"] is None
    assert result["operations"]["data_loss_incidents"] is None


def test_release_evidence_uses_current_verified_soak_window(tmp_path, monkeypatch):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    manifest = tmp_path / "corpus-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "licensed_materials": 1,
                "documents": [{"sha256": "expected", "license_name": "MIT"}],
            }
        ),
        encoding="utf-8",
    )
    (evidence_dir / "indexing-summary.json").write_text(
        json.dumps(
            {"indexed_documents": 1, "corpus_sha256": ["expected"]}
        ),
        encoding="utf-8",
    )
    (evidence_dir / "restore-summary.json").write_text(
        json.dumps({"passed": True}),
        encoding="utf-8",
    )
    (evidence_dir / "chaos-summary.json").write_text(
        json.dumps({"passed": True}),
        encoding="utf-8",
    )
    (evidence_dir / "soak-state.json").write_text(
        json.dumps(
            {
                "continuous_seconds": 14 * 86_400,
                "failure_count": 4,
                "sample_count": 4_100,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        build_release_evidence,
        "verify_evidence",
        lambda _directory: {"eligible": True},
    )

    result = build_release_evidence.build(evidence_dir, manifest)

    assert result["operations"]["soak_days"] == 14
    assert result["operations"]["availability"] == pytest.approx(
        (4_100 - 4) / 4_100
    )
    assert result["audit"]["soak_chain_valid"] is True


def test_release_evidence_collects_all_rc_gate_artifacts(tmp_path, monkeypatch):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    manifest = tmp_path / "corpus-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "licensed_materials": 20,
                "documents": [{"sha256": "expected", "license_name": "MIT"}],
            }
        ),
        encoding="utf-8",
    )
    artifacts = {
        "indexing-summary.json": {
            "indexed_documents": 200,
            "corpus_sha256": ["expected"],
        },
        "annotation-summary.json": {
            "human_reviewed": 200,
            "locked_regression": 140,
            "second_reviewed": 40,
            "label_agreement_kappa": 0.76,
            "evidence_agreement_f1": 0.81,
        },
        "usage-summary.json": {"human_originated_questions": 500},
        "soak-state.json": {
            "continuous_seconds": 14 * 86_400,
            "sample_count": 1_000,
            "success_count": 999,
        },
        "restore-summary.json": {
            "passed": True,
            "full_stack_rollback_passed": True,
            "rollback_rto_minutes": 8,
            "source_rpo_lost_records": 0,
        },
        "chaos-summary.json": {
            "provider_failure_contract_passed": True,
            "five_xx_rollback_trigger_verified": True,
        },
        "security-summary.json": {
            "rbac_authorization_pass_rate": 1.0,
            "permission_bypass_incidents": 0,
            "index_pollution_incidents": 0,
            "data_loss_incidents": 0,
            "fabricated_citation_incidents": 0,
            "secret_leak_incidents": 0,
            "unresolved_sev1": 0,
        },
        "real-benchmark.json": {
            "recall_at_5": 0.91,
            "mrr_at_10": 0.79,
            "multihop_chain_at_10": 0.81,
            "table_recall_at_10": 0.86,
            "image_recall_at_10": 0.86,
            "formula_recall_at_10": 0.86,
            "citation_accuracy": 0.91,
            "factual_coverage": 0.91,
            "fabricated_or_invalid_citations": 0,
            "refusal_f1": 0.89,
            "answerable_false_refusal_rate": 0.07,
            "blind_test_cases": 100,
            "blind_acceptance_rate": 0.86,
        },
        "ann-benchmark.json": {
            "hnsw_recall_at_50": 0.99,
            "primary_strata_recall_at_50": {"table": 0.96},
        },
        "regression-summary.json": {
            "difficult_core_best_improvement": 0.06,
            "overall_worst_regression": 0.005,
        },
        "rerank-summary.json": {
            "enabled": True,
            "trigger_subset_mrr_improvement": 0.04,
            "trigger_rate": 0.40,
        },
        "performance-summary.json": {
            "benchmark_chunks": 50_000,
            "benchmark_concurrency": 5,
            "hnsw_p95_ms": 190,
            "simple_retrieval_p95_ms": 1_900,
            "complex_retrieval_p95_ms": 5_900,
            "simple_ttft_p95_ms": 5_900,
            "complex_ttft_p95_ms": 9_900,
            "automatic_routing_cost_ratio": 1.30,
        },
    }
    for filename, payload in artifacts.items():
        (evidence_dir / filename).write_text(
            json.dumps(payload), encoding="utf-8"
        )
    monkeypatch.setattr(
        build_release_evidence,
        "verify_evidence",
        lambda _directory: {"eligible": True},
    )

    result = build_release_evidence.build(evidence_dir, manifest)

    assert result["schema_version"] == 2
    assert result["candidate_version"] == "1.0.0-rc.1"
    assert result["quality"]["multihop_chain_at_10"] == 0.81
    assert result["ann"]["primary_strata_recall_at_50"] == {"table": 0.96}
    assert result["reranking"]["enabled"] is True
    assert result["performance"]["automatic_routing_cost_ratio"] == 1.30
    assert result["operations"]["availability"] == 0.999
