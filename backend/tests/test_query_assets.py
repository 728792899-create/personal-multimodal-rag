from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.services.document_registry import DocumentRegistry
from app.services.multimodal_enrichment import TemplateMultimodalEnricher
from app.services.object_store import LocalObjectStore
from app.services.ocr import OCRResult
from app.services.query_assets import QueryAssetError, QueryAssetService


class StaticOCR:
    def __init__(self, text: str = "Architecture diagram: Alpha uses Beta"):
        self.text = text

    def extract_text(self, _path: Path) -> OCRResult:
        return OCRResult(text=self.text, status="ok", engine="fixture")


class FailingOCR:
    def extract_text(self, _path: Path) -> OCRResult:
        raise RuntimeError("fixture OCR failure")


def image_bytes(image_format: str = "PNG", *, animated: bool = False) -> bytes:
    buffer = io.BytesIO()
    first = Image.new("RGB", (32, 24), color=(35, 100, 190))
    if animated:
        second = Image.new("RGB", (32, 24), color=(190, 90, 35))
        first.save(buffer, format="GIF", save_all=True, append_images=[second], duration=100, loop=0)
    else:
        first.save(buffer, format=image_format)
    return buffer.getvalue()


def service(tmp_path: Path, *, max_bytes: int = 10 * 1024 * 1024) -> QueryAssetService:
    return QueryAssetService(
        DocumentRegistry(str(tmp_path / "registry.sqlite3")),
        LocalObjectStore(tmp_path / "objects"),
        TemplateMultimodalEnricher(),
        max_bytes=max_bytes,
        ocr_adapter=StaticOCR(),
    )


def test_query_asset_lifecycle_and_offline_enrichment(tmp_path: Path):
    query_assets = service(tmp_path)
    created = query_assets.create(image_bytes(), "diagram.png", "default")

    expanded, summaries = query_assets.enrich_query(
        "How is Alpha connected?",
        [{"id": created["id"], "detail": "high"}],
        ["default"],
    )

    assert created["media_type"] == "image/png"
    assert created["width"] == 32 and created["height"] == 24
    assert created["preview_url"].endswith(created["id"])
    assert "Alpha uses Beta" in expanded
    assert summaries[0]["detail"] == "high"
    assert summaries[0]["provider"] == "template"
    private = query_assets.registry.get_asset(created["id"], include_private=True)
    assert private and "object_key" in private
    object_path = query_assets.object_store.path_for(private["object_key"])
    assert object_path.is_file()
    assert query_assets.delete(created["id"]) is True
    assert not object_path.exists()


def test_query_assets_reject_invalid_oversized_and_animated_images(tmp_path: Path):
    oversized_payload = image_bytes()
    query_assets = service(tmp_path, max_bytes=len(oversized_payload) - 1)
    with pytest.raises(QueryAssetError, match="大小上限"):
        query_assets.create(oversized_payload, "large.png", "default")

    query_assets = service(tmp_path / "animated")
    with pytest.raises(QueryAssetError, match="动态 GIF"):
        query_assets.create(image_bytes(animated=True), "moving.gif", "default")
    with pytest.raises(QueryAssetError, match="签名"):
        query_assets.create(b"not an image", "fake.png", "default")


def test_query_asset_creation_cleans_unreferenced_object_after_ocr_failure(tmp_path: Path):
    query_assets = QueryAssetService(
        DocumentRegistry(str(tmp_path / "registry.sqlite3")),
        LocalObjectStore(tmp_path / "objects"),
        TemplateMultimodalEnricher(),
        ocr_adapter=FailingOCR(),
    )

    with pytest.raises(QueryAssetError, match="处理失败") as failure:
        query_assets.create(image_bytes(), "diagram.png", "default")

    assert failure.value.status_code == 503
    assert list((tmp_path / "objects").rglob("*")) == []


def test_query_asset_expiry_and_knowledge_base_boundary(tmp_path: Path):
    query_assets = service(tmp_path)
    other = query_assets.registry.create_knowledge_base("Other")
    created = query_assets.create(image_bytes(), "private.png", other["id"])

    with pytest.raises(QueryAssetError, match="当前选择的知识库") as forbidden:
        query_assets.enrich_query("question", [{"id": created["id"]}], ["default"])
    assert forbidden.value.status_code == 403

    with query_assets.registry.transaction() as connection:
        connection.execute("UPDATE assets SET expires_at = '2000-01-01T00:00:00' WHERE asset_id = ?", (created["id"],))
    with pytest.raises(QueryAssetError, match="已过期") as expired:
        query_assets.enrich_query("question", [{"id": created["id"]}], [other["id"]])
    assert expired.value.status_code == 410
    assert query_assets.registry.get_asset(created["id"]) is None


def test_query_asset_api_and_sse_add_typed_enrichment_events(monkeypatch, tmp_path: Path):
    from app.api.routers import conversations, documents, query_assets as query_assets_router
    from app.main import app

    query_assets = service(tmp_path)
    monkeypatch.setattr(query_assets_router, "query_asset_service", query_assets)
    monkeypatch.setattr(conversations, "query_asset_service", query_assets)
    monkeypatch.setattr(documents, "query_asset_service", query_assets)
    monkeypatch.setattr(documents, "registry", query_assets.registry)
    monkeypatch.setattr(documents, "object_store", query_assets.object_store)

    with TestClient(app) as client:
        upload = client.post(
            "/api/query-assets",
            data={"knowledge_base_id": "default"},
            files=[("files", ("diagram.png", image_bytes(), "image/png"))],
        )
        assert upload.status_code == 201
        attachment = upload.json()["assets"][0]
        assert "object_key" not in upload.text
        preview = client.get(attachment["preview_url"])
        assert preview.status_code == 200
        assert preview.headers["content-type"] == "image/png"

        conversation_id = client.post(
            "/api/conversations",
            json={"title": "Multimodal", "knowledge_base_ids": ["default"]},
        ).json()["conversation"]["id"]
        response = client.post(
            f"/api/conversations/{conversation_id}/messages:stream",
            json={
                "question": "What does the diagram describe?",
                "attachments": [{"id": attachment["id"], "detail": "high"}],
                "query_rewrite": False,
            },
        )
        events = [line.removeprefix("event: ") for line in response.text.splitlines() if line.startswith("event: ")]
        assert events[:3] == ["query.enrichment.started", "query.enrichment.completed", "retrieval.started"]
        payloads = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        completed = next(item for item in payloads if item["type"] == "query.enrichment.completed")
        assert completed["attachments"][0]["detail"] == "high"
        sequences = [item["sequence"] for item in payloads]
        assert sequences == list(range(1, len(sequences) + 1))

        deleted = client.delete(f"/api/query-assets/{attachment['id']}")
        assert deleted.status_code == 200
        assert client.get(attachment["preview_url"]).status_code == 404
