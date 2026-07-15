from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit


_SENSITIVE_PATTERNS = (
    re.compile(r"(?i)(authorization\s*:\s*bearer)\s+[^\s,;]+"),
    re.compile(r"(?i)\b([A-Za-z0-9_-]*(?:api[_-]?key|token|password|secret))\s*[:=]\s*[^\s,;]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
)
_PRIVATE_METADATA_KEYS = {
    "source_path",
    "image_path",
    "file_path",
    "staged_path",
    "object_key",
    "local_path",
    "output_dir",
}


def redact_sensitive_text(value: object) -> str:
    """Return a bounded, log-safe representation of an error or message."""

    cleaned = str(value)
    cleaned = _SENSITIVE_PATTERNS[0].sub(r"\1 [REDACTED]", cleaned)
    cleaned = _SENSITIVE_PATTERNS[1].sub(lambda match: f"{match.group(1)}=[REDACTED]", cleaned)
    cleaned = _SENSITIVE_PATTERNS[2].sub("[REDACTED]", cleaned)
    return cleaned[:1_000]


def sanitize_url_for_log(value: str) -> str:
    """Keep only the public routing portion of a URL in logs."""

    try:
        parsed = urlsplit(value)
        if not parsed.scheme or not parsed.hostname:
            return "[invalid-url]"
        host = parsed.hostname
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
        return urlunsplit((parsed.scheme.lower(), host, parsed.path or "/", "", ""))
    except (TypeError, ValueError):
        return "[invalid-url]"


def redact_private_metadata(value):
    """Remove internal filesystem/object coordinates from public JSON payloads."""

    if isinstance(value, dict):
        return {
            key: redact_private_metadata(item)
            for key, item in value.items()
            if str(key).lower() not in _PRIVATE_METADATA_KEYS
        }
    if isinstance(value, list):
        return [redact_private_metadata(item) for item in value]
    return value
