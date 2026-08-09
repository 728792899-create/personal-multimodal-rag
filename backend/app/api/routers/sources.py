from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.store import (
    connector_registry,
    registry,
    source_root_resolver,
    source_sync_service,
)
from app.services.url_importer import _validate_public_url


router = APIRouter(tags=["sources"])


class SourceCreate(BaseModel):
    type: Literal["local_directory", "url_list", "rss_atom"]
    name: str = Field(min_length=1, max_length=160)
    knowledge_base_id: str = Field("default", min_length=1, max_length=80)
    config: dict = Field(default_factory=dict)
    enabled: bool = True


class SourceUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=160)
    config: dict | None = None
    enabled: bool | None = None


class ConfirmDeletionRequest(BaseModel):
    item_ids: list[str] = Field(default_factory=list, max_length=200)


def _validated_config(source_type: str, config: dict) -> dict:
    if source_type == "local_directory":
        root_id = str(config.get("root_id") or "")
        relative_path = str(config.get("relative_path") or "").strip()
        source_root_resolver.resolve(root_id, relative_path)
        return {
            "root_id": root_id,
            "relative_path": relative_path,
            "recursive": bool(config.get("recursive", True)),
        }
    if source_type == "url_list":
        values = list(
            dict.fromkeys(
                str(item).strip()
                for item in config.get("urls", [])
                if str(item).strip()
            )
        )
        if not values:
            raise ValueError("请至少填写一个 URL。")
        if len(values) > 200:
            raise ValueError("一个 URL 列表最多包含 200 项。")
        for value in values:
            _validate_public_url(value)
        return {"urls": values}
    if source_type == "rss_atom":
        feed_url = str(config.get("feed_url") or "").strip()
        _validate_public_url(feed_url)
        return {
            "feed_url": feed_url,
            "etag": str(config.get("etag") or ""),
            "last_modified": str(config.get("last_modified") or ""),
        }
    raise ValueError("不支持该数据源类型。")


@router.get("/sources")
def list_sources(knowledge_base_id: str = ""):
    return {
        "sources": registry.list_sources(knowledge_base_id),
        "capabilities": {
            "types": connector_registry.capabilities(),
            "directory_roots": source_root_resolver.public_roots(),
        },
    }


@router.post("/sources", status_code=201)
def create_source(payload: SourceCreate):
    if not registry.get_knowledge_base(payload.knowledge_base_id):
        raise HTTPException(status_code=404, detail="知识库不存在或已被删除。")
    try:
        if not payload.name.strip():
            raise ValueError("请填写数据源名称。")
        config = _validated_config(payload.type, payload.config)
        source = registry.create_source(
            source_type=payload.type,
            name=payload.name,
            config=config,
            knowledge_base_id=payload.knowledge_base_id,
            enabled=payload.enabled,
        )
        return {"source": source}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sources/{source_id}")
def get_source(source_id: str):
    source = registry.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="数据源不存在或已被删除。")
    return {"source": source, "items": registry.list_source_items(source_id)}


@router.patch("/sources/{source_id}")
def update_source(source_id: str, payload: SourceUpdate):
    current = registry.get_source(source_id)
    if not current:
        raise HTTPException(status_code=404, detail="数据源不存在或已被删除。")
    try:
        config = (
            _validated_config(current["type"], payload.config)
            if payload.config is not None
            else None
        )
        return {
            "source": registry.update_source(
                source_id,
                name=payload.name,
                config=config,
                enabled=payload.enabled,
            )
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/sources/{source_id}")
def delete_source(source_id: str):
    if not registry.delete_source(source_id):
        raise HTTPException(status_code=404, detail="数据源不存在或已被删除。")
    return {"deleted": True, "source_id": source_id}


@router.post("/sources/{source_id}/sync", status_code=202)
def sync_source(source_id: str):
    try:
        run = source_sync_service.sync(source_id)
    except ValueError as exc:
        status = 404 if str(exc) == "数据源不存在或已被删除。" else 409
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    if run["status"] == "failed":
        return {"sync_run": run, "accepted": False}
    return {"sync_run": run, "accepted": True}


@router.post("/sources/{source_id}/deletions:confirm")
def confirm_source_deletions(source_id: str, payload: ConfirmDeletionRequest):
    try:
        return source_sync_service.confirm_deletions(source_id, payload.item_ids)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/sync-runs")
def list_sync_runs(
    limit: int = Query(50, ge=1, le=200),
    source_id: str = "",
):
    return {"sync_runs": registry.list_sync_runs(limit, source_id)}


@router.get("/sync-runs/{run_id}")
def get_sync_run(run_id: str):
    run = registry.get_sync_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="同步记录不存在或已被删除。")
    return {"sync_run": run}


@router.post("/sync-runs/{run_id}/retry", status_code=202)
def retry_sync_run(run_id: str):
    try:
        return {"sync_run": source_sync_service.retry(run_id)}
    except ValueError as exc:
        status = 404 if str(exc) == "同步记录不存在或已被删除。" else 409
        raise HTTPException(status_code=status, detail=str(exc)) from exc
