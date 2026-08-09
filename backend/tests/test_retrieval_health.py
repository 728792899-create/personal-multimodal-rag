import pytest

from app.models.domain import Chunk
from app.services.retrieval_health import (
    RetrievalHealthMonitor,
    RetrievalHealthThresholds,
    diagnose_retrieval_health,
)


def _chunk(chunk_id: str, document_id: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id=document_id,
        chunk_index=0,
        text=f"evidence for {chunk_id}",
        file_name=f"{document_id}.md",
    )


def test_current_retriever_shapes_report_overlap_and_channel_conversion():
    sparse_ids = [f"c{index}" for index in range(1, 11)]
    dense_ids = ["c1", "c2", "c3", *[f"d{index}" for index in range(4, 11)]]
    channels = [
        {"name": "bm25:0", "kind": "bm25", "ids": sparse_ids},
        {"name": "dense:0", "kind": "dense", "ids": dense_ids},
    ]
    final = [
        {"chunk": _chunk("c1", "doc-a")},
        {"chunk": _chunk("c4", "doc-b")},
        {"chunk": _chunk("d4", "doc-c")},
    ]

    result = diagnose_retrieval_health(channels, final)

    assert result["sparse_dense_top10"] == {
        "available": True,
        "k": 10,
        "sparse_count": 10,
        "dense_count": 10,
        "overlap_count": 3,
        "overlap_ids": ["c1", "c2", "c3"],
        "overlap_ratio": 0.3,
        "jaccard": 0.176471,
    }
    assert result["channel_final_evidence"]["by_kind"]["bm25"] == {
        "candidate_count": 10,
        "entered_final_count": 2,
        "entered_final_ids": ["c1", "c4"],
        "candidate_to_final_rate": 0.2,
        "final_evidence_coverage": 0.666667,
    }
    assert result["channel_final_evidence"]["by_kind"]["dense"][
        "final_evidence_coverage"
    ] == 0.666667
    assert result["candidate_diversity"]["unique_document_count"] == 3
    assert result["healthy"] is True


def test_serialized_candidates_report_duplicates_and_document_concentration():
    thresholds = RetrievalHealthThresholds(
        max_candidate_duplicate_rate=0.25,
        min_unique_documents=2,
        min_candidates_for_document_diversity=2,
    )
    final = [
        {"id": "c1", "document_id": "doc-a"},
        {"chunk_id": "c1", "document_id": "doc-a"},
        _chunk("c2", "doc-a"),
    ]

    result = diagnose_retrieval_health([], final, thresholds=thresholds)

    assert result["candidate_diversity"] == {
        "candidate_count": 3,
        "unique_candidate_count": 2,
        "duplicate_count": 1,
        "duplicate_rate": 0.333333,
        "unique_document_count": 1,
        "document_counts": {"doc-a": 2},
        "missing_document_id_count": 0,
        "channel_candidate_occurrences": 0,
        "unique_channel_candidates": 0,
        "cross_channel_duplicate_rate": 0.0,
    }
    assert {row["code"] for row in result["alerts"]} == {
        "high_candidate_duplicate_rate",
        "low_document_diversity",
    }


def test_cross_query_jaccard_and_universal_chunk_alert_support_mixed_history():
    thresholds = RetrievalHealthThresholds(
        top_k=3,
        min_cross_query_window=4,
        max_mean_top_k_jaccard=0.45,
        universal_chunk_min_query_ratio=0.75,
        universal_chunk_min_query_count=3,
    )
    current = [
        {"id": "always", "document_id": "doc-a"},
        {"id": "shared", "document_id": "doc-b"},
        {"id": "current", "document_id": "doc-c"},
    ]
    history = [
        {"top_ids": ["always", "shared", "old-1"]},
        ["always", "shared", "old-2"],
        {
            "results": [
                {"id": "always", "document_id": "doc-a"},
                {"id": "shared", "document_id": "doc-b"},
                {"id": "old-3", "document_id": "doc-d"},
            ]
        },
    ]

    result = diagnose_retrieval_health(
        [], current, history_window=history, thresholds=thresholds
    )

    assert result["cross_query"]["jaccard_by_history"] == [0.5, 0.5, 0.5]
    assert result["cross_query"]["mean_jaccard"] == 0.5
    assert result["cross_query"]["max_jaccard"] == 0.5
    assert result["cross_query"]["universal_chunks"] == [
        {"candidate_id": "always", "query_count": 4, "query_ratio": 1.0},
        {"candidate_id": "shared", "query_count": 4, "query_ratio": 1.0},
    ]
    assert {row["code"] for row in result["alerts"]} == {
        "high_cross_query_top_k_jaccard",
        "universal_chunk",
    }


def test_distinct_query_history_does_not_raise_collapse_alerts():
    thresholds = RetrievalHealthThresholds(
        top_k=3,
        min_cross_query_window=3,
        max_mean_top_k_jaccard=0.5,
        universal_chunk_min_query_ratio=0.8,
        universal_chunk_min_query_count=3,
    )

    result = diagnose_retrieval_health(
        [],
        ["a", "b", "c"],
        history_window=[["d", "e", "f"], ["g", "h", "i"]],
        thresholds=thresholds,
    )

    assert result["cross_query"]["history_sufficient"] is True
    assert result["cross_query"]["mean_jaccard"] == 0.0
    assert result["cross_query"]["universal_chunks"] == []
    assert result["alerts"] == []
    assert result["healthy"] is True


