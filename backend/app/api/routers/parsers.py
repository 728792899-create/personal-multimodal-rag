from __future__ import annotations

from fastapi import APIRouter

from app.config import settings
from app.core.store import parser_worker_client
from app.services.document_processor import SUPPORTED_EXTENSIONS
from app.services.safe_logging import redact_sensitive_text


router = APIRouter(tags=["parsers"])


@router.get("/parsers/status")
def parser_status():
    profiles = [
        {
            "id": "builtin",
            "label": "Built-in structured parser",
            "available": True,
            "isolated": False,
            "formats": sorted(SUPPORTED_EXTENSIONS),
            "capabilities": ["text", "headings", "pdf-layout", "docx-tables", "docx-omml", "ocr-metadata"],
        }
    ]
    worker_enabled = settings.parser_provider.lower() != "builtin"
    worker_error = ""
    remote_profiles: list[dict] = []
    if worker_enabled:
        try:
            payload = parser_worker_client.capabilities()
            remote_profiles = payload.get("profiles") if isinstance(payload.get("profiles"), list) else []
        except Exception as exc:
            worker_error = redact_sensitive_text(exc)
    known = {str(item.get("id")) for item in remote_profiles}
    for profile in ("mineru", "docling", "paddleocr"):
        remote = next((item for item in remote_profiles if item.get("id") == profile), {})
        profiles.append(
            {
                "id": profile,
                "label": profile,
                "available": bool(remote.get("available")) if worker_enabled else False,
                "isolated": True,
                "formats": sorted(set(remote.get("formats", [])) & SUPPORTED_EXTENSIONS),
                "capabilities": remote.get("capabilities", ["image", "table", "equation", "layout"]),
                "reason": worker_error or ("advanced-parser profile disabled" if not worker_enabled else ("not reported by worker" if profile not in known else "")),
            }
        )
    return {
        "default": settings.parser_provider,
        "fallback_allowed": settings.parser_fallback_allowed,
        "profiles": profiles,
    }
