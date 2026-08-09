from __future__ import annotations

import mimetypes
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app.api.common import (
    chunk_payload,
    chunks_for_document,
    document_summary,
    friendly_index_error,
    index_document,
)
from app.config import settings
from app.core.store import (
    enrichment_service,
    fetch_worker_client,
    graph_store,
    object_store,
    processor,
    query_asset_service,
    registry,
    retriever,
)
from app.models.domain import Document
from app.models.schemas import UrlImportRequest
from app.services.document_quality import assess_document_quality, lifecycle_event, summarize_document
from app.services.document_processor import SUPPORTED_EXTENSIONS
from app.services.safe_logging import (
    public_error_message,
    redact_private_metadata,
    redact_sensitive_text,
    sanitize_url_for_log,
)
from app.services.multimodal_assets import delete_document_assets, materialize_document_assets
from app.services.multimodal_enrichment import ProviderUnavailableError
from app.services.url_importer import fetch_url


router = APIRouter(tags=["documents"])
DATA_DIR = Path(settings.staging_path).expanduser() / "uploads"


@router.get("/documents")
def list_documents(knowledge_base_id: str = ""):
    return {
        "documents": [
            document_summary(doc, chunks_for_document(doc.document_id))
            for doc in registry.load_documents([knowledge_base_id] if knowledge_base_id else None)
        ]
    }


@router.get("/documents/{document_id}")
def get_document(document_id: str):
    doc = registry.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在或已被删除。")
    chunks = sorted(chunks_for_document(document_id), key=lambda item: item.chunk_index)
    return {
        "document": {
            **document_summary(doc, chunks),
            "title": doc.title,
            "created_at": doc.created_at.isoformat(),
            "page_count": len(doc.pages),
            "pages": [
                {"page_number": page.page_number, "text": page.text, "metadata": redact_private_metadata(page.metadata)}
                for page in doc.pages
            ],
        },
        "chunks": [chunk_payload(chunk) for chunk in chunks],
    }


@router.get("/documents/{document_id}/elements")
def get_document_elements(document_id: str):
    if not registry.get_document(document_id):
        raise HTTPException(status_code=404, detail="文档不存在或已被删除。")
    return {"elements": registry.list_document_elements(document_id)}


@router.get("/documents/{document_id}/source")
def get_document_source(document_id: str):
    doc = registry.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在或已被删除。")
    assets = registry.list_assets(document_id=document_id, kind="source", include_private=True)
    if not assets:
        raise HTTPException(
            status_code=404,
            detail="原始文件不可用；请重新上传后再执行解析。",
        )
    return _asset_file_response(assets[0], attachment=True)


@router.get("/assets/{asset_id}")
def get_asset(asset_id: str, request: Request):
    asset = registry.get_asset(asset_id, include_private=True)
    if not asset:
        raise HTTPException(status_code=404, detail="资源不存在或已被删除。")
    if asset["kind"] == "query":
        identity = request.scope.get("state", {}).get("identity")
        user_id = identity.user_id if identity is not None else "owner"
        workspace_id = identity.workspace_id if identity is not None else "default"
        asset = query_asset_service.get_for_owner(
            asset_id, user_id=user_id, workspace_id=workspace_id
        )
        if asset is None:
            raise HTTPException(status_code=404, detail="资源不存在或已被删除。")
        try:
            expired = datetime.fromisoformat(asset["expires_at"]) <= datetime.utcnow()
        except ValueError:
            expired = True
        if expired:
            query_asset_service.delete(
                asset_id, user_id=user_id, workspace_id=workspace_id
            )
            raise HTTPException(status_code=410, detail="查询图片已过期，请重新上传。")
    return _asset_file_response(asset, attachment=asset["kind"] == "source")


