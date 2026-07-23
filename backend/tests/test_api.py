from fastapi.testclient import TestClient

from app.api.routers import documents
from app.main import app
from app.services.url_importer import ImportedUrl


def test_create_query_rewriter_returns_rewriter_instance(monkeypatch):
    from app.config import settings
    from app.core.store import create_query_rewriter
    from app.services.query_rewriter import BaseQueryRewriter

    monkeypatch.setattr(settings, "query_rewrite_provider", "responses")
    monkeypatch.setattr(settings, "query_rewrite_api_key", "test-key")
    monkeypatch.setattr(settings, "query_rewrite_base_url", "http://127.0.0.1:1")
    monkeypatch.setattr(settings, "query_rewrite_model", "test-model")
    monkeypatch.setattr(settings, "query_rewrite_count", 2)

    rewriter = create_query_rewriter()

    assert isinstance(rewriter, BaseQueryRewriter)
    assert not isinstance(rewriter, tuple)
    assert rewriter.name == "responses"


def test_ingest_ask_and_delete(monkeypatch, tmp_path):
    monkeypatch.setattr(documents, "DATA_DIR", tmp_path)
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200

    upload = client.post(
        "/api/documents",
        files={"file": ("rag.md", b"# RAG\n\nRAG uses retrieval and citations.", "text/markdown")},
    )
    assert upload.status_code == 200
    document_id = upload.json()["document"]["id"]
    assert upload.json()["document"]["metadata"]["index_status"] == "indexed"
    assert upload.json()["document"]["quality"]["score"] > 0
    assert upload.json()["document"]["summary"]["suggested_questions"]

    def fake_fetch_url(url: str, title: str = "", **kwargs):
        return ImportedUrl(
            url=url,
            title=title or "RAG URL Notes",
            filename="rag-url-notes.url.txt",
            text="RAG URL import supports retrieval evaluation and deployment notes.",
            metadata={"parser": "url_html", "source_url": url, "content_type": "text/html", "host": "example.com"},
        )

    monkeypatch.setattr(documents, "fetch_url", fake_fetch_url)
    imported = client.post("/api/imports/url", json={"url": "https://example.com/rag", "title": "RAG URL Notes"})
    assert imported.status_code == 200
    imported_document_id = imported.json()["document"]["id"]
    assert imported.json()["document"]["metadata"]["source_url"] == "https://example.com/rag"

    duplicate = client.post(
        "/api/documents",
        files={"file": ("rag-copy.md", b"# RAG\n\nRAG uses retrieval and citations.", "text/markdown")},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["deduped"] is True
    assert duplicate.json()["document"]["id"] == document_id

    detail = client.get(f"/api/documents/{document_id}")
    assert detail.status_code == 200
    detail_data = detail.json()
    assert detail_data["document"]["id"] == document_id
    assert detail_data["chunks"]
    assert detail_data["document"]["quality"]["suggestions"]

    overview = client.get("/api/knowledge/overview")
    assert overview.status_code == 200
    assert overview.json()["document_count"] >= 1
    assert overview.json()["avg_quality_score"] > 0

    rebuild = client.post(f"/api/documents/{document_id}/rebuild")
    assert rebuild.status_code == 200
    assert rebuild.json()["rebuilt"] is True

    ask = client.post(
        "/api/ask",
        json={
            "question": "What does RAG use?",
            "top_k": 3,
            "search_mode": "hybrid",
            "search_profile": "precision",
            "query_rewrite": False,
        },
    )
    assert ask.status_code == 200
    data = ask.json()
    assert data["citations"]
    assert "答案" in data["answer"]
    assert data["history_id"]
    assert data["retrieval_trace"]["search_profile"] == "precision"
    assert data["retrieval_trace"]["query_rewriter"] == "off"
    assert data["citations"][0]["score_breakdown"]
    assert data["trust"]["label"] in {"证据充分", "证据一般", "证据较弱", "无法确定"}
    assert data["citation_audit"]["checked"] is True
    assert {
        "grounding",
        "grounded_sentence_count",
        "weakly_grounded_claims",
        "grounding_overlap_threshold",
    } <= data["citation_audit"].keys()
    assert data["retrieval_trace"]["query_analysis"]["label"]
    assert data["gap_report"]["query_intent"]["label"]
    assert data["retrieval_trace"]["performance"]["total_ms"] >= 0
    assert data["citations"][0]["parent_context"]["strategy"] == "parent_child"

    context = client.get(f"/api/chunks/{data['citations'][0]['id']}/context")
    assert context.status_code == 200
    assert context.json()["context"]

    rewrite = client.post(
        "/api/answer/rewrite",
        json={
            "question": "What does RAG use?",
            "answer": data["answer"],
            "style": "highlights",
            "citations": data["citations"],
        },
    )
    assert rewrite.status_code == 200
    assert rewrite.json()["rewritten"]

    card = client.post(
        "/api/knowledge/cards",
        json={
            "question": "What does RAG use?",
            "answer": data["answer"],
            "citations": data["citations"],
            "tags": ["rag"],
        },
    )
    assert card.status_code == 200
    assert card.json()["card"]["id"]

    cards = client.get("/api/knowledge/cards")
    assert cards.status_code == 200
    assert cards.json()["cards"]

    gaps = client.post(
        "/api/knowledge/gaps",
        json={
            "query": "Does this project mention Kubernetes deployment?",
            "top_k": 3,
            "query_rewrite": False,
        },
    )
    assert gaps.status_code == 200
    assert "gap_report" in gaps.json()

    eval_case = client.post(
        "/api/eval/cases",
        json={"question": "What does RAG use?", "expected_keywords": ["retrieval"]},
    )
    assert eval_case.status_code == 200
    assert eval_case.json()["case"]["status"] == "draft"
    eval_case_id = eval_case.json()["case"]["id"]

    invalid_review = client.patch(
        f"/api/eval/cases/{eval_case_id}",
        json={
            "answerable": True,
            "reviewer_id": "portfolio-owner",
            "reviewer_attestation": "human-reviewed",
        },
    )
    assert invalid_review.status_code == 422

    reviewed = client.patch(
        f"/api/eval/cases/{eval_case_id}",
        json={
            "expected_keywords": ["retrieval", "citations"],
            "expected_answer": "RAG uses retrieval and citations.",
            "expected_document_ids": [document_id],
            "answerable": True,
            "note": "Verified against the cited source.",
            "reviewer_id": "portfolio-owner",
            "reviewer_attestation": "human-reviewed",
        },
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["case"]["status"] == "reviewed"
    assert reviewed.json()["summary"]["human_reviewed"] >= 1

    review_summary = client.get("/api/eval/review-summary")
    assert review_summary.status_code == 200
    assert review_summary.json()["remaining_for_1_0"] <= 199

    batch = client.post(
        "/api/eval/cases:batch",
        json={
            "cases": [
                {
                    "candidate_id": "candidate-stable-1",
                    "question": "Which source describes citation coverage?",
                    "source_ref": "https://example.test/evidence",
                },
                {
                    "candidate_id": "candidate-stable-2",
                    "question": "When should the system refuse?",
                    "source_ref": "https://example.test/refusal",
                },
            ]
        },
    )
    assert batch.status_code == 200
    assert batch.json()["created"] == 2
    repeated_batch = client.post(
        "/api/eval/cases:batch",
        json={
            "cases": [
                {
                    "candidate_id": "candidate-stable-1",
                    "question": "Which source describes citation coverage?",
                }
            ]
        },
    )
    assert repeated_batch.status_code == 200
    assert repeated_batch.json()["created"] == 0
    assert repeated_batch.json()["deduped"] == 1

    run_drafts = client.post("/api/eval/run-drafts")
    assert run_drafts.status_code == 200
    assert run_drafts.json()["case_count"] >= 1

    feedback = client.post(
        "/api/feedback",
        json={
            "history_id": data["history_id"],
            "question": "What does RAG use?",
            "answer": data["answer"],
            "rating": "down",
            "failure_type": "bad_answer",
            "feedback_text": "answer is too generic",
            "citations": data["citations"],
        },
    )
    assert feedback.status_code == 200
    assert feedback.json()["eval_case"]["status"] == "draft"
    assert feedback.json()["stats"]["negative"] >= 1

    drafts = client.get("/api/eval/drafts")
    assert drafts.status_code == 200
    assert drafts.json()["drafts"]

    search = client.post(
        "/api/search",
        json={
            "query": "RAG citations",
            "top_k": 2,
            "search_mode": "keyword",
            "document_ids": [document_id],
            "query_rewrite": False,
        },
    )
    assert search.status_code == 200
    search_data = search.json()
    assert search_data["results"]
    assert search_data["trace"]["search_mode"] == "keyword"
    assert search_data["trace"]["document_ids"] == [document_id]
    assert "diagnostics" in search_data

    compare = client.post(
        "/api/search/compare",
        json={
            "query": "RAG citations",
            "top_k": 2,
            "document_ids": [document_id],
            "query_rewrite": False,
        },
    )
    assert compare.status_code == 200
    compare_data = compare.json()
    assert len(compare_data["profiles"]) == 4
    assert compare_data["best_profile"] in {"keyword", "semantic", "hybrid", "hybrid_rerank"}

    history = client.get("/api/history")
    assert history.status_code == 200
    assert any(item["id"] == data["history_id"] for item in history.json()["history"])

    operations = client.get("/api/operations")
    assert operations.status_code == 200
    assert operations.json()["operations"]

    metrics = client.get("/api/metrics")
    assert metrics.status_code == 200
    assert metrics.json()["knowledge"]["document_count"] >= 1

    delete = client.delete(f"/api/documents/{document_id}")
    assert delete.status_code == 200
    delete_imported = client.delete(f"/api/documents/{imported_document_id}")
    assert delete_imported.status_code == 200

    ask_after_delete = client.post("/api/ask", json={"question": "What does RAG use?", "top_k": 3})
    assert ask_after_delete.status_code == 200
    after_delete_data = ask_after_delete.json()
    assert after_delete_data["citations"] == []
    assert after_delete_data["diagnostics"]
    assert after_delete_data["diagnostics"][0]["actions"]
