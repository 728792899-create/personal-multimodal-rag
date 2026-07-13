from pathlib import Path

from app.services.document_processor import DocumentProcessor
from app.services.rag_engine import RagEngine
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