@router.post("/documents")
async def upload_document(file: UploadFile = File(...), knowledge_base_id: str = Form("default")):
    target: Path | None = None
    stored_object_key = ""
    indexed_document_id = ""
    upload_completed = False
    safe_name = ""
    try:
        if not registry.get_knowledge_base(knowledge_base_id):
            raise HTTPException(status_code=404, detail="知识库不存在或已被删除。")
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
                        detail=f"文件过大，最大允许 {settings.max_upload_bytes} bytes。",
                    )
                handle.write(chunk)
        if written == 0:
            raise HTTPException(status_code=400, detail="上传的文件为空。")
        validate_file_signature(target, safe_name)
        upload_ended = datetime.utcnow()
        parse_started = datetime.utcnow()
        doc = processor.parse_file(target, original_name=safe_name)
        doc.metadata["knowledge_base_id"] = knowledge_base_id
        parse_ended = datetime.utcnow()
        existing = registry.find_by_content_hash(doc.metadata.get("content_hash", ""), knowledge_base_id)
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
        stored = object_store.put_file(target)
        stored_object_key = stored.object_key
        doc.file_path = str(stored.path)
        doc.metadata.update({"source_available": True, "source_sha256": stored.sha256})
        indexed_document_id = doc.document_id
        doc, chunks = index_document(
            doc,
            [
                lifecycle_event("upload", "success", upload_started, upload_ended),
                lifecycle_event("parse", "success", parse_started, parse_ended),
            ],
        )
        asset = registry.create_asset(
            knowledge_base_id=knowledge_base_id,
            kind="source",
            object_key=stored.object_key,
            original_name=safe_name,
            media_type=file.content_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream",
            sha256=stored.sha256,
            size_bytes=stored.size_bytes,
            document_id=doc.document_id,
            metadata={"role": "original"},
        )
        doc.metadata["source_asset_id"] = asset["id"]
        if doc.file_type == "image":
            for element in doc.elements:
                if element.type == "image" and element.metadata.get("source_asset_role"):
                    element.asset_id = asset["id"]
        registry.save_document(doc)
        materialize_document_assets(doc, registry, object_store)
        registry.create_parser_run(
            document_id=doc.document_id,
            provider="builtin",
            parser=str(doc.metadata.get("parser") or "builtin"),
            status="succeeded",
            payload={"element_count": len(doc.elements), "modality_counts": document_summary(doc, chunks)["modality_counts"]},
        )
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
        upload_completed = True
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
    except ProviderUnavailableError as exc:
        registry.log_operation(
            "document_upload_failed",
            f"文档 enrichment provider 不可用：{safe_name or '未命名文件'}",
            {
                "filename": safe_name,
                "error": public_error_message(
                    exc,
                    "多模态 enrichment Provider 暂时不可用。",
                ),
            },
            level="error",
        )
        raise HTTPException(
            status_code=503,
            detail="当前配置的多模态 enrichment Provider 暂时不可用，请检查 Provider 状态后重试。",
        ) from exc
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
        if target is not None:
            target.unlink(missing_ok=True)
        if indexed_document_id and not upload_completed:
            _rollback_document(indexed_document_id)
        if stored_object_key and registry.asset_reference_count(stored_object_key) == 0:
            object_store.delete(stored_object_key)
        await file.close()


def safe_upload_name(filename: str | None) -> str:
    normalized = (filename or "").strip().replace("\\", "/")
    safe_name = Path(normalized).name
    if not safe_name or safe_name in {".", ".."} or "\x00" in safe_name:
        raise HTTPException(status_code=400, detail="请提供有效的文件名。")
    if len(safe_name.encode("utf-8")) > 240:
        raise HTTPException(status_code=400, detail="文件名过长。")
    suffix = Path(safe_name).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型：{suffix or '无扩展名'}；允许类型：{supported}",
        )
    return safe_name


def validate_file_signature(path: Path, filename: str) -> None:
    signatures = {
        ".pdf": (b"%PDF-",),
        ".docx": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
        ".png": (b"\x89PNG\r\n\x1a\n",),
        ".jpg": (b"\xff\xd8\xff",),
        ".jpeg": (b"\xff\xd8\xff",),
    }
    expected = signatures.get(Path(filename).suffix.lower())
    if expected and not any(path.read_bytes()[:16].startswith(signature) for signature in expected):
        raise HTTPException(status_code=400, detail="文件内容签名与扩展名不匹配。")


