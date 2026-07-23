from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.core.store import graph_store, object_store, registry, retriever
from app.models.schemas import KnowledgeBaseCreate, KnowledgeBaseUpdate


router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


@router.get("")
def list_knowledge_bases():
    return {"knowledge_bases": registry.list_knowledge_bases()}


@router.post("", status_code=201)
def create_knowledge_base(payload: KnowledgeBaseCreate):
    return {"knowledge_base": registry.create_knowledge_base(payload.name, payload.description)}


@router.patch("/{knowledge_base_id}")
def update_knowledge_base(knowledge_base_id: str, payload: KnowledgeBaseUpdate):
    updated = registry.update_knowledge_base(knowledge_base_id, payload.name, payload.description)
    if not updated:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return {"knowledge_base": updated}


@router.get("/{knowledge_base_id}/graph")
def get_knowledge_base_graph(knowledge_base_id: str, limit: int = Query(500, ge=1, le=2000)):
    if not registry.get_knowledge_base(knowledge_base_id):
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return graph_store.snapshot(knowledge_base_id, limit=limit)


@router.delete("/{knowledge_base_id}")
def delete_knowledge_base(knowledge_base_id: str, force: bool = Query(False)):
    documents = registry.load_documents([knowledge_base_id])
    assets = [
        asset
        for document in documents
        for asset in registry.list_assets(document_id=document.document_id, include_private=True)
    ]
    try:
        deleted = registry.delete_knowledge_base(knowledge_base_id, force=force)
    except ValueError as exc:
        status = 409 if "contains documents" in str(exc) or "index jobs" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    for document in documents:
        retriever.delete_document(document.document_id)
    for asset in assets:
        if registry.asset_reference_count(asset["object_key"]) == 0:
            object_store.delete(asset["object_key"])
    return {"deleted": True}
