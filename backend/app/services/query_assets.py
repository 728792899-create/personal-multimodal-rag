from __future__ import annotations

import base64
import io
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from app.models.domain import DocumentElement
from app.services.ocr import ImageOCRAdapter
from app.services.safe_logging import redact_sensitive_text


ALLOWED_IMAGE_FORMATS = {
    "PNG": ("image/png", ".png"),
    "JPEG": ("image/jpeg", ".jpg"),
    "WEBP": ("image/webp", ".webp"),
    "GIF": ("image/gif", ".gif"),
}


class QueryAssetError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class QueryAssetService:
    """Short-lived query images stored by content hash, never by user path."""

    def __init__(
        self,
        registry,
        object_store,
        enricher,
        *,
        max_bytes: int = 10 * 1024 * 1024,
        max_count: int = 4,
        ttl_hours: int = 24,
        max_pixels: int = 40_000_000,
        ocr_adapter: ImageOCRAdapter | None = None,
    ):
        self.registry = registry
        self.object_store = object_store
        self.enricher = enricher
        self.max_bytes = max(1, max_bytes)
        self.max_count = max(1, min(max_count, 4))
        self.ttl_hours = max(1, min(ttl_hours, 24))
        self.max_pixels = max(1, max_pixels)
        self.ocr_adapter = ocr_adapter or ImageOCRAdapter()

    def create(self, payload: bytes, filename: str, knowledge_base_id: str) -> dict:
        self.cleanup_expired()
        if not payload:
            raise QueryAssetError("Query image is empty")
        if len(payload) > self.max_bytes:
            raise QueryAssetError(f"Query image exceeds the {self.max_bytes}-byte limit", status_code=413)
        if not self.registry.get_knowledge_base(knowledge_base_id):
            raise QueryAssetError("Knowledge base not found", status_code=404)

        image_format, width, height, frame_count = self._inspect_image(payload)
        if frame_count > 1:
            raise QueryAssetError("Animated GIF images are not supported")
        media_type, suffix = ALLOWED_IMAGE_FORMATS[image_format]
        stored = self.object_store.put_bytes(payload)
        try:
            ocr = self._ocr(stored.path, suffix)
            expires_at = (datetime.utcnow() + timedelta(hours=self.ttl_hours)).isoformat(timespec="microseconds")
            safe_name = Path(filename or f"query-image{suffix}").name.replace("\x00", "")[:160] or f"query-image{suffix}"
            asset = self.registry.create_asset(
                knowledge_base_id=knowledge_base_id,
                kind="query",
                object_key=stored.object_key,
                original_name=safe_name,
                media_type=media_type,
                sha256=stored.sha256,
                size_bytes=stored.size_bytes,
                metadata={
                    "format": image_format.lower(),
                    "width": width,
                    "height": height,
                    "frame_count": frame_count,
                    "ocr_status": ocr.status,
                    "ocr_engine": ocr.engine,
                    "ocr_text": ocr.text[:8_000],
                    "ocr_warning": redact_sensitive_text(ocr.error) if ocr.error else "",
                },
                expires_at=expires_at,
            )
        except Exception as exc:
            # Content-addressed objects can be shared. Remove only objects that
            # no database row references after OCR or registry persistence fails.
            if self.registry.asset_reference_count(stored.object_key) == 0:
                self.object_store.delete(stored.object_key)
            raise QueryAssetError("Query image processing failed", status_code=503) from exc
        return self.public_payload(asset)

    def delete(self, asset_id: str) -> bool:
        asset = self.registry.get_asset(asset_id, include_private=True)
        if not asset or asset.get("kind") != "query":
            return False
        deleted = self.registry.delete_asset(asset_id)
        if deleted and self.registry.asset_reference_count(asset["object_key"]) == 0:
            self.object_store.delete(asset["object_key"])
        return bool(deleted)

    def cleanup_expired(self) -> int:
        now = datetime.utcnow()
        expired = 0
        for asset in self.registry.list_assets(kind="query", include_private=True):
            try:
                expiry = datetime.fromisoformat(str(asset.get("expires_at") or ""))
            except ValueError:
                expiry = now
            if expiry <= now and self.delete(asset["id"]):
                expired += 1
        return expired

    def enrich_query(self, question: str, attachments: list, knowledge_base_ids: list[str]) -> tuple[str, list[dict]]:
        if not attachments:
            return question, []
        if len(attachments) > self.max_count:
            raise QueryAssetError(f"A query accepts at most {self.max_count} images")
        allowed_bases = set(knowledge_base_ids or ["default"])
        summaries: list[dict] = []
        query_parts: list[str] = [question]
        for index, reference in enumerate(attachments, start=1):
            if isinstance(reference, dict):
                asset_id = str(reference.get("id") or "")
                detail = str(reference.get("detail") or "auto")
            else:
                asset_id = str(getattr(reference, "id", ""))
                detail = str(getattr(reference, "detail", "auto"))
            asset = self.registry.get_asset(asset_id, include_private=True)
            if not asset or asset.get("kind") != "query":
                raise QueryAssetError("Query image not found", status_code=404)
            if asset["knowledge_base_id"] not in allowed_bases:
                raise QueryAssetError("Query image does not belong to the selected knowledge base", status_code=403)
            try:
                expires_at = datetime.fromisoformat(asset["expires_at"])
            except ValueError as exc:
                raise QueryAssetError("Query image expiry metadata is invalid", status_code=410) from exc
            if expires_at <= datetime.utcnow():
                self.delete(asset_id)
                raise QueryAssetError("Query image expired; upload it again", status_code=410)
            path = self.object_store.path_for(asset["object_key"])
            if not path.is_file():
                raise QueryAssetError("Query image content is unavailable", status_code=410)
            metadata = asset.get("metadata") or {}
            ocr_text = str(metadata.get("ocr_text") or "").strip()
            image_data_url = f"data:{asset['media_type']};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"
            element = DocumentElement(
                element_id=f"query:{asset_id}",
                document_id="query",
                type="image",
                order=index - 1,
                text=ocr_text,
                caption="",
                asset_id=asset_id,
                confidence=1.0 if ocr_text else 0.0,
                metadata={key: metadata.get(key) for key in ("format", "width", "height", "ocr_status", "ocr_engine")},
            )
            enriched = self.enricher.enrich(
                element,
                {"text": question, "element_ids": [element.element_id], "image_detail": detail},
                image_data_url=image_data_url,
            )
            description = str(enriched.get("description") or ocr_text or asset["original_name"]).strip()[:2_000]
            keywords = [str(item)[:120] for item in enriched.get("keywords", []) if str(item).strip()][:16]
            query_parts.append(
                f"[Query image {index}: {asset['original_name']}]\n{description}\nKeywords: {', '.join(keywords)}"
            )
            summaries.append({
                **self.public_payload(asset),
                "detail": detail if detail in {"low", "high", "original", "auto"} else "auto",
                "description": description,
                "keywords": keywords,
                "ocr_status": metadata.get("ocr_status") or "unavailable",
                "provider": getattr(self.enricher, "provider", "template"),
            })
        return "\n\n".join(query_parts)[:12_000], summaries

    def public_payload(self, asset: dict) -> dict:
        metadata = asset.get("metadata") or {}
        return {
            "id": asset["id"],
            "filename": asset["original_name"],
            "media_type": asset["media_type"],
            "size_bytes": asset["size_bytes"],
            "width": int(metadata.get("width") or 0),
            "height": int(metadata.get("height") or 0),
            "expires_at": asset["expires_at"],
            "preview_url": f"/api/assets/{asset['id']}",
        }

    def _inspect_image(self, payload: bytes) -> tuple[str, int, int, int]:
        try:
            from PIL import Image, UnidentifiedImageError

            with Image.open(io.BytesIO(payload)) as image:
                image_format = str(image.format or "").upper()
                width, height = image.size
                frame_count = int(getattr(image, "n_frames", 1) or 1)
                if image_format not in ALLOWED_IMAGE_FORMATS:
                    raise QueryAssetError("Only PNG, JPEG, WEBP and non-animated GIF images are supported")
                if width <= 0 or height <= 0 or width * height > self.max_pixels:
                    raise QueryAssetError("Query image dimensions exceed the configured pixel limit", status_code=413)
                image.verify()
        except QueryAssetError:
            raise
        except (OSError, UnidentifiedImageError, ValueError) as exc:
            raise QueryAssetError("Query image signature or content is invalid") from exc
        return image_format, width, height, frame_count

    def _ocr(self, object_path: Path, suffix: str):
        with tempfile.NamedTemporaryFile(suffix=suffix) as temporary:
            temporary.write(object_path.read_bytes())
            temporary.flush()
            return self.ocr_adapter.extract_text(Path(temporary.name))
