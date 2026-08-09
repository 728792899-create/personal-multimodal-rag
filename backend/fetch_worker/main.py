from __future__ import annotations

import base64

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.services.pinned_fetch import fetch_raw_url
from app.services.safe_logging import redact_sensitive_text
from app.services.url_importer import imported_url_from_payload


class FetchRequest(BaseModel):
    url: str = Field(..., min_length=8, max_length=4096)
    title: str = Field("", max_length=300)
    mode: str = Field("readable", pattern="^(readable|raw)$")
    timeout_seconds: float = Field(12, ge=1, le=30)
    max_bytes: int = Field(2_000_000, ge=1, le=20_000_000)
    etag: str = Field("", max_length=500)
    last_modified: str = Field("", max_length=500)


app = FastAPI(title="RAG isolated fetch worker", version="1.0.0-rc.1")


@app.get("/health")
def health():
    return {"status": "ok", "capabilities": ["dns-pinning", "redirect-revalidation", "size-limit"]}


@app.post("/v1/fetch")
def fetch(payload: FetchRequest):
    headers = {}
    if payload.etag:
        headers["If-None-Match"] = payload.etag
    if payload.last_modified:
        headers["If-Modified-Since"] = payload.last_modified
    try:
        response = fetch_raw_url(
            payload.url,
            timeout=payload.timeout_seconds,
            max_bytes=payload.max_bytes,
            headers=headers,
        )
        if response.status == 304:
            return {
                "status": 304,
                "url": response.url,
                "headers": response.headers,
                "payload_base64": "",
            }
        if response.status >= 400:
            raise ValueError(f"remote server returned HTTP {response.status}")
        if payload.mode == "raw":
            return {
                "status": response.status,
                "url": response.url,
                "headers": response.headers,
                "payload_base64": base64.b64encode(response.payload).decode("ascii"),
            }
        imported = imported_url_from_payload(
            response.url,
            response.payload,
            response.headers.get("content-type", ""),
            title=payload.title,
        )
        return {
            "status": response.status,
            "url": response.url,
            "headers": response.headers,
            "imported": {
                "url": imported.url,
                "title": imported.title,
                "filename": imported.filename,
                "text": imported.text,
                "metadata": imported.metadata,
            },
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=redact_sensitive_text(exc)) from exc
