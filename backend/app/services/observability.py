from __future__ import annotations

import logging
import re

from app.services.safe_logging import redact_sensitive_text, sanitize_url_for_log


logger = logging.getLogger(__name__)


_SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "x-csrf-token",
    "api-key",
    "apikey",
    "credential",
    "credentials",
    "password",
    "token",
    "secret",
    "request",
    "body",
    # Stack-frame locals have no stable allowlist and may contain a credential
    # under an innocuous application variable name. Do not export them at all.
    "vars",
    "locals",
    "local-variables",
}
_SENSITIVE_KEY_MARKERS = (
    "api-key",
    "apikey",
    "credential",
    "password",
    "secret",
    "token",
    "cookie",
    "question",
    "content",
)
_EXTRA_ALLOWLIST = {
    "component",
    "jobid",
    "operation",
    "requestid",
    "stage",
    "status",
}
_BREADCRUMB_ALLOWLIST = {
    "category",
    "level",
    "timestamp",
    "type",
}
_BREADCRUMB_DATA_ALLOWLIST = {
    "method",
    "route",
    "statuscode",
    "url",
}
_MAX_DEPTH = 20
_MAX_ITEMS = 100


def _canonical_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _is_sensitive_key(value: object) -> bool:
    normalized = str(value).lower().replace("_", "-")
    canonical = _canonical_key(value)
    return (
        normalized in _SENSITIVE_KEYS
        or canonical
        in {
            "apikey",
            "authorization",
            "clientsecret",
            "cookie",
            "credential",
            "credentials",
            "locals",
            "localvariables",
            "password",
            "secret",
            "setcookie",
            "token",
            "vars",
            "xapikey",
            "xcsrftoken",
        }
        or any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS)
    )


def scrub_telemetry_event(event: dict, _hint: dict | None = None) -> dict:
    """Remove credentials, bodies, questions, and URL query data before export."""

    seen: set[int] = set()

    def scrub(
        value,
        key: str = "",
        *,
        depth: int = 0,
        exception_value: bool = False,
    ):
        normalized = key.lower().replace("_", "-")
        if exception_value or _is_sensitive_key(key):
            return "[Filtered]"
        if depth > _MAX_DEPTH:
            return "[Filtered]"
        if isinstance(value, dict):
            identity = id(value)
            if identity in seen:
                return "[Filtered]"
            seen.add(identity)
            canonical = _canonical_key(key)
            if canonical == "extra":
                result = {
                    item_key: (
                        scrub(
                            item,
                            str(item_key),
                            depth=depth + 1,
                        )
                        if _canonical_key(item_key) in _EXTRA_ALLOWLIST
                        else "[Filtered]"
                    )
                    for item_key, item in list(value.items())[:_MAX_ITEMS]
                }
            elif canonical == "breadcrumbs":
                result = scrub_breadcrumb_container(value, depth=depth + 1)
            elif canonical == "exception":
                result = scrub_exception(value, depth=depth + 1)
            else:
                result = {
                    item_key: scrub(
                        item,
                        str(item_key),
                        depth=depth + 1,
                    )
                    for item_key, item in list(value.items())[:_MAX_ITEMS]
                }
            seen.discard(identity)
            return result
        if isinstance(value, (list, tuple)):
            identity = id(value)
            if identity in seen:
                return ["[Filtered]"]
            seen.add(identity)
            result = [
                scrub(item, key, depth=depth + 1)
                for item in value[:_MAX_ITEMS]
            ]
            seen.discard(identity)
            return result
        if isinstance(value, str) and normalized in {"url", "request-url"}:
            return sanitize_url_for_log(value)
        if isinstance(value, str):
            return redact_sensitive_text(value)
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return "[Filtered]"

    def scrub_exception(value: dict, *, depth: int) -> dict:
        result = {}
        for item_key, item in list(value.items())[:_MAX_ITEMS]:
            canonical = _canonical_key(item_key)
            if canonical == "values" and isinstance(item, (list, tuple)):
                result[item_key] = [
                    {
                        child_key: scrub(
                            child_value,
                            str(child_key),
                            depth=depth + 2,
                            exception_value=_canonical_key(child_key)
                            == "value",
                        )
                        for child_key, child_value in list(entry.items())[
                            :_MAX_ITEMS
                        ]
                    }
                    if isinstance(entry, dict)
                    else "[Filtered]"
                    for entry in item[:_MAX_ITEMS]
                ]
            else:
                result[item_key] = scrub(
                    item,
                    str(item_key),
                    depth=depth + 1,
                )
        return result

    def scrub_breadcrumb_container(value: dict, *, depth: int) -> dict:
        result = {}
        for item_key, item in list(value.items())[:_MAX_ITEMS]:
            if (
                _canonical_key(item_key) == "values"
                and isinstance(item, (list, tuple))
            ):
                result[item_key] = [
                    scrub_breadcrumb_entry(entry, depth=depth + 1)
                    if isinstance(entry, dict)
                    else "[Filtered]"
                    for entry in item[:_MAX_ITEMS]
                ]
            else:
                result[item_key] = scrub(
                    item,
                    str(item_key),
                    depth=depth + 1,
                )
        return result

    def scrub_breadcrumb_entry(value: dict, *, depth: int) -> dict:
        result = {}
        for item_key, item in list(value.items())[:_MAX_ITEMS]:
            canonical = _canonical_key(item_key)
            if canonical == "message":
                result[item_key] = "[Filtered]"
            elif canonical == "data" and isinstance(item, dict):
                result[item_key] = {
                    data_key: (
                        scrub(
                            data_value,
                            str(data_key),
                            depth=depth + 2,
                        )
                        if _canonical_key(data_key)
                        in _BREADCRUMB_DATA_ALLOWLIST
                        else "[Filtered]"
                    )
                    for data_key, data_value in list(item.items())[
                        :_MAX_ITEMS
                    ]
                }
            elif canonical in _BREADCRUMB_ALLOWLIST:
                result[item_key] = scrub(
                    item,
                    str(item_key),
                    depth=depth + 1,
                )
            else:
                result[item_key] = "[Filtered]"
        return result

    return scrub(event)


def scrub_telemetry_breadcrumb(
    breadcrumb: dict,
    _hint: dict | None = None,
) -> dict:
    """Apply the same credential policy before a breadcrumb enters Sentry state."""

    return scrub_telemetry_event(
        {"breadcrumbs": {"values": [breadcrumb]}}
    )["breadcrumbs"]["values"][0]


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
        include_local_variables=False,
        before_send=scrub_telemetry_event,
        before_breadcrumb=scrub_telemetry_breadcrumb,
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
