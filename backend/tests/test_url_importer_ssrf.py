import pytest

from app.config import settings
from app.services.url_importer import SafeRedirectHandler, fetch_url, is_blocked_host


@pytest.mark.parametrize(
    "hostname",
    ["127.0.0.1", "0.0.0.0", "169.254.169.254", "::1", "localhost"],
)
def test_private_and_special_hosts_are_blocked(hostname):
    assert is_blocked_host(hostname) is True


def test_public_host_is_allowed_when_dns_resolves_globally(monkeypatch):
    monkeypatch.setattr(
        "app.services.url_importer.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )

    assert is_blocked_host("example.com") is False


def test_fetch_rejects_loopback_before_opening_connection():
    with pytest.raises(ValueError, match="private|special|blocked"):
        fetch_url("http://127.0.0.1/internal")


def test_redirect_to_private_address_is_rejected():
    handler = SafeRedirectHandler()

    with pytest.raises(ValueError, match="private|special|blocked"):
        handler.redirect_request(
            req=None,
            fp=None,
            code=302,
            msg="Found",
            headers={},
            newurl="http://169.254.169.254/latest/meta-data",
        )


def test_explicit_private_url_override(monkeypatch):
    monkeypatch.setattr(settings, "allow_private_urls", True)

    assert is_blocked_host("127.0.0.1") is False
