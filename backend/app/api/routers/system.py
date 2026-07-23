from __future__ import annotations

from fastapi import APIRouter

from app.config import settings
from app.core.store import job_signal_queue, object_store, registry, retriever
from app.services.runtime_readiness import build_readiness_report, collect_runtime_checks


router = APIRouter(prefix="/system", tags=["system"])


@router.get("/readiness-report")
def readiness_report():
    report = build_readiness_report(
        settings,
        checks=collect_runtime_checks(
            settings,
            registry=registry,
            object_store=object_store,
            queue=job_signal_queue,
            vector_store=retriever.vector_store,
        ),
    )
    report["schema_version"] = registry.schema_version
    report["release"] = {
        "version": "0.4.0-rc.1",
        "production_ready_claim": False,
        "remaining_gates": [
            "real-provider acceptance",
            "production backup restore",
            "14-day soak",
        ],
    }
    return report
