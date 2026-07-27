from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from app.config import settings


@dataclass(frozen=True)
class RawFetchResponse:
    status: int
    url: str
    headers: dict[str, str]
    payload: bytes


def resolve_public_addresses(hostname: str) -> list[str]:
    if settings.allow_private_urls:
        return [result[4][0].split("%", 1)[0] for result in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)]
    addresses: set[str] = set()
    for result in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM):
        address = result[4][0].split("%", 1)[0]
        if not ipaddress.ip_address(address).is_global:
            raise ValueError("URL 解析到私有、特殊或已阻止的地址。")
        addresses.add(address)
    if not addresses:
        raise ValueError("URL 主机名无法解析。")
    return sorted(addresses)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, pinned_ip: str, timeout: float):
        super().__init__(host, port=port, timeout=timeout)
        self.pinned_ip = pinned_ip

    def connect(self) -> None:
        self.sock = socket.create_connection((self.pinned_ip, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, pinned_ip: str, timeout: float):
        super().__init__(host, port=port, timeout=timeout, context=ssl.create_default_context())
        self.pinned_ip = pinned_ip

    def connect(self) -> None:
        sock = socket.create_connection((self.pinned_ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def fetch_raw_url(
    url: str,
    *,
    timeout: float,
    max_bytes: int,
    headers: dict[str, str] | None = None,
    max_redirects: int = 5,
) -> RawFetchResponse:
    """Fetch through one DNS-pinned socket per hop and revalidate every redirect."""
    current = url
    for redirect_index in range(max_redirects + 1):
        parsed = urlsplit(current)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise ValueError("仅支持绝对 http/https URL。")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("不支持包含凭据的 URL。")
        try:
            port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
        except ValueError as exc:
            raise ValueError("URL 包含无效端口。") from exc
        pinned_ip = resolve_public_addresses(parsed.hostname)[0]
        connection_class = _PinnedHTTPSConnection if parsed.scheme.lower() == "https" else _PinnedHTTPConnection
        connection = connection_class(parsed.hostname, port, pinned_ip, timeout)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        request_headers = {
            "Host": parsed.netloc,
            "User-Agent": "PersonalMultimodalRAG-FetchWorker/0.4",
            "Accept": "*/*",
            "Connection": "close",
            **(headers or {}),
        }
        try:
            connection.request("GET", path, headers=request_headers)
            response = connection.getresponse()
            response_headers = {key.lower(): value for key, value in response.getheaders()}
            if response.status in {301, 302, 303, 307, 308}:
                location = response_headers.get("location", "")
                response.read()
                if not location:
                    raise ValueError("重定向响应缺少 Location。")
                if redirect_index >= max_redirects:
                    raise ValueError("URL 超过允许的重定向次数。")
                current = urljoin(current, location)
                continue
            payload = response.read(max_bytes + 1)
            if len(payload) > max_bytes:
                raise ValueError(f"URL 内容过大，最大允许 {max_bytes} bytes。")
            return RawFetchResponse(
                status=response.status,
                url=current,
                headers=response_headers,
                payload=payload,
            )
        finally:
            connection.close()
    raise ValueError("URL 超过允许的重定向次数。")
