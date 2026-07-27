from __future__ import annotations

import hashlib
import mimetypes
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.api.routers.documents import safe_upload_name, validate_file_signature
from app.config import settings
from app.core.store import object_store, registry
from app.models.schemas import IngestionUrlRequest
from app.services.safe_logging import sanitize_url_for_log


router = APIRouter(tags=["ingestion"])
INGESTION_DIR = Path(settings.staging_path).expanduser() / "ingestions"


def _public_job(job: dict) -> dict:
    return {key: value for key, value in job.items() if key != "payload"}


@router.post("/ingestions/file", status_code=202)
async def enqueue_file(
    file: UploadFile = File(...),
    knowledge_base_id: str = Form("default"),
    parser_profile: str = Form("builtin"),
    enrich_modalities: bool = Form(True),
    build_graph: bool = Form(True),
):
    if not registry.get_knowledge_base(knowledge_base_id):
        raise HTTPException(status_code=404, detail="知识库不存在或已被删除。")
    safe_name = safe_upload_name(file.filename)
    INGESTION_DIR.mkdir(parents=True, exist_ok=True)
    target = INGESTION_DIR / f"{uuid.uuid4().hex}-{safe_name}"
    digest = hashlib.sha256()
    written = 0
    created_asset_id = ""
    stored_object_key = ""
    try:
        with target.open("wb") as handle:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件过大，最大允许 {settings.max_upload_bytes} bytes。",
                    )
                digest.update(chunk)
                handle.write(chunk)
        if not written:
            raise HTTPException(status_code=400, detail="上传的文件为空。")
        validate_file_signature(target, safe_name)
        profile = parser_profile.strip().lower() or "builtin"
        if profile not in {"builtin", "mineru", "docling", "paddleocr", "auto"}:
            raise HTTPException(status_code=400, detail="不支持该解析 profile。")
        stored = object_store.put_file(target)
        stored_object_key = stored.object_key
        asset = registry.create_asset(
            knowledge_base_id=knowledge_base_id,
            kind="source",
            object_key=stored.object_key,
            original_name=safe_name,
            media_type=file.content_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream",
            sha256=stored.sha256,
            size_bytes=stored.size_bytes,
            metadata={"role": "original", "pending_ingestion": True},
        )
        created_asset_id = asset["id"]
        key = hashlib.sha256(
            f"{knowledge_base_id}:{digest.hexdigest()}:{profile}:{enrich_modalities}:{build_graph}:{settings.enrichment_provider}:{settings.enrichment_prompt_version}:{settings.chunker_version}:{settings.embedding_provider}:{settings.embedding_model}:{settings.resolved_embedding_dimension()}:{settings.index_version}".encode()
        ).hexdigest()
        job = registry.create_index_job(
            source_type="file",
            source_name=safe_name,
            payload={
                "asset_id": asset["id"],
                "content_hash": digest.hexdigest(),
                "parser_profile": profile,
                "enrich_modalities": enrich_modalities,
                "build_graph": build_graph,
            },
            knowledge_base_id=knowledge_base_id,
            idempotency_key=key,
        )
        if job["payload"].get("asset_id") != asset["id"]:
            removed = registry.delete_asset(asset["id"])
            created_asset_id = ""
            if removed and registry.asset_reference_count(stored.object_key) == 0:
                object_store.delete(stored.object_key)
        return {"job": _public_job(job)}
    except Exception:
        if created_asset_id:
            registry.delete_asset(created_asset_id)
        if stored_object_key and registry.asset_reference_count(stored_object_key) == 0:
            object_store.delete(stored_object_key)
        raise
    finally:
        target.unlink(missing_ok=True)
        await file.close()


@router.post("/ingestions/url", status_code=202)
def enqueue_url(payload: IngestionUrlRequest):
    if not registry.get_knowledge_base(payload.knowledge_base_id):
        raise HTTPException(status_code=404, detail="知识库不存在或已被删除。")
    key = hashlib.sha256(
        f"{payload.knowledge_base_id}:{payload.url.strip()}:{payload.parser_profile}:{payload.enrich_modalities}:{payload.build_graph}:{settings.enrichment_provider}:{settings.enrichment_prompt_version}:{settings.chunker_version}:{settings.embedding_provider}:{settings.embedding_model}:{settings.index_version}".encode()
    ).hexdigest()
    job = registry.create_index_job(
        source_type="url",
        source_name=sanitize_url_for_log(payload.url),
        payload={
            "url": payload.url,
            "title": payload.title,
            "parser_profile": payload.parser_profile,
            "enrich_modalities": payload.enrich_modalities,
            "build_graph": payload.build_graph,
        },
        knowledge_base_id=payload.knowledge_base_id,
        idempotency_key=key,
    )
    return {"job": _public_job(job)}


@router.get("/index-jobs")
def list_index_jobs(limit: int = 50):
    return {"jobs": registry.list_index_jobs(limit)}


@router.get("/index-jobs/dead-letters")
def list_dead_letter_jobs(limit: int = 50):
    return {"dead_letters": registry.list_dead_letter_jobs(limit)}


@router.get("/index-jobs/{job_id}")
def get_index_job(job_id: str):
    job = registry.get_index_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="索引任务不存在或已被删除。")
    return {"job": job}


@router.post("/index-jobs/{job_id}/retry")
def retry_index_job(job_id: str):
    job = registry.retry_index_job(job_id)
    if not job:
        raise HTTPException(status_code=409, detail="只有失败或已取消的索引任务可以重试。")
    return {"job": job}


@router.delete("/index-jobs/{job_id}")
def cancel_index_job(job_id: str):
    job = registry.request_index_job_cancel(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="索引任务不存在或已被删除。")
    return {"job": job}
