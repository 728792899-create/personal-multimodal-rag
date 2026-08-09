from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.services.index_versions import IndexVersionRegistry, REQUIRED_VALIDATIONS


def passed_checklist() -> dict[str, bool]:
    return {name: True for name in REQUIRED_VALIDATIONS}


def validated_metrics(*, documents: int = 2, chunks: int = 4) -> dict:
    return {
        "document_count": documents,
        "expected_document_count": documents,
        "chunk_count": chunks,
        "expected_chunk_count": chunks,
        "distinct_chunk_count": chunks,
        "content_hash_count": documents,
        "empty_citation_text": 0,
        "empty_embedding_text": 0,
        "non_finite_vectors": 0,
        "hnsw": {
            "passed": True,
            "sample_count": chunks,
            "selected_ef_search": 80,
            "recall_by_ef_search": {"80": 0.99},
        },
        "cost_gate": {
            "passed": True,
            "projected_input_tokens": 1_000,
            "actual_input_tokens": 1_050,
            "variance": 0.05,
            "threshold": 0.15,
        },
    }


def prepare_stable(
    registry: IndexVersionRegistry,
    index_id: str,
    *,
    source_index_id: str = "",
):
    record = registry.register_candidate(
        index_id=index_id,
        parser_version="builtin-elements-v1",
        source_index_id=source_index_id,
    )
    registry.record_validation(
        record.index_id,
        passed_checklist(),
        metrics=validated_metrics(),
    )
    return registry.promote(record.index_id)


def test_index_registry_requires_data_level_validation_and_switches_atomically():
    registry = IndexVersionRegistry(":memory:")
    first = registry.register_candidate(
        index_id="retrieval-v2-a",
        parser_version="builtin-elements-v1",
    )

    with pytest.raises(ValueError, match="activation-ready"):
        registry.promote(first.index_id)

    # Validation booleans alone are not evidence that an index contains data.
    registry.record_validation(first.index_id, passed_checklist())
    with pytest.raises(ValueError, match="metrics.document_count"):
        registry.promote(first.index_id)

    registry.record_validation(
        first.index_id,
        passed_checklist(),
        metrics=validated_metrics(),
    )
    assert registry.promote(first.index_id).status == "stable"

    # The first activation establishes a fully validated baseline; it is not a
    # cutover and therefore does not manufacture a previous rollback pointer.
    assert registry.activate(first.index_id).status == "active"
    assert registry.state()["previous_index_id"] == ""
    assert registry.state()["generation"] == 1

    second = prepare_stable(
        registry,
        "retrieval-v2-b",
        source_index_id=first.index_id,
    )
    registry.activate(second.index_id)

    assert registry.active().index_id == second.index_id
    assert registry.get(first.index_id).status == "stable"
    assert registry.state()["previous_index_id"] == first.index_id
    assert registry.rollback().index_id == first.index_id
    assert registry.get(second.index_id).status == "rollback"
    assert registry.state()["generation"] == 3


def test_empty_bootstrap_cannot_be_promoted_or_used_as_first_active_snapshot():
    registry = IndexVersionRegistry(":memory:")
    bootstrap = registry.register_candidate(
        index_id="rag_chunks_v2_initial",
        table_name="rag_chunks_v2_initial",
        parser_version="builtin-elements-v1",
    )
    empty_metrics = validated_metrics(documents=1, chunks=1)
    empty_metrics.update(
        {
            "document_count": 0,
            "expected_document_count": 0,
            "chunk_count": 0,
            "expected_chunk_count": 0,
            "distinct_chunk_count": 0,
            "content_hash_count": 0,
        }
    )
    registry.record_validation(
        bootstrap.index_id,
        passed_checklist(),
        metrics=empty_metrics,
    )

    with pytest.raises(ValueError, match="metrics.document_count"):
        registry.promote(bootstrap.index_id)

    assert registry.active() is None
    assert registry.state()["previous_index_id"] == ""


def test_first_cutover_can_rollback_to_a_validated_openai_1536_baseline():
    registry = IndexVersionRegistry(":memory:")
    fallback = prepare_stable(registry, "rag_chunks_v2_initial")
    registry.activate(fallback.index_id)

    candidate = prepare_stable(
        registry,
        "retrieval-v2-first",
        source_index_id=fallback.index_id,
    )
    registry.activate(candidate.index_id)

    assert registry.state()["previous_index_id"] == fallback.index_id
    assert registry.rollback().index_id == fallback.index_id
    assert registry.get(candidate.index_id).status == "rollback"


def test_cutover_and_rollback_revalidate_snapshot_evidence_in_transaction():
    registry = IndexVersionRegistry(":memory:")
    fallback = prepare_stable(registry, "rag_chunks_v2_initial")
    registry.activate(fallback.index_id)
    candidate = prepare_stable(
        registry,
        "retrieval-v2-cloud",
        source_index_id=fallback.index_id,
    )

    assert registry._sqlite is not None
    corrupt = validated_metrics()
    corrupt["chunk_count"] = 0
    registry._sqlite.execute(
        "UPDATE rag_index_versions SET metrics = ? WHERE index_id = ?",
        (json.dumps(corrupt), fallback.index_id),
    )
    registry._sqlite.commit()
    before = registry.state().copy()
    with pytest.raises(ValueError, match="Current rollback snapshot.*chunk_count"):
        registry.activate(candidate.index_id)
    assert registry.state() == before
    assert registry.active().index_id == fallback.index_id

    registry._sqlite.execute(
        "UPDATE rag_index_versions SET metrics = ? WHERE index_id = ?",
        (json.dumps(validated_metrics()), fallback.index_id),
    )
    registry._sqlite.commit()
    registry.activate(candidate.index_id)

    corrupt = validated_metrics()
    corrupt["hnsw"] = {
        "passed": True,
        "sample_count": 0,
        "selected_ef_search": 80,
        "recall_by_ef_search": {"80": 0.99},
    }
    registry._sqlite.execute(
        "UPDATE rag_index_versions SET metrics = ? WHERE index_id = ?",
        (json.dumps(corrupt), fallback.index_id),
    )
    registry._sqlite.commit()
    before = registry.state().copy()
    with pytest.raises(ValueError, match="Rollback target.*hnsw.sample_count"):
        registry.rollback()
    assert registry.state() == before
    assert registry.active().index_id == candidate.index_id


def test_index_registry_rejects_unsafe_table_names_and_non_v2_dimensions():
    registry = IndexVersionRegistry(":memory:")

    with pytest.raises(ValueError, match="rag_chunks_v2"):
        registry.register_candidate(
            index_id="unsafe",
            table_name="rag_chunks;DROP_TABLE",
            parser_version="builtin",
        )
    with pytest.raises(ValueError, match="1536"):
        registry.register_candidate(
            index_id="wrong-dimension",
            parser_version="builtin",
            embedding_dimension=768,
        )
    with pytest.raises(ValueError, match="OpenAI"):
        registry.register_candidate(
            index_id="wrong-provider",
            parser_version="builtin",
            embedding_provider="local",
        )
    with pytest.raises(ValueError, match="text-embedding-3-large"):
        registry.register_candidate(
            index_id="wrong-model",
            parser_version="builtin",
            embedding_model="text-embedding-3-small",
        )


def test_application_mounts_the_admin_index_control_plane():
    from app.main import app

    paths = TestClient(app).get("/openapi.json").json()["paths"]

    assert "/api/indexes" in paths
    assert "/api/indexes/{index_id}/rebuild" in paths
    assert "/api/indexes/{index_id}/activate" in paths
    assert "/api/indexes/rollback" in paths
