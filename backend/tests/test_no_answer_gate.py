from pathlib import Path
from types import SimpleNamespace

from app.services.document_processor import DocumentProcessor
from app.services.rag_engine import RagEngine, _extract_direct_identifiers
from app.services.retriever import HybridRetriever


class StaticRetriever:
    def __init__(self, ranked: list[dict]):
        self.ranked = ranked

    def search(self, question: str, top_k: int = 5, **options):
        return self.ranked, {
            "available_chunks": len(self.ranked),
            "search_mode": options.get("search_mode", "hybrid"),
            "fallbacks": [],
        }


def _real_engine(tmp_path: Path) -> RagEngine:
    source = tmp_path / "rag.md"
    source.write_text("RAG 使用 BM25 向量检索和引用来降低幻觉。", encoding="utf-8")
    processor = DocumentProcessor()
    document = processor.parse_file(source)
    retriever = HybridRetriever()
    retriever.add_document(document, processor.split(document))
    return RagEngine(retriever, grounding_min_confidence=0.15)


def test_no_ranked_evidence_is_refused():
    engine = RagEngine(StaticRetriever([]), no_answer_threshold=0.05, grounding_min_confidence=0.15)

    result = engine.ask("unknown question")

    assert result["citations"] == []
    assert result["generation_trace"]["skipped"] is True
    assert result["generation_trace"]["reason"] == "no_evidence"
    assert result["retrieval_trace"]["refuse_reason"] == "no_evidence"


def test_weak_score_without_matched_terms_is_refused():
    ranked = [
        {
            "score": 0.10,
            "rerank_score": 0.10,
            "matched_terms": [],
            "chunk": object(),
        }
    ]
    engine = RagEngine(
        StaticRetriever(ranked),
        no_answer_threshold=0.05,
        grounding_min_confidence=0.15,
    )

    result = engine.ask("question with no lexical support")

    assert result["citations"] == []
    assert result["generation_trace"]["reason"] == "weak_grounding"
    assert result["retrieval_trace"]["refuse_reason"] == "weak_grounding"


def test_off_topic_question_is_refused_with_real_retrieval(tmp_path):
    result = _real_engine(tmp_path).ask(
        "iOS 原生支付对账集群",
        search_mode="keyword",
        query_rewrite=False,
    )

    assert result["citations"] == []
    assert result["generation_trace"]["reason"] in {
        "no_evidence",
        "below_threshold",
        "weak_grounding",
    }


def test_on_topic_question_still_returns_evidence(tmp_path):
    result = _real_engine(tmp_path).ask(
        "BM25 向量检索",
        search_mode="keyword",
        query_rewrite=False,
    )

    assert result["citations"]


def test_mock_embedding_rejects_only_generic_lexical_overlap(tmp_path):
    source = tmp_path / "workflow.md"
    source.write_text("系统提供检索流程、参数配置和 API 封装。", encoding="utf-8")
    processor = DocumentProcessor()
    document = processor.parse_file(source)
    retriever = HybridRetriever()
    retriever.add_document(document, processor.split(document))

    result = RagEngine(retriever).ask("视频转码 HLS 切片参数怎么配置？", query_rewrite=False)

    assert result["citations"] == []
    assert result["retrieval_trace"]["refusal_reason"] == "weak_grounding"


def test_mock_embedding_rejects_project_only_overlap(tmp_path):
    source = tmp_path / "overview.md"
    source.write_text("该项目面向个人知识库问答，目标是展示检索链路。", encoding="utf-8")
    processor = DocumentProcessor()
    document = processor.parse_file(source)
    retriever = HybridRetriever()
    retriever.add_document(document, processor.split(document))

    result = RagEngine(retriever).ask(
        "本项目的支付对账 SLA 和退款审批规则是什么？",
        query_rewrite=False,
    )

    assert result["citations"] == []
    assert result["retrieval_trace"]["refusal_reason"] == "weak_grounding"


def test_mock_embedding_rejects_automatic_only_overlap(tmp_path):
    source = tmp_path / "jobs.md"
    source.write_text("索引任务最多自动尝试三次，失败后记录脱敏错误。", encoding="utf-8")
    processor = DocumentProcessor()
    document = processor.parse_file(source)
    retriever = HybridRetriever()
    retriever.add_document(document, processor.split(document))

    result = RagEngine(retriever).ask(
        "支付系统的每日对账差异如何自动冲正？",
        min_score=0.05,
        query_rewrite=False,
    )

    assert result["citations"] == []
    assert result["retrieval_trace"]["refusal_reason"] == "weak_grounding"


def test_deterministic_idempotency_alias_finds_explicit_evidence(tmp_path):
    source = tmp_path / "jobs.md"
    source.write_text("内容哈希和索引版本共同组成幂等键。", encoding="utf-8")
    processor = DocumentProcessor()
    document = processor.parse_file(source)
    retriever = HybridRetriever()
    retriever.add_document(document, processor.split(document))

    result = RagEngine(retriever).ask("重复提交是如何避免的？", query_rewrite=False)

    assert result["citations"]
    assert "幂等键" in result["citations"][0]["text"]


def test_direct_identifier_parser_preserves_version_identifiers():
    assert _extract_direct_identifiers(
        "A100、release-v2.1 与 module_name-3；123invalid 以及 no-digits"
    ) == ["a100", "release-v2.1", "module_name-3"]


def test_direct_identifier_parser_preserves_unicode_boundaries_and_trailing_underscore():
    assert _extract_direct_identifiers("解释模型v2、v3配置和 module3_") == ["module3_"]


def test_similar_identifier_cannot_bypass_explicit_evidence_gap():
    ranked = [
        {
            "score": 0.9,
            "rerank_score": 0.9,
            "matched_terms": ["配置"],
            "chunk": SimpleNamespace(text="模型 v20 的配置未提供"),
        }
    ]
    engine = RagEngine(StaticRetriever(ranked))

    assert engine._should_refuse("解释 v2 的缺失配置", ranked, 0.9, 0.05) == (
        True,
        "explicit_evidence_gap",
    )


def test_direct_identifier_parser_handles_adversarial_long_input_linearly():
    query = ("segment-without-digits-" * 20_000) + "tail"

    assert _extract_direct_identifiers(query) == []
