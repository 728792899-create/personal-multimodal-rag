from app.services.safe_logging import (
    public_error_message,
    redact_private_metadata,
    redact_sensitive_text,
    sanitize_url_for_log,
)


def test_sensitive_values_and_authorization_headers_are_redacted():
    message = "Authorization: Bearer sk-secret OPENAI_API_KEY=sk-another password=hunter2"

    cleaned = redact_sensitive_text(message)

    assert "sk-secret" not in cleaned
    assert "sk-another" not in cleaned
    assert "hunter2" not in cleaned
    assert cleaned.count("[REDACTED]") >= 3


def test_sensitive_values_inside_stringified_json_are_redacted():
    canary = "telemetry-canary-json"

    cleaned = redact_sensitive_text(
        f'provider={{"api_key":"{canary}","credential":"{canary}"}}'
    )

    assert canary not in cleaned
    assert cleaned.count("[REDACTED]") == 2


def test_url_logging_drops_credentials_query_and_fragment():
    safe = sanitize_url_for_log("https://user:pass@example.com/private/path?token=secret#section")

    assert safe == "https://example.com/private/path"


def test_public_metadata_removes_internal_paths_recursively():
    cleaned = redact_private_metadata(
        {
            "source_path": "/private/upload.pdf",
            "heading_path": ["Architecture"],
            "nested": {"object_key": "ab/hash", "bbox": [1, 2, 3, 4]},
        }
    )

    assert cleaned == {"heading_path": ["Architecture"], "nested": {"bbox": [1, 2, 3, 4]}}


def test_public_error_message_always_uses_application_owned_fallback():
    hidden = public_error_message(
        RuntimeError(
            "解析失败：/Users/private/customer.pdf；"
            "请查看 https://private.example/doc?id=42；"
            "OPENAI_API_KEY=sk-secret-value"
        ),
        "回答服务暂时不可用，请稍后重试。",
    )

    assert hidden == "回答服务暂时不可用，请稍后重试。"
    assert "/Users/private" not in hidden
    assert "private.example" not in hidden
    assert "sk-secret-value" not in hidden
