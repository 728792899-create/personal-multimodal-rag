from __future__ import annotations

from datetime import datetime

from app.models.domain import Chunk, Document, DocumentPage
from app.services.embeddings import MockEmbeddingProvider
from app.services.retriever import HybridRetriever
from app.services.vectorstore import MemoryVectorStore


class RecordingProvider(MockEmbeddingProvider):
    def __init__(self):
        super().__init__(vector_dim=8)
        self.batch_lengths: list[int] = []

    def embed_batch(self, texts):
        self.batch_lengths.append(len(texts))
        return super().embed_batch(texts)


def test_document_embeddings_are_bounded_into_provider_batches():
    provider = RecordingProvider()
    store = MemoryVectorStore()
    retriever = HybridRetriever(
        embedding_provider=provider,
        vector_store=store,
        embedding_batch_size=2,
    )
    document = Document(
        document_id="doc",
        file_name="doc.md",
        file_path="/tmp/doc.md",
        file_type="markdown",
        title="Document",
        created_at=datetime(2026, 7, 23),
        pages=[DocumentPage(page_number=1, text="evidence")],
    )
    chunks = [
        Chunk(
            chunk_id=f"doc:{index}",
            document_id="doc",
            chunk_index=index,
            text=f"evidence {index}",
            file_name="doc.md",
        )
        for index in range(5)
    ]

    retriever.add_document(document, chunks)

    assert provider.batch_lengths == [2, 2, 1]
    assert len(store.chunks) == 5
