from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.services.index_versions import IndexVersionRegistry


class CandidateIndexRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index_id: str = Field(min_length=1, max_length=80)
    table_name: str = ""
    parser_version: str = Field(min_length=1, max_length=120)
    chunker_version: str = "structure-v2"
    source_index_id: str = ""
    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-large"
    embedding_dimension: int = 1536


class IndexValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checklist: dict[str, bool]
    metrics: dict[str, Any] = Field(default_factory=dict)


class ShadowRebuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    benchmark_samples: int = Field(default=100, ge=10, le=500)


def build_durable_shadow_rebuild_enqueuer(document_registry):
    """Use the existing durable index job + outbox lifecycle for rebuilds."""

    def enqueue(index_id: str, benchmark_samples: int) -> dict:
        idempotency_key = hashlib.sha256(
            f"shadow-index:{index_id}:{benchmark_samples}".encode("utf-8")
        ).hexdigest()
        return document_registry.create_index_job(
            source_type="shadow_index",
            source_name=f"shadow-index:{index_id}",
            payload={
                "index_id": index_id,
                "benchmark_samples": benchmark_samples,
            },
            knowledge_base_id="default",
            idempotency_key=idempotency_key,
            max_attempts=3,
        )

    return enqueue


def build_indexes_router(
    registry: IndexVersionRegistry,
    *,
    require_admin: Callable,
    store_factory: Callable | None = None,
    enqueue_rebuild: Callable[[str, int], dict] | None = None,
) -> APIRouter:
    """Build admin-only index control-plane routes.

    ``require_admin`` is mandatory by design; the router cannot accidentally be
    mounted without the application's RBAC dependency.
    """

    if not callable(require_admin):
        raise ValueError("An admin authorization dependency is required")
    router = APIRouter(
        prefix="/indexes",
        tags=["indexes"],
        dependencies=[Depends(require_admin)],
    )

    @router.get("")
    def list_indexes(limit: int = 100):
        return {
            "indexes": [item.model_dump() for item in registry.list(limit=limit)],
            "state": registry.state(),
        }

    @router.get("/active")
    def active_index():
        active = registry.active()
        return {
            "index": active.model_dump() if active else None,
            "state": registry.state(),
        }

    @router.post("/candidates", status_code=201)
    def create_candidate(payload: CandidateIndexRequest):
        try:
            record = registry.register_candidate(**payload.model_dump())
            if store_factory is not None:
                store_factory(record, create_hnsw=False)
            return {"index": record.model_dump()}
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.put("/{index_id}/validation")
    def record_validation(index_id: str, payload: IndexValidationRequest):
        try:
            record = registry.record_validation(
                index_id,
                payload.checklist,
                metrics=payload.metrics,
            )
            return {
                "index": record.model_dump(),
                "validation_errors": registry.validation_errors(index_id),
            }
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/{index_id}/rebuild", status_code=202)
    def rebuild_shadow_index(index_id: str, payload: ShadowRebuildRequest):
        record = registry.get(index_id)
        if record is None:
            raise HTTPException(status_code=404, detail="索引候选版本不存在。")
        if record.status not in {"candidate", "stable"}:
            raise HTTPException(status_code=409, detail="当前索引状态不允许重建。")
        if enqueue_rebuild is None:
            raise HTTPException(status_code=503, detail="影子索引任务队列未配置。")
        job = enqueue_rebuild(index_id, payload.benchmark_samples)
        return {
            "job": {key: value for key, value in job.items() if key != "payload"},
            "index": record.model_dump(),
        }

    @router.post("/{index_id}/promote")
    def promote_index(index_id: str):
        try:
            return {"index": registry.promote(index_id).model_dump()}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/{index_id}/activate")
    def activate_index(index_id: str):
        try:
            return {
                "index": registry.activate(index_id).model_dump(),
                "state": registry.state(),
            }
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/rollback")
    def rollback_index():
        try:
            return {
                "index": registry.rollback().model_dump(),
                "state": registry.state(),
            }
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return router
