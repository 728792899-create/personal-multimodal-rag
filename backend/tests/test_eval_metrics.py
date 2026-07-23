from scripts.run_retrieval_eval import compare_thresholds, summarize_rows


def test_eval_summary_separates_answerable_and_refusal_cases():
    rows = [
        {"should_answer": True, "recall_hit": True, "first_relevant_rank": 1, "citation_correct": True, "decision_correct": True},
        {"should_answer": True, "recall_hit": False, "first_relevant_rank": None, "citation_correct": False, "decision_correct": True},
        {"should_answer": False, "recall_hit": None, "first_relevant_rank": None, "citation_correct": True, "decision_correct": True},
        {"should_answer": False, "recall_hit": None, "first_relevant_rank": None, "citation_correct": False, "decision_correct": False},
    ]

    summary = summarize_rows(rows)

    assert summary["recall_at_5"] == 0.5
    assert summary["mrr"] == 0.5
    assert summary["citation_accuracy"] == 0.5
    assert summary["refusal_accuracy"] == 0.5


def test_threshold_checks_are_machine_readable():
    checks = compare_thresholds({"mrr": 0.75, "recall_at_5": 0.89}, {"mrr": 0.75, "recall_at_5": 0.9})

    assert checks == [
        {"metric": "mrr", "actual": 0.75, "minimum": 0.75, "passed": True},
        {"metric": "recall_at_5", "actual": 0.89, "minimum": 0.9, "passed": False},
    ]
