from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import settings
from app.middleware.request_guards import RequestGuardMiddleware
from app.services.observability import configure_sentry
from app.core.store import ingestion_worker, registry
from app.api.routers.providers import provider_status

configure_sentry(
    dsn=settings.sentry_dsn,
    environment=settings.sentry_environment,
    traces_sample_rate=settings.sentry_traces_sample_rate,
)

@asynccontextmanager
async def lifespan(_: FastAPI):
    ingestion_worker.start()
    try:
        yield
    finally:
        ingestion_worker.stop()


app = FastAPI(
    title="Personal Multimodal RAG",
    description="Local-first knowledge base QA with hybrid retrieval and citations.",
    version="0.3.0",
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
    rate_limit_requests=settings.rate_limit_requests,
    rate_limit_window_seconds=settings.rate_limit_window_seconds,
)

app.include_router(router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    providers = provider_status()
    return {
        "status": providers["status"],
        "providers": providers["providers"],
        "schema_version": registry.schema_version,
        "index_queue_depth": sum(1 for job in registry.list_index_jobs(200) if job["status"] in {"queued", "running", "cancelling"}),
    }
