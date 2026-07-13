from __future__ import annotations

import logging


logger = logging.getLogger(__name__)


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
    )
    return True
