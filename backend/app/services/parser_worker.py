from __future__ import annotations

import hashlib
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

import httpx

from app.models.domain import Document, DocumentElement, DocumentPage
from app.services.resilience import ResilientExecutor


PARSER_PROFILES = ("builtin", "auto", "mineru", "docling", "paddleocr")


class ParserWorkerClient:
    """Small HTTP adapter for the optional, isolated heavy-parser service."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 300,
        http_client: httpx.Client | None = None,
        poll_seconds: float = 0.25,
        executor: ResilientExecutor | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        # Keep provider selection import-safe in environments with incomplete
        # host proxy extras. Internal parser traffic also must not use proxies.
        self.http_client = http_client
        self.poll_seconds = poll_seconds
        self.executor = executor or ResilientExecutor("parser_worker", base_delay_seconds=0.2)

    def _client(self) -> httpx.Client:
        if self.http_client is None:
            self.http_client = httpx.Client(timeout=min(self.timeout_seconds, 30), trust_env=False)
        return self.http_client

    def capabilities(self) -> dict:
        response = self.executor.run(lambda: self._checked(self._client().get(f"{self.base_url}/v1/capabilities")))
        payload = response.json()
        return payload if isinstance(payload, dict) else {"profiles": []}

    def parse(
        self,
        path: Path,
        original_name: str,
        profile: str,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict:
        if profile not in PARSER_PROFILES or profile == "builtin":
            raise ValueError("A heavy parser profile is required")
        with path.open("rb") as handle:
            def submit_job():
                handle.seek(0)
                return self._client().post(
                    f"{self.base_url}/v1/jobs",
                    data={"profile": profile},
                    files={"file": (Path(original_name).name, handle, "application/octet-stream")},
                )

            response = self.executor.run(
                lambda: self._checked(submit_job())
            )
        job_id = str(response.json().get("id") or "")
        if not job_id:
            raise ValueError("Parser worker returned no job id")
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            if cancel_check and cancel_check():
                self._client().delete(f"{self.base_url}/v1/jobs/{job_id}")
                raise ValueError("Parser job cancelled")
            status = self.executor.run(
                lambda: self._checked(self._client().get(f"{self.base_url}/v1/jobs/{job_id}"))
            )
            payload = status.json()
            state = payload.get("status")
            if state == "succeeded":
                result = payload.get("result")
                if not isinstance(result, dict):
                    raise ValueError("Parser worker returned an invalid result")
                self._cleanup(job_id)
                return result
            if state in {"failed", "cancelled"}:
                error = str(payload.get("error") or f"Parser job {state}")
                self._cleanup(job_id)
                raise ValueError(error)
            time.sleep(self.poll_seconds)
        self._client().delete(f"{self.base_url}/v1/jobs/{job_id}")
        raise TimeoutError("Parser worker timed out")

    def _cleanup(self, job_id: str) -> None:
        try:
            self._client().delete(f"{self.base_url}/v1/jobs/{job_id}")
        except httpx.HTTPError:
            pass

    @staticmethod
    def _checked(response: httpx.Response) -> httpx.Response:
        response.raise_for_status()
        return response


def document_from_content_list(
    content_list: list[dict],
    *,
    source_path: Path,
    original_name: str,
    parser_name: str,
) -> Document:
    """Convert RAG-Anything-style content blocks into the native typed IR."""

    document_id = str(uuid.uuid4())
    elements: list[DocumentElement] = []
    page_text: dict[int | None, list[str]] = {}
    heading_path: list[str] = []
    for raw in content_list:
        if not isinstance(raw, dict):
            continue
        raw_type = str(raw.get("type") or "text").lower()
        page_number = _page_number(raw.get("page_idx"))
        if raw_type == "text":
            text = str(raw.get("text") or "").strip()
            level = int(raw.get("text_level") or 0)
            element_type = "heading" if 1 <= level <= 6 else "text"
            if element_type == "heading":
                heading_path = heading_path[: level - 1] + [text]
                rendered = f"{'#' * level} {text}"
            else:
                rendered = text
            element = _element(document_id, elements, element_type, rendered, page_number, heading_path, raw)
        elif raw_type == "image":
            captions = raw.get("image_caption") or raw.get("img_caption") or []
            caption = " ".join(str(item) for item in captions) if isinstance(captions, list) else str(captions or "")
            text = caption or f"Image on page {page_number or 1}"
            element = _element(document_id, elements, "image", text, page_number, heading_path, raw)
            element.caption = caption
        elif raw_type == "table":
            body = str(raw.get("table_body") or raw.get("table_data") or "").strip()
            rows = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in body.splitlines() if line.strip()]
            element = _element(document_id, elements, "table", body, page_number, heading_path, raw)
            element.table = rows
            element.caption = str(raw.get("table_caption") or "")
        elif raw_type in {"equation", "formula"}:
            latex = str(raw.get("latex") or raw.get("equation") or raw.get("text") or "").strip()
            element = _element(document_id, elements, "equation", latex, page_number, heading_path, raw)
            element.latex = latex
        else:
            text = str(raw.get("text") or raw.get("content") or "").strip()
            element = _element(document_id, elements, "text", text, page_number, heading_path, raw)
        if element.text:
            elements.append(element)
            page_text.setdefault(page_number, []).append(element.text)

    pages = [
        DocumentPage(page_number=page, text="\n\n".join(parts), metadata={"parser": parser_name})
        for page, parts in sorted(page_text.items(), key=lambda item: (-1 if item[0] is None else item[0]))
    ]
    if not pages:
        raise ValueError("Parser worker returned no readable content")
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    return Document(
        document_id=document_id,
        file_name=Path(original_name).name,
        file_path=str(source_path),
        file_type=_file_type(Path(original_name).suffix.lower()),
        title=Path(original_name).stem,
        created_at=datetime.utcnow(),
        pages=pages,
        elements=elements,
        metadata={
            "parser": parser_name,
            "parser_provider": "raganything_worker",
            "content_hash": digest,
            "index_status": "parsed",
        },
    )


def _element(document_id, elements, element_type, text, page_number, heading_path, raw):
    safe_metadata = {
        key: value
        for key, value in raw.items()
        if key in {"page_idx", "text_level", "confidence", "bbox", "category", "format"}
    }
    element = DocumentElement(
        element_id=f"{document_id}:element:{len(elements)}",
        document_id=document_id,
        type=element_type,
        order=len(elements),
        text=text,
        page_number=page_number,
        heading_path=list(heading_path),
        confidence=float(raw["confidence"]) if isinstance(raw.get("confidence"), (int, float)) else None,
        metadata=safe_metadata,
    )
    bbox = raw.get("bbox")
    if isinstance(bbox, list) and len(bbox) == 4 and all(isinstance(value, (int, float)) for value in bbox):
        element.bbox = [float(value) for value in bbox]
    return element


def _page_number(value) -> int | None:
    if isinstance(value, int):
        return value + 1
    return None


def _file_type(suffix: str) -> str:
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".docx":
        return "docx"
    if suffix in {".md", ".markdown"}:
        return "markdown"
    if suffix in {".png", ".jpg", ".jpeg"}:
        return "image"
    return "text"
