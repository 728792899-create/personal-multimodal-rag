from __future__ import annotations

import json
import stat

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
    with pytest.raises(ValueError, match="hash chain"):
        soak_monitor.verify_chain(path)


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
    with pytest.raises(ValidationError, match="only valid"):
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

    with pytest.raises(ValueError, match="unsupported fields"):
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
    assert result["corpus"]["non_fixture_documents"] == 0
    assert result["corpus"]["annotated_questions"] == 0
    assert result["operations"]["soak_days"] == 0
    assert result["operations"]["no_data_loss_defect"] is False
