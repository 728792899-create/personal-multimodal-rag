from app.services.safe_logging import redact_sensitive_text, sanitize_url_for_log


def test_sensitive_values_and_authorization_headers_are_redacted():
    message = "Authorization: Bearer sk-secret OPENAI_API_KEY=sk-another password=hunter2"

    cleaned = redact_sensitive_text(message)

    assert "sk-secret" not in cleaned
    assert "sk-another" not in cleaned
    assert "hunter2" not in cleaned
    assert cleaned.count("[REDACTED]") >= 3


def test_url_logging_drops_credentials_query_and_fragment():
    safe = sanitize_url_for_log("https://user:pass@example.com/private/path?token=secret#section")

    assert safe == "https://example.com/private/path"