@router.post("/imports/url")
def import_url(payload: UrlImportRequest):
    safe_url = sanitize_url_for_log(payload.url)
    try:
        if not registry.get_knowledge_base(payload.knowledge_base_id):
            raise HTTPException(status_code=404, detail="知识库不存在或已被删除。")
        fetch_started = datetime.utcnow()
        active_fetcher = fetch_worker_client.fetch_url if fetch_worker_client else fetch_url
        imported = active_fetcher(
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
        doc.metadata["knowledge_base_id"] = payload.knowledge_base_id
        parse_ended = datetime.utcnow()
        existing = registry.find_by_content_hash(doc.metadata.get("content_hash", ""), payload.knowledge_base_id)
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
    except HTTPException:
        raise
    except Exception as exc:
        message = public_error_message(
            exc,
            "URL 导入失败，请检查地址、内容类型或网络状态后重试。",
        )
        registry.log_operation("url_import_failed", f"URL 导入失败：{safe_url}", {"url": safe_url, "error": message}, level="error")
        raise HTTPException(status_code=400, detail=message) from exc


@router.delete("/documents/{document_id}")
def delete_document(document_id: str):
    doc = registry.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在或已被删除。")
    assets = registry.list_assets(document_id=document_id, include_private=True)
    retriever.delete_document(document_id)
    registry.delete_document(document_id)
    source_deleted = delete_uploaded_source(doc)
    for asset in assets:
        if registry.asset_reference_count(asset["object_key"]) == 0:
            source_deleted = object_store.delete(asset["object_key"]) or source_deleted
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
        rebuilt_doc.file_path = doc.file_path
        rebuilt_doc.metadata = {**doc.metadata, **rebuilt_doc.metadata}
        for index, element in enumerate(rebuilt_doc.elements):
            element.document_id = doc.document_id
            element.element_id = f"{doc.document_id}:element:{index}"
            if element.type == "image" and element.metadata.get("source_asset_role"):
                element.asset_id = str(doc.metadata.get("source_asset_id") or "") or None
    rebuilt_doc.metadata["index_status"] = "indexing"
    enrichment_service.enrich_document(rebuilt_doc)
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
    rebuilt_doc.metadata["graph"] = graph_store.build_document(rebuilt_doc)
    rebuilt_doc.metadata["quality"] = assess_document_quality(rebuilt_doc, chunks)
    registry.save_document(rebuilt_doc)
    return rebuilt_doc, chunks


def _rollback_document(document_id: str) -> None:
    """Remove every partially-created index and durable object for a failed upload."""

    assets = registry.list_assets(document_id=document_id, include_private=True)
    retriever.delete_document(document_id)
    registry.delete_document(document_id)
    for asset in assets:
        if registry.asset_reference_count(asset["object_key"]) == 0:
            object_store.delete(asset["object_key"])


@router.post("/documents/{document_id}/rebuild")
def rebuild_document(document_id: str):
    doc = registry.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在或已被删除。")
    try:
        registry.update_document_status(document_id, "indexing")
        rebuilt_doc, chunks = _rebuild(doc)
        delete_document_assets(document_id, registry, object_store, kind="derived")
        materialize_document_assets(rebuilt_doc, registry, object_store)
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
        raise HTTPException(status_code=500, detail=f"文档索引重建失败：{message}") from exc


@router.post("/documents/{document_id}/reindex")
def reindex_document(document_id: str):
    """0.3 alias with the same compatibility-preserving behavior as rebuild."""
    return rebuild_document(document_id)


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


def _asset_file_response(asset: dict, *, attachment: bool) -> FileResponse:
    try:
        path = object_store.path_for(asset["object_key"])
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="资源当前不可用。") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="资源当前不可用。")
    safe_name = Path(str(asset.get("original_name") or "asset")).name
    disposition = "attachment" if attachment else "inline"
    return FileResponse(
        path,
        media_type=asset.get("media_type") or "application/octet-stream",
        filename=safe_name,
        content_disposition_type=disposition,
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=60"},
    )
