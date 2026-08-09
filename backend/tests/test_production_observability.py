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
    assert scrubbed["extra"]["safe"] == "[Filtered]"


def test_telemetry_scrubber_canary_covers_stack_extra_breadcrumb_and_urls():
    canary = "telemetry-canary-4f36f5e0"
    event = {
        "exception": {
            "values": [
                {
                    "type": "ProviderError",
                    "value": (
                        f'upstream payload {{"api_key":"{canary}"}}'
                    ),
                    "stacktrace": {
                        "frames": [
                            {
                                "module": "app.provider",
                                "function": "connect",
                                "vars": {
                                    "harmless_name": canary,
                                    "api-key": canary,
                                },
                            }
                        ]
                    },
                }
            ]
        },
        "extra": {
            "stage": "provider-validation",
            "opaque": canary,
            "api_key": canary,
            "api-key": canary,
            "apikey": canary,
            "credential": canary,
            "secret": canary,
        },
        "breadcrumbs": {
            "values": [
                {
                    "category": "provider",
                    "level": "error",
                    "message": canary,
                    "data": {
                        "method": "GET",
                        "route": "/models",
                        "url": (
                            f"https://user:{canary}@api.example/models"
                            f"?api_key={canary}#private"
                        ),
                        "opaque": canary,
                    },
                }
            ]
        },
        "contexts": {
            "provider": {
                "credential": canary,
                "url": (
                    f"https://user:{canary}@api.example/v1"
                    f"?secret={canary}#private"
                ),
            }
        },
    }

    scrubbed = scrub_telemetry_event(event)
    encoded = json.dumps(scrubbed, ensure_ascii=False)

    assert canary not in encoded
    assert "user:" not in encoded
    assert "?api_key=" not in encoded
    assert "?secret=" not in encoded
    assert scrubbed["extra"]["stage"] == "provider-validation"
    exception = scrubbed["exception"]["values"][0]
    assert exception["type"] == "ProviderError"
    assert exception["value"] == "[Filtered]"
    assert exception["stacktrace"]["frames"][0]["module"] == "app.provider"
    assert exception["stacktrace"]["frames"][0]["vars"] == "[Filtered]"
    breadcrumb = scrubbed["breadcrumbs"]["values"][0]
    assert breadcrumb["category"] == "provider"
    assert breadcrumb["level"] == "error"
    assert breadcrumb["message"] == "[Filtered]"
    assert breadcrumb["data"]["url"] == "https://api.example/models"
    assert event["extra"]["opaque"] == canary


def test_release_readiness_is_blocked_without_external_evidence(tmp_path):
    report = build_release_readiness(tmp_path / "missing.json")

    assert report["status"] == "blocked"
    assert report["production_ready_claim"] is False
    assert report["passed_gates"] == 0
    assert report["errors"]


def test_release_readiness_requires_every_real_gate(tmp_path):
    evidence = {
        "schema_version": 2,
        "candidate_version": "1.0.0-rc.1",
        "updated_at": "2026-07-23T00:00:00Z",
        "corpus": {
            "licensed_materials": 20,
            "non_fixture_documents": 200,
            "annotated_questions": 200,
            "locked_regression_questions": 140,
            "second_reviewed_questions": 40,
            "label_agreement_kappa": 0.75,
            "evidence_agreement_f1": 0.80,
        },
        "usage": {"representative_queries": 500},
        "operations": {
            "soak_days": 14,
            "availability": 0.995,
            "provider_failure_contract_passed": True,
            "rbac_authorization_pass_rate": 1.0,
            "restore_drill_passed": True,
            "full_stack_rollback_passed": True,
            "rollback_rto_minutes": 10,
            "source_rpo_lost_records": 0,
            "five_xx_rollback_trigger_verified": True,
            "permission_bypass_incidents": 0,
            "index_pollution_incidents": 0,
            "data_loss_incidents": 0,
            "fabricated_citation_incidents": 0,
            "secret_leak_incidents": 0,
            "unresolved_sev1": 0,
        },
        "quality": {
            "recall_at_5": 0.90,
            "mrr_at_10": 0.78,
            "multihop_chain_at_10": 0.80,
            "table_recall_at_10": 0.85,
            "image_recall_at_10": 0.85,
            "formula_recall_at_10": 0.85,
            "citation_accuracy": 0.90,
            "factual_coverage": 0.90,
            "fabricated_or_invalid_citations": 0,
            "refusal_f1": 0.88,
            "answerable_false_refusal_rate": 0.08,
            "blind_test_cases": 100,
            "blind_acceptance_rate": 0.85,
        },
        "ann": {
            "hnsw_recall_at_50": 0.98,
            "primary_strata_recall_at_50": {
                "exact": 0.95,
                "semantic": 0.97,
                "multimodal": 0.96,
            },
        },
        "comparison": {
            "difficult_core_best_improvement": 0.05,
            "overall_worst_regression": 0.01,
        },
        "reranking": {"enabled": False},
        "performance": {
            "benchmark_chunks": 50_000,
            "benchmark_concurrency": 5,
            "hnsw_p95_ms": 200,
            "simple_retrieval_p95_ms": 2_000,
            "complex_retrieval_p95_ms": 6_000,
            "simple_ttft_p95_ms": 6_000,
            "complex_ttft_p95_ms": 10_000,
            "automatic_routing_cost_ratio": 1.35,
        },
        "audit": {
            "indexed_hashes_match": True,
            "soak_chain_valid": True,
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


def test_release_readiness_fails_closed_for_missing_zero_target_evidence(tmp_path):
    evidence = {
        "schema_version": 2,
        "candidate_version": "1.0.0-rc.1",
        "quality": {"fabricated_or_invalid_citations": None},
        "operations": {"data_loss_incidents": None},
    }
    path = tmp_path / "release.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")

    report = build_release_readiness(path)

    assert next(
        gate
        for gate in report["gates"]
        if gate["id"] == "fabricated_or_invalid_citations"
    )["passed"] is False
    assert next(
        gate for gate in report["gates"] if gate["id"] == "data_loss_incidents"
    )["passed"] is False


def test_release_readiness_only_requires_rerank_metrics_when_enabled(tmp_path):
    path = tmp_path / "release.json"
    path.write_text(
        json.dumps({"reranking": {"enabled": False}}), encoding="utf-8"
    )
    disabled = build_release_readiness(path)
    assert "rerank_mrr_improvement" not in {
        gate["id"] for gate in disabled["gates"]
    }

    path.write_text(
        json.dumps(
            {
                "reranking": {
                    "enabled": True,
                    "trigger_subset_mrr_improvement": 0.02,
                    "trigger_rate": 0.51,
                }
            }
        ),
        encoding="utf-8",
    )
    enabled = build_release_readiness(path)
    gates = {gate["id"]: gate for gate in enabled["gates"]}
    assert gates["rerank_mrr_improvement"]["passed"] is False
    assert gates["rerank_trigger_rate"]["passed"] is False
