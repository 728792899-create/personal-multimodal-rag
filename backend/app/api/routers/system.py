from __future__ import annotations

from fastapi import APIRouter

from app.config import settings
from app.core.store import fetch_worker_client, job_signal_queue, object_store, registry, retriever
from app.api.routers.providers import provider_status
from app.services.runtime_readiness import build_readiness_report, collect_runtime_checks
from app.services.release_readiness import build_release_readiness


router = APIRouter(prefix="/system", tags=["system"])


@router.get("/readiness-report")
def readiness_report():
    answer_status = provider_status()["providers"]["answer"]
    report = build_readiness_report(
        settings,
        checks=collect_runtime_checks(
            settings,
            registry=registry,
            object_store=object_store,
            queue=job_signal_queue,
            vector_store=retriever.vector_store,
            fetch_worker=fetch_worker_client,
            answer_status=answer_status,
        ),
        answer_status=answer_status,
    )
    report["schema_version"] = registry.schema_version
    report["release"] = build_release_readiness(settings.release_evidence_path)
    return report


@router.get("/usage-evidence")
def usage_evidence():
    """Return counts only; question text is deliberately excluded."""
    return registry.real_usage_summary()
