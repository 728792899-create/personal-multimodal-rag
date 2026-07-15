from __future__ import annotations

import mimetypes
from pathlib import Path

import fitz

from app.models.domain import Document


def materialize_document_assets(document: Document, registry, object_store) -> list[dict]:
    """Persist embedded PDF/DOCX media and bind it to typed elements."""

    source = Path(document.file_path)
    if not source.is_file():
        return []
    assets: list[dict] = []
    if document.file_type == "pdf":
        pdf = fitz.open(str(source))
        try:
            for element in document.elements:
                xref = element.metadata.get("xref") if element.type == "image" else None
                if not isinstance(xref, int) or element.asset_id:
                    continue
                extracted = pdf.extract_image(xref)
                payload = extracted.get("image")
                if not isinstance(payload, bytes):
                    continue
                extension = str(extracted.get("ext") or "bin").lower()
                asset = _store(
                    document,
                    registry,
                    object_store,
                    payload,
                    f"{Path(document.file_name).stem}-page-{element.page_number or 1}-image-{element.order}.{extension}",
                    mimetypes.guess_type(f"asset.{extension}")[0] or "application/octet-stream",
                    {"source": "pdf-embedded", "page_number": element.page_number, "xref": xref},
                )
                element.asset_id = asset["id"]
                element.metadata["asset_status"] = "materialized"
                assets.append(asset)
        finally:
            pdf.close()
    elif document.file_type == "docx":
        from docx import Document as WordDocument

        word = WordDocument(str(source))
        for element in document.elements:
            relationship_id = element.metadata.get("relationship_id") if element.type == "image" else None
            if not relationship_id or element.asset_id:
                continue
            relationship = word.part.rels.get(relationship_id)
            target = getattr(relationship, "target_part", None)
            payload = getattr(target, "blob", None)
            if not isinstance(payload, bytes):
                continue
            content_type = str(getattr(target, "content_type", "") or "application/octet-stream")
            extension = mimetypes.guess_extension(content_type) or ".bin"
            asset = _store(
                document,
                registry,
                object_store,
                payload,
                f"{Path(document.file_name).stem}-image-{element.order}{extension}",
                content_type,
                {"source": "docx-embedded", "relationship_id": relationship_id},
            )
            element.asset_id = asset["id"]
            element.metadata["asset_status"] = "materialized"
            assets.append(asset)
    if assets:
        registry.save_document(document)
    return assets


def delete_document_assets(document_id: str, registry, object_store, *, kind: str | None = None) -> int:
    assets = registry.list_assets(document_id=document_id, kind=kind, include_private=True)
    for asset in assets:
        removed = registry.delete_asset(asset["id"])
        if removed and registry.asset_reference_count(asset["object_key"]) == 0:
            object_store.delete(asset["object_key"])
    return len(assets)


def _store(document, registry, object_store, payload, original_name, media_type, metadata):
    stored = object_store.put_bytes(payload)
    try:
        return registry.create_asset(
            document_id=document.document_id,
            knowledge_base_id=str(document.metadata.get("knowledge_base_id") or "default"),
            kind="derived",
            object_key=stored.object_key,
            original_name=original_name,
            media_type=media_type,
            sha256=stored.sha256,
            size_bytes=stored.size_bytes,
            metadata=metadata,
        )
    except Exception:
        if registry.asset_reference_count(stored.object_key) == 0:
            object_store.delete(stored.object_key)
        raise
