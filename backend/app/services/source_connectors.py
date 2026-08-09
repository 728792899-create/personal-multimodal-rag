from __future__ import annotations

import hashlib
import mimetypes
import os
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener

from app.services.document_processor import SUPPORTED_EXTENSIONS
from app.services.safe_logging import public_error_message
from app.services.url_importer import SafeRedirectHandler, _validate_public_url, fetch_url


@dataclass(frozen=True)
class SourceCandidate:
    external_id: str
    location: str
    title: str
    filename: str
    media_type: str
    payload: bytes
    content_hash: str
    etag: str = ""
    last_modified: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class DiscoveryResult:
    candidates: list[SourceCandidate]
    failures: list[str] = field(default_factory=list)
    complete: bool = True
    empty_result: bool = False
    not_modified: bool = False
    source_metadata: dict = field(default_factory=dict)


class SourceRootResolver:
    def __init__(self, configured_roots: str):
        self._roots: dict[str, Path] = {}
        for raw in configured_roots.split(os.pathsep):
            value = raw.strip()
            if not value:
                continue
            path = Path(value).expanduser().resolve()
            root_id = f"root-{hashlib.sha256(str(path).encode()).hexdigest()[:12]}"
            self._roots[root_id] = path

    def public_roots(self) -> list[dict]:
        return [
            {"id": root_id, "label": path.name or "source-root"}
            for root_id, path in sorted(self._roots.items())
        ]

    def resolve(self, root_id: str, relative_path: str = "") -> Path:
        root = self._roots.get(root_id)
        if root is None:
            raise ValueError("未找到指定的数据源根目录。")
        relative = Path(relative_path or ".")
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("数据源路径必须位于允许的根目录内，并使用相对路径。")
        candidate = (root / relative).resolve()
        if candidate != root and root not in candidate.parents:
            raise ValueError("数据源路径超出允许的根目录。")
        if not candidate.is_dir():
            raise ValueError("数据源目录不存在。")
        return candidate


class DirectoryConnector:
    type = "local_directory"

    def __init__(self, resolver: SourceRootResolver, *, max_items: int, max_bytes: int):
        self.resolver = resolver
        self.max_items = max(1, int(max_items))
        self.max_bytes = max(1, int(max_bytes))

    def discover(self, source: dict) -> DiscoveryResult:
        config = source["config"]
        root = self.resolver.resolve(
            str(config.get("root_id") or ""),
            str(config.get("relative_path") or ""),
        )
        recursive = bool(config.get("recursive", True))
        paths = root.rglob("*") if recursive else root.glob("*")
        candidates: list[SourceCandidate] = []
        failures: list[str] = []
        for path in sorted(paths):
            if len(candidates) >= self.max_items:
                failures.append(f"已达到条目上限（{self.max_items}）")
                break
            if path.is_symlink() or not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            try:
                resolved = path.resolve()
                if resolved != root and root not in resolved.parents:
                    raise ValueError("文件超出所选数据源目录。")
                if resolved.stat().st_size > self.max_bytes:
                    raise ValueError(f"文件超过 {self.max_bytes} bytes。")
                payload = resolved.read_bytes()
                relative = resolved.relative_to(root).as_posix()
                digest = hashlib.sha256(payload).hexdigest()
                candidates.append(
                    SourceCandidate(
                        external_id=relative,
                        location=relative,
                        title=resolved.name,
                        filename=resolved.name,
                        media_type=mimetypes.guess_type(resolved.name)[0] or "application/octet-stream",
                        payload=payload,
                        content_hash=digest,
                        metadata={"connector": self.type, "relative_path": relative},
                    )
                )
            except Exception as exc:
                failures.append(
                    f"{path.name}：{public_error_message(exc, '文件读取失败。')}"
                )
        return DiscoveryResult(
            candidates=candidates,
            failures=failures,
            complete=not failures,
            empty_result=not candidates,
        )


class UrlListConnector:
    type = "url_list"

    def __init__(self, *, timeout: float, max_bytes: int, max_items: int, fetcher=fetch_url):
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.max_items = max_items
        self.fetcher = fetcher

    def discover(self, source: dict) -> DiscoveryResult:
        urls = list(dict.fromkeys(str(item).strip() for item in source["config"].get("urls", []) if str(item).strip()))
        candidates: list[SourceCandidate] = []
        failures: list[str] = []
        for url in urls[: self.max_items]:
            try:
                candidates.append(self._candidate(url))
            except Exception as exc:
                failures.append(
                    public_error_message(exc, "URL 内容读取失败。")
                )
        if len(urls) > self.max_items:
            failures.append(f"已达到条目上限（{self.max_items}）")
        return DiscoveryResult(
            candidates=candidates,
            failures=failures,
            complete=not failures,
            empty_result=not candidates and not failures,
        )

    def _candidate(self, url: str, *, title: str = "", external_id: str = "") -> SourceCandidate:
        imported = self.fetcher(url, title=title, timeout=self.timeout, max_bytes=self.max_bytes)
        payload = imported.text.encode("utf-8")
        return SourceCandidate(
            external_id=external_id or url,
            location=url,
            title=imported.title,
            filename=imported.filename,
            media_type="text/plain; charset=utf-8",
            payload=payload,
            content_hash=hashlib.sha256(payload).hexdigest(),
            metadata={
                "connector": self.type,
                "source_url": imported.url,
                "content_type": imported.metadata.get("content_type", ""),
            },
        )


