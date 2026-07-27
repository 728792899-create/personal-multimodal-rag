from __future__ import annotations

import pytest

from app.services import pinned_fetch


def test_pinned_connection_uses_the_validated_ip(monkeypatch):
    calls = []
    fake_socket = object()
    monkeypatch.setattr(
        pinned_fetch.socket,
        "create_connection",
        lambda address, timeout: calls.append((address, timeout)) or fake_socket,
    )
    connection = pinned_fetch._PinnedHTTPConnection(
        "public.example",
        80,
        "93.184.216.34",
        4.0,
    )

    connection.connect()

    assert connection.sock is fake_socket
    assert calls == [(("93.184.216.34", 80), 4.0)]


def test_mixed_dns_answer_is_rejected(monkeypatch):
    monkeypatch.setattr(
        pinned_fetch.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (2, 1, 6, "", ("93.184.216.34", 0)),
            (2, 1, 6, "", ("127.0.0.1", 0)),
        ],
    )

    with pytest.raises(ValueError, match="私有|特殊|阻止"):
        pinned_fetch.resolve_public_addresses("rebinding.example")


def test_redirect_is_resolved_and_validated_as_a_new_hop(monkeypatch):
    class Response:
        status = 302

        def getheaders(self):
            return [("Location", "http://169.254.169.254/latest/meta-data")]

        def read(self, *_args):
            return b""

    class Connection:
        def __init__(self, *_args):
            pass

        def request(self, *_args, **_kwargs):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    def resolve(hostname: str):
        if hostname == "public.example":
            return ["93.184.216.34"]
        raise ValueError("URL 解析到私有、特殊或已阻止的地址。")

    monkeypatch.setattr(pinned_fetch, "_PinnedHTTPConnection", Connection)
    monkeypatch.setattr(pinned_fetch, "resolve_public_addresses", resolve)

    with pytest.raises(ValueError, match="私有|特殊|阻止"):
        pinned_fetch.fetch_raw_url(
            "http://public.example/start",
            timeout=2,
            max_bytes=1000,
        )
