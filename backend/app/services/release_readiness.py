from __future__ import annotations

import json
from pathlib import Path


QUALITY_THRESHOLDS = {
    "recall_at_5": 0.85,
    "mrr": 0.75,
    "citation_accuracy": 0.85,
    "citation_coverage": 0.90,
    "refusal_accuracy": 0.90,
    "answer_acceptance": 0.85,
}


def _load_evidence(path: str | Path) -> tuple[dict, list[str]]:
    target = Path(path)
    if not target.is_file():
        return {}, ["release evidence file is not present"]
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, ["release evidence file is unreadable or invalid JSON"]
    if not isinstance(payload, dict):
        return {}, ["release evidence root must be a JSON object"]
    return payload, []


def build_release_readiness(path: str | Path) -> dict:
    evidence, errors = _load_evidence(path)
    corpus = evidence.get("corpus") if isinstance(evidence.get("corpus"), dict) else {}
    usage = evidence.get("usage") if isinstance(evidence.get("usage"), dict) else {}
    operations = evidence.get("operations") if isinstance(evidence.get("operations"), dict) else {}
    quality = evidence.get("quality") if isinstance(evidence.get("quality"), dict) else {}

    gates: list[dict] = []

    def minimum(gate_id: str, label: str, observed, required) -> None:
        try:
            numeric = float(observed or 0)
        except (TypeError, ValueError):
            numeric = 0.0
        gates.append(
            {
                "id": gate_id,
                "label": label,
                "passed": numeric >= float(required),
                "observed": observed or 0,
                "required": required,
            }
        )

    def boolean(gate_id: str, label: str, observed: object) -> None:
        gates.append(
            {
                "id": gate_id,
                "label": label,
                "passed": observed is True,
                "observed": bool(observed),
                "required": True,
            }
        )

    minimum("licensed_materials", "licensed real source materials", corpus.get("licensed_materials"), 20)
    minimum("non_fixture_documents", "non-fixture indexed documents", corpus.get("non_fixture_documents"), 200)
    minimum("annotated_questions", "human-annotated benchmark questions", corpus.get("annotated_questions"), 200)
    minimum("real_questions", "real usage questions", usage.get("real_questions"), 100)
    minimum("soak_days", "continuous deployment days", operations.get("soak_days"), 14)
    boolean("restore_drill", "complete production restore drill", operations.get("restore_drill_passed"))
    boolean("no_data_loss", "no known data-loss defect", operations.get("no_data_loss_defect"))
    for metric, threshold in QUALITY_THRESHOLDS.items():
        minimum(metric, metric.replace("_", " "), quality.get(metric), threshold)

    passed = sum(1 for gate in gates if gate["passed"])
    return {
        "target_version": "1.0.0",
        "candidate_version": "0.4.0-rc.1",
        "ready": not errors and passed == len(gates),
        "status": "ready" if not errors and passed == len(gates) else "blocked",
        "passed_gates": passed,
        "total_gates": len(gates),
        "gates": gates,
        "errors": errors,
        "evidence_updated_at": str(evidence.get("updated_at") or ""),
        "production_ready_claim": False,
    }
