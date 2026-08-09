from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.core.store import query_asset_service
from app.services.query_assets import QueryAssetError


router = APIRouter(prefix="/query-assets", tags=["query-assets"])


def _owner(request: Request) -> tuple[str, str]:
    identity = request.scope.get("state", {}).get("identity")
    return (
        (identity.user_id, identity.workspace_id)
        if identity is not None
        else ("owner", "default")
    )


@router.post("", status_code=201)
async def create_query_assets(
    request: Request,
    files: list[UploadFile] = File(...),
    knowledge_base_id: str = Form("default"),
):
    user_id, workspace_id = _owner(request)
    if not files or len(files) > query_asset_service.max_count:
        raise HTTPException(
            status_code=400,
            detail=f"请上传 1 至 {query_asset_service.max_count} 张查询图片。",
        )
    assets = []
    try:
        for file in files:
            payload = await file.read(query_asset_service.max_bytes + 1)
            assets.append(
                query_asset_service.create(
                    payload,
                    file.filename or "query-image",
                    knowledge_base_id,
                    user_id=user_id,
                    workspace_id=workspace_id,
                )
            )
    except QueryAssetError as exc:
        for asset in assets:
            query_asset_service.delete(
                asset["id"], user_id=user_id, workspace_id=workspace_id
            )
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    finally:
        for file in files:
            await file.close()
    return {"assets": assets}


@router.delete("/{asset_id}")
def delete_query_asset(asset_id: str, request: Request):
    user_id, workspace_id = _owner(request)
    if not query_asset_service.delete(
        asset_id, user_id=user_id, workspace_id=workspace_id
    ):
        raise HTTPException(status_code=404, detail="查询图片不存在或已被删除。")
    return {"deleted": True, "id": asset_id}
