from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.config import settings


@dataclass
class ImportedUrl:
    url: str
    title: str
    filename: str
    text: str
    metadata: dict


class ReadableHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self._in_title = False
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in {"p", "div", "section", "article", "h1", "h2", "h3", "li", "br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str):
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag in {"p", "div", "section", "article", "h1", "h2", "h3", "li"}:
            self.parts.append("\n")

    def handle_data(self, data: str):
        if self._skip_depth:
            return
        cleaned = " ".join(data.split())
        if not cleaned:
            return
        if self._in_title:
            self.title = f"{self.title} {cleaned}".strip()
        else:
            self.parts.append(cleaned)

    def readable_text(self) -> str:
        text = " ".join(self.parts)
        text = re.sub(r"\s*\n\s*", "\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


class SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_url(url: str, title: str = "", timeout: float = 12, max_bytes: int = 2_000_000) -> ImportedUrl:
    parsed = _validate_public_url(url)
    request = Request(
        url,
        headers={
            "User-Agent": "PersonalMultimodalRAG/0.1 (+local import)",
            "Accept": "text/html,text/plain,application/xhtml+xml",
        },
    )
    opener = build_opener(SafeRedirectHandler())
    with opener.open(request, timeout=timeout) as response:
        _validate_public_url(response.geturl())
        content_type = response.headers.get("content-type", "")
        raw = response.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError(f"URL content is too large; max {max_bytes} bytes")
    encoding = _encoding_from_content_type(content_type)
    body = raw.decode(encoding, errors="ignore")
    if "html" in content_type.lower() or "<html" in body[:500].lower():
        parser = ReadableHTMLParser()
        parser.feed(body)
        text = parser.readable_text()
        resolved_title = title or parser.title or parsed.netloc
        parser_name = "url_html"
    else:
        text = body
        resolved_title = title or PathishName(parsed.path) or parsed.netloc
        parser_name = "url_text"
    filename = _safe_filename(resolved_title, parsed.netloc)
    return ImportedUrl(
        url=url,
        title=resolved_title,
        filename=filename,
        text=text,
        metadata={
            "parser": parser_name,
            "source_url": url,
            "content_type": content_type,
            "host": parsed.netloc,
        },
    )


def is_blocked_host(hostname: str) -> bool:
    if settings.allow_private_urls:
        return False

    normalized = hostname.strip().rstrip(".").lower()
    if not normalized or normalized == "localhost" or normalized.endswith(".localhost"):
        return True

    addresses: set[str] = set()
    try:
        addresses.add(str(ipaddress.ip_address(normalized.split("%", 1)[0])))
    except ValueError:
        try:
            for result in socket.getaddrinfo(normalized, None, type=socket.SOCK_STREAM):
                addresses.add(result[4][0].split("%", 1)[0])
        except OSError:
            return True

    if not addresses:
        return True
    for address in addresses:
        try:
            if not ipaddress.ip_address(address).is_global:
                return True
        except ValueError:
            return True
    return False


def _validate_public_url(url: str):
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("Only http/https URLs are supported")
    if not parsed.hostname:
        raise ValueError("URL must include a valid hostname")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URLs with embedded credentials are not supported")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("URL contains an invalid port") from exc
    if is_blocked_host(parsed.hostname):
        raise ValueError("URL resolves to a private, special, or blocked address")
    return parsed


def PathishName(path: str) -> str:
    name = path.rstrip("/").split("/")[-1]
    return name or ""


def _encoding_from_content_type(content_type: str) -> str:
    match = re.search(r"charset=([^;\s]+)", content_type, flags=re.IGNORECASE)
    return match.group(1) if match else "utf-8"


def _safe_filename(title: str, fallback: str) -> str:
    base = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", title.strip()).strip("-")
    if not base:
        base = fallback or "url-import"
    return f"{base[:80]}.url.txt"
