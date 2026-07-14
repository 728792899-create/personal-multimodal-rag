from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.api.routers.documents import safe_upload_name, validate_file_signature
from app.config import settings
from app.core.store import registry
from app.models.schemas import IngestionUrlRequest
from app.services.safe_logging import sanitize_url_for_log


router = APIRouter(tags=["ingestion"])
INGESTION_DIR = Path(__file__).resolve().parents[4] / "data" / "ingestions"


def _public_job(job: dict) -> dict:
    return {key: value for key, value in job.items() if key != "payload"}


@router.post("/ingestions/file", status_code=202)
async def enqueue_file(
    file: UploadFile = File(...),
    knowledge_base_id: str = Form("default"),
):
    if not registry.get_knowledge_base(knowledge_base_id):
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    safe_name = safe_upload_name(file.filename)
    INGESTION_DIR.mkdir(parents=True, exist_ok=True)
    target = INGESTION_DIR / f"{uuid.uuid4().hex}-{safe_name}"
    digest = hashlib.sha256()
    written = 0
    try:
        with target.open("wb") as handle:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > settings.max_upload_bytes:
                    raise HTTPException(status_code=413, detail=f"File is too large; max {settings.max_upload_bytes} bytes")
                digest.update(chunk)
                handle.write(chunk)
        if not written:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
        validate_file_signature(target, safe_name)
        key = hashlib.sha256(
            f"{knowledge_base_id}:{digest.hexdigest()}:{settings.chunker_version}:{settings.embedding_provider}:{settings.embedding_model}:{settings.resolved_embedding_dimension()}:{settings.index_version}".encode()
        ).hexdigest()
        job = registry.create_index_job(
            source_type="file",
            source_name=safe_name,
            payload={"staged_path": str(target), "content_hash": digest.hexdigest()},
            knowledge_base_id=knowledge_base_id,
            idempotency_key=key,
        )
        if job["payload"].get("staged_path") != str(target):
            target.unlink(missing_ok=True)
        return {"job": _public_job(job)}
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@router.post("/ingestions/url", status_code=202)
def enqueue_url(payload: IngestionUrlRequest):
    if not registry.get_knowledge_base(payload.knowledge_base_id):
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    key = hashlib.sha256(
        f"{payload.knowledge_base_id}:{payload.url.strip()}:{settings.chunker_version}:{settings.embedding_provider}:{settings.embedding_model}:{settings.index_version}".encode()
    ).hexdigest()
    job = registry.create_index_job(
        source_type="url",
        source_name=sanitize_url_for_log(payload.url),
        payload={"url": payload.url, "title": payload.title},
        knowledge_base_id=payload.knowledge_base_id,
        idempotency_key=key,
    )
    return {"job": _public_job(job)}


@router.get("/index-jobs")
def list_index_jobs(limit: int = 50):
    return {"jobs": registry.list_index_jobs(limit)}


@router.get("/index-jobs/{job_id}")
def get_index_job(job_id: str):
    job = registry.get_index_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Index job not found")
    return {"job": job}


@router.post("/index-jobs/{job_id}/retry")
def retry_index_job(job_id: str):
    job = registry.retry_index_job(job_id)
    if not job:
        raise HTTPException(status_code=409, detail="Only failed or cancelled jobs can be retried")
    return {"job": job}


@router.delete("/index-jobs/{job_id}")
def cancel_index_job(job_id: str):
    job = registry.request_index_job_cancel(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Index job not found")
    return {"job": job}
