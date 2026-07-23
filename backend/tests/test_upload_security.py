from fastapi.testclient import TestClient

from app.api.routers import documents
from app.config import settings
from app.main import app


def test_upload_sanitizes_posix_path_components(monkeypatch, tmp_path):
    monkeypatch.setattr(documents, "DATA_DIR", tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/documents",
        files={"file": ("../../evil.md", b"RAG upload path validation content.", "text/markdown")},
    )

    assert response.status_code == 200
    assert response.json()["document"]["filename"] == "evil.md"
    assert all(path.parent == tmp_path for path in tmp_path.iterdir())
    delete = client.delete(f"/api/documents/{response.json()['document']['id']}")
    assert delete.status_code == 200
    assert list(tmp_path.iterdir()) == []


def test_upload_sanitizes_windows_path_components(monkeypatch, tmp_path):
    monkeypatch.setattr(documents, "DATA_DIR", tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/documents",
        files={"file": ("..\\..\\windows.md", b"Windows upload path validation content.", "text/markdown")},
    )

    assert response.status_code == 200
    assert response.json()["document"]["filename"] == "windows.md"
    client.delete(f"/api/documents/{response.json()['document']['id']}")


def test_upload_rejects_unsupported_extension_before_writing(monkeypatch, tmp_path):
    monkeypatch.setattr(documents, "DATA_DIR", tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/documents",
        files={"file": ("payload.exe", b"not executable", "application/octet-stream")},
    )

    assert response.status_code == 400
    assert list(tmp_path.iterdir()) == []


def test_oversized_upload_returns_413_and_removes_partial_file(monkeypatch, tmp_path):
    monkeypatch.setattr(documents, "DATA_DIR", tmp_path)
    monkeypatch.setattr(settings, "max_upload_bytes", 8)
    client = TestClient(app)

    response = client.post(
        "/api/documents",
        files={"file": ("large.md", b"123456789", "text/markdown")},
    )

    assert response.status_code == 413
    assert list(tmp_path.iterdir()) == []


def test_empty_upload_is_rejected_and_removed(monkeypatch, tmp_path):
    monkeypatch.setattr(documents, "DATA_DIR", tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/documents",
        files={"file": ("empty.md", b"", "text/markdown")},
    )

    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()
    assert list(tmp_path.iterdir()) == []


def test_image_extension_requires_matching_file_signature(monkeypatch, tmp_path):
    monkeypatch.setattr(documents, "DATA_DIR", tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/documents",
        files={"file": ("pretend.png", b"not really a png", "image/png")},
    )

    assert response.status_code == 400
    assert "signature" in response.json()["detail"].lower()
    assert list(tmp_path.iterdir()) == []
