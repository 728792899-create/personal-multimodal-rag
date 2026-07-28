from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import settings
from app.middleware.request_guards import RequestGuardMiddleware
from app.services.observability import configure_opentelemetry, configure_sentry
from app.services.production_metrics import production_metrics
from app.core.store import (
    auth_service,
    ingestion_worker,
    outbox_dispatcher,
    query_asset_service,
    registry,
    object_store,
    job_signal_queue,
    fetch_worker_client,
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
    description="本地优先的多模态知识库问答服务，支持混合检索与可核验引用。",
    version="0.4.0-rc.1",
    lifespan=lifespan,
)

configure_opentelemetry(
    app,
    endpoint=settings.otel_exporter_otlp_endpoint,
    service_name=settings.otel_service_name,
    sample_ratio=settings.otel_traces_sample_ratio,
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
    metrics=production_metrics,
)

app.include_router(router, prefix="/api")
app.include_router(build_auth_router(auth_service), prefix="/api")


@app.exception_handler(RequestValidationError)
async def localized_validation_error(_, exc: RequestValidationError):
    issues = []
    for error in exc.errors():
        issue_type = str(error.get("type") or "")
        context = error.get("ctx") if isinstance(error.get("ctx"), dict) else {}
        messages = {
            "missing": "缺少必填字段。",
            "string_too_short": "文本长度不足。",
            "string_too_long": "文本过长。",
            "int_type": "请输入有效整数。",
            "int_parsing": "请输入有效整数。",
            "float_type": "请输入有效数值。",
            "float_parsing": "请输入有效数值。",
            "bool_type": "请输入有效布尔值。",
            "literal_error": "该值不在允许范围内。",
            "list_too_long": "列表项目过多。",
            "list_too_short": "列表项目不足。",
        }
        message = messages.get(issue_type)
        if issue_type == "greater_than_equal":
            message = f"数值必须大于或等于 {context.get('ge')}。"
        elif issue_type == "less_than_equal":
            message = f"数值必须小于或等于 {context.get('le')}。"
        elif issue_type == "value_error":
            original = str(error.get("msg") or "")
            _, _, localized = original.partition(", ")
            message = localized or "请求参数无效。"
        issue = {
            "type": issue_type,
            "loc": list(error.get("loc") or []),
            "msg": message or "请求参数无效。",
        }
        issues.append(issue)
    return JSONResponse(
        status_code=422,
        content=jsonable_encoder({"detail": issues}),
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics():
    return PlainTextResponse(
        production_metrics.render(registry=registry),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.get("/ready")
def ready():
    providers = provider_status()
    answer_status = providers["providers"]["answer"]
    checks = collect_runtime_checks(
        settings,
        registry=registry,
        object_store=object_store,
        queue=job_signal_queue,
        vector_store=retriever.vector_store,
        fetch_worker=fetch_worker_client,
        answer_status=answer_status,
    )
    runtime = build_readiness_report(
        settings,
        checks=checks,
        answer_status=answer_status,
    )
    payload = {
        "status": "ready" if providers["status"] == "ready" and runtime["ready"] else "degraded",
        "providers": providers["providers"],
        "runtime": runtime,
        "schema_version": registry.schema_version,
        "index_queue_depth": sum(1 for job in registry.list_index_jobs(200) if job["status"] in {"queued", "running", "cancelling"}),
    }
    return JSONResponse(payload, status_code=200 if payload["status"] == "ready" else 503)
