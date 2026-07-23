from __future__ import annotations

import base64

import httpx

from app.services.url_importer import ImportedUrl


class FetchWorkerClient:
    def __init__(self, base_url: str, *, timeout_seconds: float = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def fetch_url(self, url: str, title: str = "", timeout: float = 12, max_bytes: int = 2_000_000) -> ImportedUrl:
        payload = self._request(
            {
                "url": url,
                "title": title,
                "mode": "readable",
                "timeout_seconds": timeout,
                "max_bytes": max_bytes,
            }
        )
        imported = payload["imported"]
        return ImportedUrl(**imported)

    def fetch_feed(
        self,
        url: str,
        *,
        etag: str,
        last_modified: str,
        timeout: float,
        max_bytes: int,
    ) -> dict:
        payload = self._request(
            {
                "url": url,
                "mode": "raw",
                "timeout_seconds": timeout,
                "max_bytes": max_bytes,
                "etag": etag,
                "last_modified": last_modified,
            }
        )
        status = int(payload.get("status") or 200)
        headers = payload.get("headers") or {}
        return {
            "payload": base64.b64decode(payload.get("payload_base64") or ""),
            "not_modified": status == 304,
            "etag": headers.get("etag", etag),
            "last_modified": headers.get("last-modified", last_modified),
        }

    def health(self) -> bool:
        response = httpx.get(f"{self.base_url}/health", timeout=3, trust_env=False)
        return response.status_code == 200

    def _request(self, payload: dict) -> dict:
        response = httpx.post(
            f"{self.base_url}/v1/fetch",
            json=payload,
            timeout=self.timeout_seconds,
            trust_env=False,
        )
        response.raise_for_status()
        return response.json()
