from app.services.system_metrics import build_system_metrics


def _build(history: list[dict], conversation_traces: list[dict] | None = None) -> dict:
    return build_system_metrics(
        documents=[],
        history=history,
        feedback_stats={},
        operations=[],
        chunk_count=0,
        conversation_retrieval_traces=conversation_traces,
    )


def test_system_metrics_reports_missing_retrieval_health_as_no_data():
    health = _build([])["answering"]["retrieval_health"]

    assert health == {
        "status": "no_data",
        "observed_count": 0,
        "eligible_count": 0,
        "warning_count": 0,
        "warning_rate": None,
        "by_status": {},
        "by_alert": {},
        "avg_cross_query_topk_jaccard": None,
        "avg_sparse_dense_jaccard": None,
    }


def test_system_metrics_aggregates_retrieval_health_without_candidate_ids():
    history = [
        {
            "retrieval_trace": {
                "pipeline": {
                    "retrieval_health": {
                        "eligible": True,
                        "status": "warning",
                        "alerts": [{"code": "universal_chunk"}],
                        "cross_query": {
                            "mean_jaccard": 0.9,
                            "current_top_ids": ["private-chunk"],
                        },
                        "sparse_dense_top10": {"jaccard": 0.2},
                    }
                }
            }
        },
        {
            "retrieval_trace": {
                "pipeline": {
                    "retrieval_health": {
                        "eligible": True,
                        "status": "healthy",
                        "alerts": [],
                        "cross_query": {"mean_jaccard": 0.1},
                        "sparse_dense_top10": {"jaccard": 0.4},
                    }
                }
            }
        },
    ]

    metrics = _build(history)
    health = metrics["answering"]["retrieval_health"]

    assert health["status"] == "warning"
    assert health["eligible_count"] == 2
    assert health["warning_count"] == 1
    assert health["warning_rate"] == 0.5
    assert health["by_alert"] == {"universal_chunk": 1}
    assert health["avg_cross_query_topk_jaccard"] == 0.5
    assert health["avg_sparse_dense_jaccard"] == 0.3
    assert "private-chunk" not in str(health)
    assert any("检索健康告警" in item for item in metrics["recommendations"])


def test_system_metrics_never_calls_skipped_only_history_healthy():
    metrics = _build(
        [
            {
                "retrieval_trace": {
                    "pipeline": {
                        "retrieval_health": {
                            "eligible": False,
                            "status": "skipped",
                            "alerts": [{"code": "low_document_diversity"}],
                        }
                    }
                }
            }
        ]
    )
    health = metrics["answering"]["retrieval_health"]

    assert health["status"] == "insufficient_history"
    assert health["eligible_count"] == 0
    assert health["warning_count"] == 0
    assert health["warning_rate"] is None
    assert health["by_alert"] == {}


def test_system_metrics_never_hides_insufficient_samples_behind_one_healthy_row():
    def row(status: str) -> dict:
        return {
            "retrieval_trace": {
                "pipeline": {
                    "retrieval_health": {
                        "eligible": True,
                        "status": status,
                        "alerts": [],
                    }
                }
            }
        }

    health = _build([row("healthy"), *[row("insufficient_history") for _ in range(9)]])[
        "answering"
    ]["retrieval_health"]

    assert health["status"] == "insufficient_history"
    assert health["eligible_count"] == 10


def test_system_metrics_treats_unknown_eligible_status_as_insufficient():
    health = _build(
        [
            {
                "retrieval_trace": {
                    "pipeline": {
                        "retrieval_health": {
                            "eligible": True,
                            "status": "skipped",
                            "alerts": [],
                        }
                    }
                }
            }
        ]
    )["answering"]["retrieval_health"]

    assert health["status"] == "insufficient_history"


def test_system_metrics_includes_persisted_conversation_traces():
    metrics = _build(
        [],
        [
            {
                "pipeline": {
                    "retrieval_health": {
                        "eligible": True,
                        "status": "healthy",
                        "alerts": [],
                        "cross_query": {"mean_jaccard": 0.1},
                    }
                }
            }
        ],
    )

    health = metrics["answering"]["retrieval_health"]
    assert health["status"] == "healthy"
    assert health["observed_count"] == 1
    assert health["eligible_count"] == 1
