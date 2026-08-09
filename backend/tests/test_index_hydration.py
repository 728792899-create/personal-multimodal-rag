from app.models.domain import Chunk
from app.services.document_processor import DocumentProcessor
from app.services.index_hydration import hydrate_retriever
from app.services.retriever import HybridRetriever
from app.services.vectorstore import MemoryVectorStore


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


def test_orphan_vector_can_be_deleted_without_a_loaded_document():
    store = MemoryVectorStore()
    chunk = Chunk(
        chunk_id="orphan:0",
        document_id="orphan",
        chunk_index=0,
        text="partial write",
        file_name="interrupted.md",
    )
    store.add_chunks([chunk], [[0.1, 0.2]])
    retriever = HybridRetriever(vector_store=store)

    assert retriever.delete_document("orphan") is True
    assert store.chunks == {}
    assert store.embeddings == {}
    assert retriever.delete_document("orphan") is False


def test_versioned_persistent_index_is_never_rebuilt_during_web_hydration(tmp_path):
    class PersistentStore(MemoryVectorStore):
        supports_persistent_sparse = True

        def sparse_search(self, *_args, **_kwargs):
            return []

    class FailingEmbedding:
        def embed_batch(self, _texts):
            raise AssertionError("web startup must not call cloud embedding")

    source = tmp_path / "registered.md"
    source.write_text("影子索引必须通过耐久任务重建。", encoding="utf-8")
    processor = DocumentProcessor()
    document = processor.parse_file(source)
    retriever = HybridRetriever(
        vector_store=PersistentStore(),
        embedding_provider=FailingEmbedding(),
    )

    rebuilt = hydrate_retriever(
        retriever,
        processor,
        [document],
        expected_embedding_provider="openai",
        expected_embedding_model="text-embedding-3-large",
        expected_embedding_dimension=1536,
        expected_index_version="retrieval-v2",
    )

    assert rebuilt == 0
    assert retriever.documents[document.document_id] is document
    assert retriever.vector_store.count_chunks() == 0
