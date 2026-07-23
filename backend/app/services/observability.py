from __future__ import annotations

import logging
from urllib.parse import urlsplit, urlunsplit


logger = logging.getLogger(__name__)


_SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "x-csrf-token",
    "password",
    "token",
    "secret",
    "request",
    "body",
}


def scrub_telemetry_event(event: dict, _hint: dict | None = None) -> dict:
    """Remove credentials, bodies, questions, and URL query data before export."""

    def scrub(value, key: str = ""):
        normalized = key.lower().replace("_", "-")
        if normalized in _SENSITIVE_KEYS or any(
            marker in normalized for marker in ("password", "secret", "token", "cookie", "question", "content")
        ):
            return "[Filtered]"
        if isinstance(value, dict):
            return {item_key: scrub(item, str(item_key)) for item_key, item in value.items()}
        if isinstance(value, list):
            return [scrub(item, key) for item in value[:100]]
        if isinstance(value, str) and normalized in {"url", "request-url"}:
            try:
                parsed = urlsplit(value)
                return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
            except ValueError:
                return "[Filtered]"
        return value

    return scrub(event)


def configure_sentry(*, dsn: str, environment: str, traces_sample_rate: float = 0.05) -> bool:
    """Enable privacy-conscious Sentry reporting only when explicitly configured."""
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        logger.warning("SENTRY_DSN is set but sentry-sdk is not installed; error reporting is disabled")
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        traces_sample_rate=max(0.0, min(float(traces_sample_rate), 1.0)),
        send_default_pii=False,
        max_request_body_size="never",
        before_send=scrub_telemetry_event,
    )
    return True


def configure_opentelemetry(
    app,
    *,
    endpoint: str,
    service_name: str = "personal-multimodal-rag",
    sample_ratio: float = 0.05,
) -> bool:
    """Enable OTLP/HTTP tracing only when an endpoint is explicitly configured."""
    if not endpoint:
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
    except ImportError:
        logger.warning("OTEL_EXPORTER_OTLP_ENDPOINT is set but OpenTelemetry packages are unavailable")
        return False
    provider = TracerProvider(
        resource=Resource.create({"service.name": service_name}),
        sampler=ParentBased(TraceIdRatioBased(max(0.0, min(float(sample_ratio), 1.0)))),
    )
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls="health,ready,metrics",
        http_capture_headers_server_request=[],
        http_capture_headers_server_response=[],
    )
    return True
