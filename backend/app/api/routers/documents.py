from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.api.common import (
    chunk_payload,
    chunks_for_document,
    document_summary,
    friendly_index_error,
    index_document,
)
from app.config import settings
from app.core.store import processor, registry, retriever
from app.models.domain import Document
from app.models.schemas import UrlImportRequest
from app.services.document_quality import assess_document_quality, lifecycle_event, summarize_document
from app.services.document_processor import SUPPORTED_EXTENSIONS
from app.services.safe_logging import redact_sensitive_text, sanitize_url_for_log
from app.services.url_importer import fetch_url


router = APIRouter(tags=["documents"])
DATA_DIR = Path(__file__).resolve().parents[4] / "data" / "uploads"
DATA_DIR.mkdir(parents=True, exist_ok=True)


@router.get("/documents")
def list_documents():
    return {
        "documents": [
            document_summary(doc, chunks_for_document(doc.document_id))
            for doc in registry.load_documents()
        ]
    }


@router.get("/documents/{document_id}")
def get_document(document_id: str):
    doc = registry.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    chunks = sorted(chunks_for_document(document_id), key=lambda item: item.chunk_index)
    return {
        "document": {
            **document_summary(doc, chunks),
            "title": doc.title,
            "created_at": doc.created_at.isoformat(),
            "page_count": len(doc.pages),
            "pages": [
                {"page_number": page.page_number, "text": page.text, "metadata": page.metadata}
                for page in doc.pages
            ],
        },
        "chunks": [chunk_payload(chunk) for chunk in chunks],
    }


@router.post("/documents")
async def upload_document(file: UploadFile = File(...)):
    target: Path | None = None
    keep_target = False
    safe_name = ""
    try:
        safe_name = safe_upload_name(file.filename)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        target = DATA_DIR / f"{uuid.uuid4().hex}-{safe_name}"
        upload_started = datetime.utcnow()
        with target.open("wb") as handle:
            written = 0
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File is too large; max {settings.max_upload_bytes} bytes",
                    )
                handle.write(chunk)
        if written == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
        validate_file_signature(target, safe_name)
        upload_ended = datetime.utcnow()
        parse_started = datetime.utcnow()
        doc = processor.parse_file(target, original_name=safe_name)
        parse_ended = datetime.utcnow()
        existing = registry.find_by_content_hash(doc.metadata.get("content_hash", ""))
        if existing:
            chunks = chunks_for_document(existing.document_id)
            registry.log_operation(
                "document_deduped",
                f"重复文档已复用：{existing.file_name}",
                {"document_id": existing.document_id, "filename": existing.file_name, "incoming_filename": safe_name},
            )
            return {
                "deduped": True,
                "document": document_summary(existing, chunks),
                "chunks": [chunk_payload(chunk) for chunk in sorted(chunks, key=lambda item: item.index)[:5]],
            }
        doc, chunks = index_document(
            doc,
            [
                lifecycle_event("upload", "success", upload_started, upload_ended),
                lifecycle_event("parse", "success", parse_started, parse_ended),
            ],
        )
        keep_target = True
        registry.log_operation(
            "document_uploaded",
            f"上传并索引文档：{doc.file_name}",
            {
                "document_id": doc.document_id,
                "filename": doc.file_name,
                "chunk_count": len(chunks),
                "quality_score": doc.metadata["quality"]["score"],
            },
        )
        return {
            "deduped": False,
            "document": document_summary(doc, chunks),
            "chunks": [chunk_payload(chunk) for chunk in chunks[:5]],
        }
    except HTTPException as exc:
        registry.log_operation(
            "document_upload_rejected",
            f"文档上传被拒绝：{safe_name or '未命名文件'}",
            {"filename": safe_name, "error": redact_sensitive_text(exc.detail), "status_code": exc.status_code},
            level="warning",
        )
        raise
    except ValueError as exc:
        message = friendly_index_error(exc)
        registry.log_operation(
            "document_upload_failed",
            f"文档上传或索引失败：{safe_name or '未命名文件'}",
            {"filename": safe_name, "error": message},
            level="error",
        )
        raise HTTPException(status_code=400, detail=message) from exc
    finally:
        if target is not None and not keep_target:
            target.unlink(missing_ok=True)
        await file.close()


def safe_upload_name(filename: str | None) -> str:
    normalized = (filename or "").strip().replace("\\", "/")
    safe_name = Path(normalized).name
    if not safe_name or safe_name in {".", ".."} or "\x00" in safe_name:
        raise HTTPException(status_code=400, detail="A valid filename is required")
    if len(safe_name.encode("utf-8")) > 240:
        raise HTTPException(status_code=400, detail="Filename is too long")
    suffix = Path(safe_name).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix or '(none)'}; allowed: {supported}")
    return safe_name


def validate_file_signature(path: Path, filename: str) -> None:
    signatures = {
        ".pdf": (b"%PDF-",),
        ".png": (b"\x89PNG\r\n\x1a\n",),
        ".jpg": (b"\xff\xd8\xff",),
        ".jpeg": (b"\xff\xd8\xff",),
    }
    expected = signatures.get(Path(filename).suffix.lower())
    if expected and not any(path.read_bytes()[:16].startswith(signature) for signature in expected):
        raise HTTPException(status_code=400, detail="File signature does not match its extension")


