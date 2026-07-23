from app.services.observability import configure_sentry


def test_sentry_is_disabled_without_dsn():
    assert configure_sentry(dsn="", environment="test") is False
