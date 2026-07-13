from pathlib import Path

from fastapi.testclient import TestClient

from app.api import routes
from app.main import app


ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "samples" / "demo-documents" / "02-rag-workbench-technical.md"


def test_demo_documents_ingest_and_ask(monkeypatch, tmp_path):
    monkeypatch.setattr(routes, "DATA_DIR", tmp_path)
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    upload = client.post(
        "/api/documents",
        files={"file": (SAMPLE.name, SAMPLE.read_bytes(), "text/markdown")},
    )
    assert upload.status_code == 200
    document = upload.json()["document"]
    assert document["chunk_count"] > 0

    ask = client.post(
        "/api/ask",
        json={
            "question": "这个 RAG 项目如何展示引用可信度？",
            "top_k": 4,
            "search_mode": "hybrid",
            "query_rewrite": False,
        },
    )
    assert ask.status_code == 200
    data = ask.json()
    assert data["answer"]
    assert data["citations"]
    assert data["citations"][0]["score"] >= 0
    assert data["citations"][0]["score_breakdown"]
    assert data["retrieval_trace"]
    assert data["retrieval_trace"]["search_mode"] == "hybrid"
    assert "fallbacks" in data["retrieval_trace"]
    delete = client.delete(f"/api/documents/{document['id']}")
    assert delete.status_code == 200
