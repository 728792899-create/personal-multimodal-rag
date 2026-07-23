from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import app
from app.middleware.request_guards import RequestGuardMiddleware
from app.services.observability import scrub_telemetry_event
from app.services.production_metrics import ProductionMetrics, safe_path_class
from app.services.release_readiness import build_release_readiness


def test_prometheus_metrics_use_bounded_paths_and_never_export_questions():
    metrics = ProductionMetrics()
    metrics.observe_http(
        method="GET",
        path="/api/documents/6e05f894-6438-42bc-83ec-bce7424fc820?token=secret",
        status=200,
        seconds=0.125,
    )
    rendered = metrics.render()

    assert safe_path_class("/api/documents/6e05f894-6438-42bc-83ec-bce7424fc820?x=1") == "/api/documents/:id"
    assert 'path="/api/documents/:id"' in rendered
    assert "secret" not in rendered
    assert "token=" not in rendered


def test_metrics_endpoint_is_prometheus_text_and_public():
    response = TestClient(app).get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "rag_build_info" in response.text
    assert "rag_index_queue_jobs" in response.text


def test_guard_rejections_are_included_in_http_metrics():
    guarded_app = FastAPI()
    metrics = ProductionMetrics()
    guarded_app.add_middleware(
        RequestGuardMiddleware,
        auth_token="expected-token",
        rate_limit_requests=0,
        metrics=metrics,
    )

    @guarded_app.get("/api/private")
    def private_route():
        return {"ok": True}

    response = TestClient(guarded_app).get("/api/private")

    assert response.status_code == 401
    rendered = metrics.render()
    assert 'rag_http_requests_total{method="GET",path="/api/private",status="401"} 1' in rendered


def test_telemetry_scrubber_removes_credentials_bodies_questions_and_query():
    scrubbed = scrub_telemetry_event(
        {
            "request": {
                "url": "https://private.example/path?token=secret",
                "headers": {"Authorization": "Bearer secret", "Cookie": "session=secret"},
                "body": "private document",
            },
            "extra": {"question": "private question", "safe": "stage=rerank"},
        }
    )

    assert scrubbed["request"] == "[Filtered]"
    assert scrubbed["extra"]["question"] == "[Filtered]"
    assert scrubbed["extra"]["safe"] == "stage=rerank"


def test_release_readiness_is_blocked_without_external_evidence(tmp_path):
    report = build_release_readiness(tmp_path / "missing.json")

    assert report["status"] == "blocked"
    assert report["production_ready_claim"] is False
    assert report["passed_gates"] == 0
    assert report["errors"]


def test_release_readiness_requires_every_real_gate(tmp_path):
    evidence = {
        "updated_at": "2026-07-23T00:00:00Z",
        "corpus": {
            "licensed_materials": 20,
            "non_fixture_documents": 200,
            "annotated_questions": 200,
        },
        "usage": {"real_questions": 100},
        "operations": {
            "soak_days": 14,
            "restore_drill_passed": True,
            "no_data_loss_defect": True,
        },
        "quality": {
            "recall_at_5": 0.85,
            "mrr": 0.75,
            "citation_accuracy": 0.85,
            "citation_coverage": 0.90,
            "refusal_accuracy": 0.90,
            "answer_acceptance": 0.85,
        },
    }
    path = tmp_path / "release.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")

    report = build_release_readiness(path)
    assert report["ready"] is True
    assert report["passed_gates"] == report["total_gates"]

    evidence["operations"]["soak_days"] = 13
    path.write_text(json.dumps(evidence), encoding="utf-8")
    blocked = build_release_readiness(path)
    assert blocked["ready"] is False
    assert next(gate for gate in blocked["gates"] if gate["id"] == "soak_days")["passed"] is False