def test_missing_channel_or_history_is_reported_without_false_alerts():
    result = diagnose_retrieval_health(
        [{"name": "bm25:0", "kind": "bm25", "ids": ["c1", "c2"]}],
        [],
    )

    assert result["sparse_dense_top10"]["available"] is False
    assert result["sparse_dense_top10"]["jaccard"] is None
    assert result["cross_query"]["history_sufficient"] is False
    assert result["alerts"] == []


def test_inputs_are_not_mutated():
    channels = [{"name": "bm25:0", "kind": "bm25", "ids": ["c1", "c1"]}]
    final = [{"id": "c1", "document_id": "doc-a"}]
    history = [{"top_ids": ["c1", "c2"]}]

    diagnose_retrieval_health(channels, final, history_window=history)

    assert channels == [{"name": "bm25:0", "kind": "bm25", "ids": ["c1", "c1"]}]
    assert final == [{"id": "c1", "document_id": "doc-a"}]
    assert history == [{"top_ids": ["c1", "c2"]}]


def test_monitor_compares_only_unrelated_queries_in_the_same_scope():
    monitor = RetrievalHealthMonitor(max_history=8)
    thresholds = RetrievalHealthThresholds(
        top_k=3,
        min_sparse_dense_overlap=0,
        min_channel_final_coverage=0,
        min_unique_documents=1,
        min_cross_query_window=2,
        max_mean_top_k_jaccard=0.8,
        universal_chunk_min_query_ratio=1.0,
        universal_chunk_min_query_count=2,
    )
    final = [
        {"id": "universal", "document_id": "doc-a"},
        {"id": "same-2", "document_id": "doc-b"},
        {"id": "same-3", "document_id": "doc-c"},
    ]

    first = monitor.diagnose(
        [],
        final,
        query_tokens=["aurora", "launch"],
        scope_key=("index-a", "semantic"),
        thresholds=thresholds,
    )
    retry = monitor.diagnose(
        [],
        final,
        query_tokens=["aurora", "launch"],
        scope_key=("index-a", "semantic"),
        thresholds=thresholds,
    )
    other_scope = monitor.diagnose(
        [],
        final,
        query_tokens=["payroll", "policy"],
        scope_key=("index-b", "semantic"),
        thresholds=thresholds,
    )
    unrelated = monitor.diagnose(
        [],
        final,
        query_tokens=["payroll", "policy"],
        scope_key=("index-a", "semantic"),
        thresholds=thresholds,
    )

    assert first["status"] == "insufficient_history"
    assert retry["history"]["unrelated_queries_compared"] == 0
    assert retry["history"]["duplicate_query_not_stored"] is True
    assert other_scope["history"]["stored_queries_in_scope"] == 0
    assert unrelated["status"] == "warning"
    assert unrelated["cross_query"]["mean_jaccard"] == 1.0
    assert {row["code"] for row in unrelated["alerts"]} == {
        "high_cross_query_top_k_jaccard",
        "universal_chunk",
    }


def test_monitor_skips_ineligible_requests_without_growing_history():
    monitor = RetrievalHealthMonitor(max_history=4)
    final = [{"id": "c1", "document_id": "doc-a"}]

    skipped = monitor.diagnose(
        [],
        final,
        query_tokens=["summary"],
        scope_key=("index-a", "summary"),
        eligible=False,
        exclude_reason="summary_route",
    )
    later = monitor.diagnose(
        [],
        final,
        query_tokens=["different"],
        scope_key=("index-a", "summary"),
    )

    assert skipped["status"] == "skipped"
    assert skipped["exclude_reason"] == "summary_route"
    assert skipped["history"]["stored_queries_in_scope"] == 0
    assert later["history"]["stored_queries_in_scope"] == 0


def test_monitor_retains_only_a_fixed_size_scope_digest():
    monitor = RetrievalHealthMonitor(max_history=2)
    final = [
        {"id": f"c{index}", "document_id": f"doc-{index}"}
        for index in range(3)
    ]
    oversized_scope_value = "private-" + ("x" * 100_000)

    monitor.diagnose(
        [],
        final,
        query_tokens=["bounded", "scope"],
        scope_key=(oversized_scope_value, tuple(str(index) for index in range(1_000))),
    )

    stored = list(monitor._history)
    assert len(stored) == 1
    assert set(stored[0]) == {"scope_digest", "query_tokens", "top_ids"}
    assert len(stored[0]["scope_digest"]) == 64
    assert oversized_scope_value not in repr(stored)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"top_k": 0},
        {"max_candidate_duplicate_rate": 1.01},
        {"universal_chunk_min_query_ratio": -0.01},
    ],
)
def test_thresholds_reject_invalid_values(kwargs):
    with pytest.raises(ValueError):
        RetrievalHealthThresholds(**kwargs)
