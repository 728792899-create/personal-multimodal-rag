from __future__ import annotations

from app.models.domain import Document
from app.services.document_processor import DocumentProcessor
from app.services.retriever import HybridRetriever


def hydrate_retriever(
    retriever: HybridRetriever,
    processor: DocumentProcessor,
    documents: list[Document],
    *,
    expected_embedding_provider: str = "",
    expected_embedding_model: str = "",
    expected_embedding_dimension: int = 0,
    expected_index_version: str = "",
    on_mismatch=None,
) -> int:
    """Restore document metadata and rebuild only indexes missing from the vector store."""
    retriever.load_documents(documents)
    compatible_documents: list[Document] = []
    for document in documents:
        expected = {
            "embedding_provider": expected_embedding_provider,
            "embedding_model": expected_embedding_model,
            "embedding_dimension": expected_embedding_dimension,
            "index_version": expected_index_version,
        }
        mismatch = {}
        for key, expected_value in expected.items():
            stored_value = document.metadata.get(key)
            if stored_value in {None, "", 0} or expected_value in {None, "", 0}:
                continue
            if str(stored_value) != str(expected_value):
                mismatch[key] = {"stored": stored_value, "expected": expected_value}
        if mismatch:
            retriever.vector_store.delete_by_document_id(document.document_id)
            document.metadata["index_status"] = "needs_rebuild"
            document.metadata["index_mismatch"] = mismatch
            if on_mismatch:
                on_mismatch(document)
            continue
        for key, expected_value in expected.items():
            if expected_value not in {None, "", 0}:
                document.metadata.setdefault(key, expected_value)
        compatible_documents.append(document)

    indexed_document_ids = {
        chunk.document_id for chunk in retriever.vector_store.chunks.values()
    }
    rebuilt = 0
    for document in compatible_documents:
        if document.document_id in indexed_document_ids:
            continue
        retriever.add_document(document, processor.split(document))
        rebuilt += 1
    return rebuilt
