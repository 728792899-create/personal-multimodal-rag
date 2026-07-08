from pathlib import Path

from app.services.document_processor import DocumentProcessor
from app.services.embeddings import BaseEmbeddingProvider
from app.services.embeddings import MockEmbeddingProvider
from app.services.retriever import HybridRetriever


def test_mock_embedding_is_stable():
    provider = MockEmbeddingProvider(vector_dim=32)

    assert provider.embed_text("RAG 检索") == provider.embed_text("RAG 检索")
    assert len(provider.embed_text("RAG 检索")) == 32


def test_hybrid_retriever_search_and_delete(tmp_path: Path):
    file_path = tmp_path / "rag.md"
    file_path.write_text("RAG 召回优化需要结合 BM25、向量检索和 Rerank。", encoding="utf-8")
    processor = DocumentProcessor()
    document = processor.parse_file(file_path)
    chunks = processor.split(document)

    retriever = HybridRetriever()
    retriever.add_document(document, chunks)
    results, trace = retriever.search("BM25 向量检索", top_k=3)

    assert trace["total_chunks"] == len(chunks)
    assert trace["reranker"] == "keyword"
    assert results
    assert "rerank_score" in results[0]
    assert results[0]["chunk"].document_id == document.document_id

    assert retriever.delete_document(document.document_id) is True
    results_after_delete, trace_after_delete = retriever.search("BM25", top_k=3)
    assert results_after_delete == []
    assert trace_after_delete["total_chunks"] == 0


def test_retriever_supports_modes_and_document_filter(tmp_path: Path):
    processor = DocumentProcessor()
    first_path = tmp_path / "rag.md"
    second_path = tmp_path / "frontend.md"
    first_path.write_text("RAG 使用 BM25、向量检索和引用证据降低幻觉。", encoding="utf-8")
    second_path.write_text("Vue 前端工作台关注组件状态、交互反馈和响应式布局。", encoding="utf-8")

    first_doc = processor.parse_file(first_path)
    second_doc = processor.parse_file(second_path)
    retriever = HybridRetriever()
    retriever.add_document(first_doc, processor.split(first_doc))
    retriever.add_document(second_doc, processor.split(second_doc))

    keyword_results, keyword_trace = retriever.search("Vue 组件状态", top_k=3, search_mode="keyword")
    assert keyword_results
    assert keyword_trace["search_mode"] == "keyword"
    assert keyword_trace["bm25_weight"] == 1.0
    assert keyword_trace["vector_weight"] == 0.0

    filtered_results, filtered_trace = retriever.search(
        "Vue 组件状态",
        top_k=3,
        document_ids=[first_doc.document_id],
        search_profile="precision",
        query_rewrite=False,
    )
    assert filtered_trace["document_ids"] == [first_doc.document_id]
    assert filtered_trace["query_rewriter"] == "off"
    assert all(item["chunk"].document_id == first_doc.document_id for item in filtered_results)


def test_retriever_falls_back_when_reranker_fails(tmp_path: Path):
    class BrokenReranker:
        name = "broken"

        def rerank(self, question: str, candidates: list[dict], top_k: int) -> list[dict]:
            raise RuntimeError("reranker unavailable")

    file_path = tmp_path / "rag.md"
    file_path.write_text("RAG 召回优化需要稳定的 fallback 机制。", encoding="utf-8")
    processor = DocumentProcessor()
    document = processor.parse_file(file_path)
    retriever = HybridRetriever(reranker=BrokenReranker())
    retriever.add_document(document, processor.split(document))

    results, trace = retriever.search("RAG fallback", top_k=3)

    assert results
    assert trace["rerank_status"] == "fallback"
    assert trace["fallbacks"][0]["stage"] == "rerank"
    assert "rerank_score" in results[0]


def test_retriever_falls_back_to_keyword_when_vector_fails(tmp_path: Path):
    class BrokenEmbeddingProvider(BaseEmbeddingProvider):
        def embed_text(self, text: str) -> list[float]:
            raise RuntimeError("embedding unavailable")

        def embed_batch(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("embedding unavailable")

    file_path = tmp_path / "rag.md"
    file_path.write_text("RAG 召回优化需要结合关键词检索和向量检索。", encoding="utf-8")
    processor = DocumentProcessor()
    document = processor.parse_file(file_path)
    retriever = HybridRetriever()
    retriever.add_document(document, processor.split(document))
    retriever.embedding_provider = BrokenEmbeddingProvider()

    results, trace = retriever.search("RAG 召回", top_k=3, search_mode="semantic")

    assert results
    assert trace["vector_status"] == "fallback"
    assert trace["bm25_weight"] == 1.0
    assert trace["vector_weight"] == 0.0
