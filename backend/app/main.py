from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import settings
from app.middleware.request_guards import RequestGuardMiddleware
from app.services.observability import configure_sentry
from app.core.store import (
    auth_service,
    ingestion_worker,
    outbox_dispatcher,
    query_asset_service,
    registry,
    object_store,
    job_signal_queue,
    retriever,
)
from app.api.routers.auth import build_auth_router
from app.api.routers.providers import provider_status
from app.services.runtime_readiness import (
    build_readiness_report,
    collect_runtime_checks,
    validate_runtime_settings,
)

configure_sentry(
    dsn=settings.sentry_dsn,
    environment=settings.sentry_environment,
    traces_sample_rate=settings.sentry_traces_sample_rate,
)

@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_runtime_settings(settings)
    query_asset_service.cleanup_expired()
    registry.recover_interrupted_sync_runs()
    if outbox_dispatcher:
        outbox_dispatcher.start()
    if settings.embedded_worker:
        ingestion_worker.start()
    try:
        yield
    finally:
        if settings.embedded_worker:
            ingestion_worker.stop()
        if outbox_dispatcher:
            outbox_dispatcher.stop()


app = FastAPI(
    title="Personal Multimodal RAG",
    description="Local-first knowledge base QA with hybrid retrieval and citations.",
    version="0.4.0-rc.1",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    RequestGuardMiddleware,
    auth_token=settings.api_auth_token,
    auth_service=auth_service,
    rate_limit_requests=settings.rate_limit_requests,
    rate_limit_window_seconds=settings.rate_limit_window_seconds,
    login_rate_limit_requests=settings.login_rate_limit_requests,
    login_rate_limit_window_seconds=settings.login_rate_limit_window_seconds,
)

app.include_router(router, prefix="/api")
app.include_router(build_auth_router(auth_service), prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    providers = provider_status()
    checks = collect_runtime_checks(
        settings,
        registry=registry,
        object_store=object_store,
        queue=job_signal_queue,
        vector_store=retriever.vector_store,
    )
    runtime = build_readiness_report(
        settings,
        checks=checks,
    )
    payload = {
        "status": "ready" if providers["status"] == "ready" and runtime["ready"] else "degraded",
        "providers": providers["providers"],
        "runtime": runtime,
        "schema_version": registry.schema_version,
        "index_queue_depth": sum(1 for job in registry.list_index_jobs(200) if job["status"] in {"queued", "running", "cancelling"}),
    }
    return JSONResponse(payload, status_code=200 if payload["status"] == "ready" else 503)
