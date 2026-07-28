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


def test_out_of_range_citation_marker_does_not_count_as_supported():
    result = audit_answer(
        "RAG combines retrieval with citations to reduce unsupported claims. [999]",
        CITATIONS,
        confidence=0.42,
        threshold=0.05,
        overlap_threshold=0.34,
    )

    audit = result["citation_audit"]
    assert audit["coverage"] == 0
    assert audit["supported_sentence_count"] == 0
    assert audit["unsupported_sentence_count"] == 1
    assert audit["grounded_sentence_count"] == 0


def test_grouped_citation_markers_reference_every_listed_source():
    citations = [
        {
            "document_id": "doc-1",
            "filename": "source-1.md",
            "text": "破军是慕湮剑圣的弟子，九百年前被剑圣封印。",
            "rerank_score": 0.42,
        },
        {
            "document_id": "doc-2",
            "filename": "source-2.md",
            "text": "迦楼罗金翅鸟是破军的巨大机械座驾。",
            "rerank_score": 0.40,
        },
    ]
    result = audit_answer(
        "破军是慕湮剑圣的弟子，迦楼罗金翅鸟是他的座驾。[1, 2]",
        citations,
        confidence=0.42,
        threshold=0.05,
        overlap_threshold=0.20,
    )

    audit = result["citation_audit"]
    assert audit["supported_sentence_count"] == 1
    assert audit["grounded_sentence_count"] == 1
    assert audit["weakly_grounded_claims"] == []


def test_markdown_structural_headings_are_not_counted_as_claims():
    result = audit_answer(
        "### 答案\nRAG combines retrieval with citations to reduce unsupported claims.[1]\n"
        "### 依据\n### 不确定性\n### 后续建议",
        CITATIONS,
        confidence=0.42,
        threshold=0.05,
        overlap_threshold=0.34,
    )

    audit = result["citation_audit"]
    assert audit["sentence_count"] == 1
    assert audit["supported_sentence_count"] == 1


def test_chinese_sentences_without_spaces_are_audited_separately():
    citations = [
        {
            "document_id": "doc-rag",
            "filename": "rag.md",
            "text": "混合检索结合关键词召回和向量召回来提高证据覆盖率。",
            "rerank_score": 0.42,
        }
    ]
    result = audit_answer(
        "这是没有任何引用支持的第一条结论。混合检索结合关键词召回和向量召回来提高证据覆盖率。[1]",
        citations,
        confidence=0.42,
        threshold=0.05,
        overlap_threshold=0.34,
    )

    audit = result["citation_audit"]
    assert audit["sentence_count"] == 2
    assert audit["supported_sentence_count"] == 1
    assert audit["unsupported_sentence_count"] == 1
    assert audit["coverage"] == 0.5
    assert audit["grounded_sentence_count"] == 1


def test_low_grounding_cannot_receive_medium_or_strong_trust():
    citations = [
        {
            "document_id": f"doc-{index}",
            "filename": f"source-{index}.md",
            "text": "RAG combines retrieval with citations to reduce unsupported model claims.",
            "rerank_score": 0.9,
        }
        for index in range(1, 4)
    ]
    result = audit_answer(
        "Kubernetes automatically guarantees perfect database consistency. [1]",
        citations,
        confidence=0.9,
        threshold=0.05,
        overlap_threshold=0.34,
    )

    assert result["citation_audit"]["coverage"] == 1
    assert result["citation_audit"]["grounding"] == 0
    assert result["trust"]["level"] == "weak"
