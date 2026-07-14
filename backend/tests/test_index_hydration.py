from app.services.document_processor import DocumentProcessor
from app.services.index_hydration import hydrate_retriever
from app.services.retriever import HybridRetriever


def test_memory_index_is_rebuilt_from_registered_documents(tmp_path):
    source = tmp_path / "rag.md"
    source.write_text("固定黄金集使用 Recall@K、MRR 和引用准确率。", encoding="utf-8")
    processor = DocumentProcessor()
    document = processor.parse_file(source)
    restarted_retriever = HybridRetriever()

    rebuilt = hydrate_retriever(restarted_retriever, processor, [document])
    results, trace = restarted_retriever.search("黄金集 MRR", query_rewrite=False)

    assert rebuilt == 1
    assert trace["available_chunks"] > 0
    assert results[0]["chunk"].document_id == document.document_id


def test_persisted_chunks_are_not_reembedded(tmp_path):
    source = tmp_path / "rag.md"
    source.write_text("BM25 和向量检索组成混合召回。", encoding="utf-8")
    processor = DocumentProcessor()
    document = processor.parse_file(source)
    retriever = HybridRetriever()
    retriever.add_document(document, processor.split(document))

    rebuilt = hydrate_retriever(retriever, processor, [document])

    assert rebuilt == 0


def test_incompatible_embedding_metadata_is_quarantined_for_rebuild(tmp_path):
    source = tmp_path / "legacy.md"
    source.write_text("legacy vector dimensions must not mix", encoding="utf-8")
    processor = DocumentProcessor()
    document = processor.parse_file(source)
    document.metadata.update({
        "embedding_provider": "mock",
        "embedding_model": "legacy-hash",
        "embedding_dimension": 64,
        "index_version": "legacy-v0",
    })
    retriever = HybridRetriever()
    retriever.add_document(document, processor.split(document))
    quarantined = []

    rebuilt = hydrate_retriever(
        retriever,
        processor,
        [document],
        expected_embedding_provider="mock",
        expected_embedding_model="hash-mock",
        expected_embedding_dimension=256,
        expected_index_version="hybrid-v1",
        on_mismatch=quarantined.append,
    )

    assert rebuilt == 0
    assert document.metadata["index_status"] == "needs_rebuild"
    assert document.metadata["index_mismatch"]["embedding_dimension"] == {"stored": 64, "expected": 256}
    assert quarantined == [document]
    assert not retriever.vector_store.chunks