class FeedConnector(UrlListConnector):
    type = "rss_atom"

    def __init__(self, *, feed_fetcher=None, **kwargs):
        super().__init__(**kwargs)
        self.feed_fetcher = feed_fetcher or self._fetch_feed

    def discover(self, source: dict) -> DiscoveryResult:
        config = source["config"]
        feed_url = str(config.get("feed_url") or "")
        try:
            response = self.feed_fetcher(
                feed_url,
                etag=str(config.get("etag") or ""),
                last_modified=str(config.get("last_modified") or ""),
                timeout=self.timeout,
                max_bytes=self.max_bytes,
            )
        except Exception as exc:
            return DiscoveryResult(
                candidates=[],
                failures=[public_error_message(exc, "订阅源读取失败。")],
                complete=False,
            )
        if response["not_modified"]:
            return DiscoveryResult(
                candidates=[],
                not_modified=True,
                source_metadata={
                    "etag": response.get("etag", ""),
                    "last_modified": response.get("last_modified", ""),
                },
            )
        try:
            entries = self._parse_entries(response["payload"])
        except Exception as exc:
            return DiscoveryResult(
                candidates=[],
                failures=[public_error_message(exc, "订阅源内容解析失败。")],
                complete=False,
            )
        candidates: list[SourceCandidate] = []
        failures: list[str] = []
        for entry in entries[: self.max_items]:
            try:
                candidates.append(
                    self._candidate(
                        entry["url"],
                        title=entry["title"],
                        external_id=entry["external_id"],
                    )
                )
            except Exception as exc:
                failures.append(
                    public_error_message(exc, "订阅条目读取失败。")
                )
        if len(entries) > self.max_items:
            failures.append(f"已达到条目上限（{self.max_items}）")
        return DiscoveryResult(
            candidates=candidates,
            failures=failures,
            complete=not failures,
            empty_result=not entries,
            source_metadata={
                "etag": response.get("etag", ""),
                "last_modified": response.get("last_modified", ""),
            },
        )

    @staticmethod
    def _fetch_feed(
        url: str,
        *,
        etag: str,
        last_modified: str,
        timeout: float,
        max_bytes: int,
    ) -> dict:
        _validate_public_url(url)
        headers = {
            "User-Agent": "PersonalMultimodalRAG/0.4 (+source sync)",
            "Accept": "application/rss+xml,application/atom+xml,application/xml,text/xml",
        }
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        request = Request(url, headers=headers)
        try:
            with build_opener(SafeRedirectHandler()).open(request, timeout=timeout) as response:
                _validate_public_url(response.geturl())
                payload = response.read(max_bytes + 1)
                if len(payload) > max_bytes:
                    raise ValueError(f"订阅源超过 {max_bytes} bytes。")
                return {
                    "payload": payload,
                    "not_modified": False,
                    "etag": response.headers.get("etag", ""),
                    "last_modified": response.headers.get("last-modified", ""),
                }
        except HTTPError as exc:
            if exc.code == 304:
                return {
                    "payload": b"",
                    "not_modified": True,
                    "etag": etag,
                    "last_modified": last_modified,
                }
            raise

    @staticmethod
    def _parse_entries(payload: bytes) -> list[dict]:
        upper = payload[:4096].upper()
        if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
            raise ValueError("订阅源不允许包含 DTD 或 entity 声明。")
        root = ElementTree.fromstring(payload)

        def local(element) -> str:
            return element.tag.rsplit("}", 1)[-1].lower()

        entries: list[dict] = []
        for node in root.iter():
            if local(node) not in {"item", "entry"}:
                continue
            title = ""
            link = ""
            guid = ""
            for child in list(node):
                kind = local(child)
                if kind == "title" and child.text:
                    title = child.text.strip()
                elif kind == "link":
                    link = (child.attrib.get("href") or child.text or "").strip()
                elif kind in {"guid", "id"} and child.text:
                    guid = child.text.strip()
            if link:
                entries.append(
                    {
                        "url": link,
                        "title": title,
                        "external_id": guid or link,
                    }
                )
        return entries


class ConnectorRegistry:
    def __init__(self, connectors: list):
        self.connectors = {connector.type: connector for connector in connectors}

    def get(self, source_type: str):
        try:
            return self.connectors[source_type]
        except KeyError as exc:
            raise ValueError("不支持该数据源类型。") from exc

    def capabilities(self) -> list[str]:
        return sorted(self.connectors)
