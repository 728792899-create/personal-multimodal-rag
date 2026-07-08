import importlib.util
from pathlib import Path

import pytest

from app.services.document_processor import DocumentProcessor
from app.services.embeddings import MockEmbeddingProvider
from app.services.retriever import HybridRetriever
from app.services.vectorstore import ChromaVectorStore


pytestmark = pytest.mark.skipif(importlib.util.find_spec("chromadb") is None, reason="chromadb not installed")


def test_chroma_vector_store_recovers_chunks_after_restart(tmp_path: Path):
    file_path = tmp_path / "rag.md"
    file_path.write_text("RAG 召回优化需要结合 BM25、向量检索和 Rerank。", encoding="utf-8")
    processor = DocumentProcessor()
    document = processor.parse_file(file_path)
    chunks = processor.split(document)

    persist_path = str(tmp_path / "chroma")
    collection = "test_recover_chunks"
    provider = MockEmbeddingProvider(vector_dim=32)
    first_store = ChromaVectorStore(persist_path=persist_path, collection_name=collection)
    first_retriever = HybridRetriever(embedding_provider=provider, vector_store=first_store)
    first_retriever.add_document(document, chunks)

    recovered_store = ChromaVectorStore(persist_path=persist_path, collection_name=collection)
    recovered_retriever = HybridRetriever(embedding_provider=provider, vector_store=recovered_store)
    recovered_retriever.load_documents([document])
    results, trace = recovered_retriever.search("BM25 向量检索", top_k=3)

    assert trace["total_chunks"] == len(chunks)
    assert results
    assert results[0]["chunk"].document_id == document.document_id
