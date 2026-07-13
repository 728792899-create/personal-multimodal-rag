from app.services.citation_audit import audit_answer


CITATIONS = [
    {
        "document_id": "doc-rag",
        "filename": "rag.md",
        "text": "RAG combines retrieval with citations to reduce unsupported model claims.",
        "rerank_score": 0.42,
    }
]


def test_grounded_sentence_has_high_overlap():
    result = audit_answer(
        "RAG combines retrieval with citations to reduce unsupported claims. [1]",
        CITATIONS,
        confidence=0.42,
        threshold=0.05,
        overlap_threshold=0.34,
    )

    audit = result["citation_audit"]
    assert audit["grounding"] >= 0.7
    assert audit["grounded_sentence_count"] == 1
    assert audit["weakly_grounded_claims"] == []


def test_citation_marker_without_evidence_overlap_is_flagged():
    result = audit_answer(
        "Kubernetes automatically guarantees perfect database consistency. [1]",
        CITATIONS,
        confidence=0.42,
        threshold=0.05,
        overlap_threshold=0.34,
    )

    audit = result["citation_audit"]
    assert audit["supported_sentence_count"] == 1
    assert audit["grounded_sentence_count"] == 0
    assert len(audit["weakly_grounded_claims"]) == 1
    assert audit["weakly_grounded_claims"][0]["overlap"] < 0.34
    assert audit["weakly_grounded_claims"][0]["reason"] == "cited_but_low_overlap"


def test_claim_is_checked_against_the_citation_it_actually_references():
    citations = [
        {
            "document_id": "doc-ui",
            "filename": "vue.md",
            "text": "Vue components coordinate reactive state and user interface rendering.",
            "rerank_score": 0.40,
        },
        {
            "document_id": "doc-rag",
            "filename": "rag.md",
            "text": "RAG combines retrieval with citations to reduce unsupported model claims.",
            "rerank_score": 0.39,
        },
    ]

    result = audit_answer(
        "RAG combines retrieval with citations to reduce unsupported model claims. [1]",
        citations,
        confidence=0.40,
        threshold=0.05,
        overlap_threshold=0.34,
    )

    weak_claim = result["citation_audit"]["weakly_grounded_claims"][0]
    assert weak_claim["citation_indexes"] == [1]
    assert weak_claim["overlap"] < 0.34


def test_uncited_sentence_remains_unsupported_and_ungrounded():
    result = audit_answer(
        "This unrelated conclusion has no citation marker.",
        CITATIONS,
        confidence=0.42,
        threshold=0.05,
        overlap_threshold=0.34,
    )

    audit = result["citation_audit"]
    assert audit["unsupported_sentence_count"] == 1
    assert audit["grounded_sentence_count"] == 0
    assert audit["grounding"] == 0


def test_grounding_overlap_threshold_is_reported():
    result = audit_answer(
        "答案：\n无关句子。",
        CITATIONS,
        confidence=0.0,
        threshold=0.05,
        overlap_threshold=0.5,
    )

    assert result["citation_audit"]["grounding_overlap_threshold"] == 0.5
