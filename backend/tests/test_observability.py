import sys
from types import SimpleNamespace

from app.services.observability import (
    configure_sentry,
    scrub_telemetry_breadcrumb,
    scrub_telemetry_event,
)


def test_sentry_is_disabled_without_dsn():
    assert configure_sentry(dsn="", environment="test") is False


def test_sentry_registers_privacy_callbacks_and_disables_stack_locals(
    monkeypatch,
):
    captured = {}
    monkeypatch.setitem(
        sys.modules,
        "sentry_sdk",
        SimpleNamespace(init=lambda **kwargs: captured.update(kwargs)),
    )

    assert configure_sentry(
        dsn="https://public@example.invalid/1",
        environment="test",
    ) is True

    assert captured["send_default_pii"] is False
    assert captured["max_request_body_size"] == "never"
    assert captured["include_local_variables"] is False
    assert captured["before_send"] is scrub_telemetry_event
    assert captured["before_breadcrumb"] is scrub_telemetry_breadcrumb


def test_breadcrumb_callback_filters_message_and_untrusted_data():
    canary = "telemetry-canary-breadcrumb"

    scrubbed = scrub_telemetry_breadcrumb(
        {
            "category": "provider",
            "level": "warning",
            "message": canary,
            "data": {
                "route": "/models",
                "opaque": canary,
                "api-key": canary,
            },
        }
    )

    assert canary not in repr(scrubbed)
    assert scrubbed["category"] == "provider"
    assert scrubbed["data"]["route"] == "/models"