@router.post("/imports/url")
def import_url(payload: UrlImportRequest):
    safe_url = sanitize_url_for_log(payload.url)
    try:
        fetch_started = datetime.utcnow()
        imported = fetch_url(
            payload.url,
            title=payload.title,
            timeout=settings.url_import_timeout_seconds,
            max_bytes=settings.url_import_max_bytes,
        )
        fetch_ended = datetime.utcnow()
        parse_started = datetime.utcnow()
        doc = processor.parse_text_source(
            imported.text,
            imported.filename,
            source_url=imported.url,
            parser=imported.metadata.get("parser", "url_html"),
            metadata=imported.metadata,
        )
        doc.title = imported.title
        parse_ended = datetime.utcnow()
        existing = registry.find_by_content_hash(doc.metadata.get("content_hash", ""))
        if existing:
            chunks = chunks_for_document(existing.document_id)
            registry.log_operation("url_deduped", f"URL 已存在：{safe_url}", {"document_id": existing.document_id, "url": safe_url})
            return {
                "deduped": True,
                "document": document_summary(existing, chunks),
                "chunks": [chunk_payload(chunk) for chunk in sorted(chunks, key=lambda item: item.index)[:5]],
            }
        doc, chunks = index_document(
            doc,
            [
                lifecycle_event("fetch_url", "success", fetch_started, fetch_ended),
                lifecycle_event("parse", "success", parse_started, parse_ended),
            ],
        )
        registry.log_operation(
            "url_imported",
            f"导入 URL：{imported.title}",
            {"document_id": doc.document_id, "url": safe_url, "chunk_count": len(chunks), "quality_score": doc.metadata["quality"]["score"]},
        )
        return {"deduped": False, "document": document_summary(doc, chunks), "chunks": [chunk_payload(chunk) for chunk in chunks[:5]]}
    except Exception as exc:
        message = redact_sensitive_text(exc)
        registry.log_operation("url_import_failed", f"URL 导入失败：{safe_url}", {"url": safe_url, "error": message}, level="error")
        raise HTTPException(status_code=400, detail=message) from exc


@router.delete("/documents/{document_id}")
def delete_document(document_id: str):
    doc = registry.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    retriever.delete_document(document_id)
    registry.delete_document(document_id)
    source_deleted = delete_uploaded_source(doc)
    registry.log_operation(
        "document_deleted",
        f"删除文档：{doc.file_name}",
        {"document_id": document_id, "filename": doc.file_name, "source_deleted": source_deleted},
        level="warning",
    )
    return {"deleted": True, "document_id": document_id}


def delete_uploaded_source(doc: Document | None) -> bool:
    if not doc or not doc.file_path:
        return False
    source = Path(doc.file_path).resolve()
    upload_root = DATA_DIR.resolve()
    if source.parent != upload_root or not source.is_file():
        return False
    source.unlink()
    return True


def _rebuild(doc: Document) -> tuple[Document, list]:
    source_path = Path(doc.file_path)
    rebuilt_doc = doc
    if source_path.exists():
        rebuilt_doc = processor.parse_file(source_path, original_name=doc.file_name)
        rebuilt_doc.document_id = doc.document_id
    rebuilt_doc.metadata["index_status"] = "indexing"
    split_started = datetime.utcnow()
    chunks = processor.split(rebuilt_doc)
    split_ended = datetime.utcnow()
    retriever.delete_document(doc.document_id)
    index_started = datetime.utcnow()
    retriever.add_document(rebuilt_doc, chunks)
    index_ended = datetime.utcnow()
    rebuilt_doc.metadata["index_status"] = "indexed"
    rebuilt_doc.metadata["lifecycle"] = [
        lifecycle_event("chunk", "success", split_started, split_ended),
        lifecycle_event("index", "success", index_started, index_ended),
    ]
    rebuilt_doc.metadata["quality"] = assess_document_quality(rebuilt_doc, chunks)
    rebuilt_doc.metadata["summary"] = summarize_document(rebuilt_doc, chunks)
    registry.save_document(rebuilt_doc)
    return rebuilt_doc, chunks


@router.post("/documents/{document_id}/rebuild")
def rebuild_document(document_id: str):
    doc = registry.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        registry.update_document_status(document_id, "indexing")
        rebuilt_doc, chunks = _rebuild(doc)
        registry.log_operation(
            "document_rebuilt",
            f"重建索引：{rebuilt_doc.file_name}",
            {"document_id": document_id, "filename": rebuilt_doc.file_name, "chunk_count": len(chunks), "quality_score": rebuilt_doc.metadata["quality"]["score"]},
        )
        return {"rebuilt": True, "document_id": document_id, "chunk_count": len(chunks), "metadata": rebuilt_doc.metadata}
    except Exception as exc:
        message = friendly_index_error(exc)
        registry.update_document_status(document_id, "failed", message)
        registry.log_operation("document_rebuild_failed", f"重建索引失败：{doc.file_name}", {"document_id": document_id, "filename": doc.file_name, "error": message}, level="error")
        raise HTTPException(status_code=500, detail=f"Failed to rebuild document: {message}") from exc


@router.post("/documents/rebuild-all")
def rebuild_all_documents():
    results = []
    for doc in registry.load_documents():
        try:
            registry.update_document_status(doc.document_id, "indexing")
            _, chunks = _rebuild(doc)
            results.append({"document_id": doc.document_id, "filename": doc.file_name, "status": "indexed", "chunk_count": len(chunks)})
        except Exception as exc:
            message = friendly_index_error(exc)
            registry.update_document_status(doc.document_id, "failed", message)
            results.append({"document_id": doc.document_id, "filename": doc.file_name, "status": "failed", "error": message})
    return {"rebuilt": True, "results": results}
