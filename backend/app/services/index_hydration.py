from __future__ import annotations

from app.models.domain import Document
from app.services.document_processor import DocumentProcessor
from app.services.retriever import HybridRetriever


def hydrate_retriever(
    retriever: HybridRetriever,
    processor: DocumentProcessor,
    documents: list[Document],
) -> int:
    """Restore document metadata and rebuild only indexes missing from the vector store."""
    retriever.load_documents(documents)
    indexed_document_ids = {
        chunk.document_id for chunk in retriever.vector_store.chunks.values()
    }
    rebuilt = 0
    for document in documents:
        if document.document_id in indexed_document_ids:
            continue
        retriever.add_document(document, processor.split(document))
        rebuilt += 1
    return rebuilt
