from __future__ import annotations

from datetime import datetime

from app.models.domain import Document, DocumentElement, DocumentPage
from app.services.document_processor import DocumentProcessor


def test_structure_chunks_keep_citation_text_separate_from_embedding_text():
    processor = DocumentProcessor()
    document = processor.parse_text_source(
        "# Retrieval\n\n" + "证据段落。" * 80,
        "guide.md",
    )

    chunks = processor.split(document)

    assert chunks
    assert chunks[0].text.startswith("证据段落")
    assert not chunks[0].text.startswith("guide")
    assert "guide" in chunks[0].metadata["embedding_text"]
    assert "Retrieval" in chunks[0].metadata["embedding_text"]
    assert all(len(chunk.text) <= 900 for chunk in chunks)


def test_large_table_is_windowed_and_repeats_header():
    rows = [["name", "value"], *[[f"row-{index}", "x" * 70] for index in range(30)]]
    rendered = "\n".join(" | ".join(row) for row in rows)
    document = Document(
        document_id="table-doc",
        file_name="table.docx",
        file_path="table.docx",
        file_type="docx",
        title="Table",
        created_at=datetime(2026, 8, 9),
        pages=[DocumentPage(text=rendered)],
        elements=[
            DocumentElement(
                element_id="table-doc:element:0",
                document_id="table-doc",
                type="table",
                order=0,
                text=rendered,
                table=rows,
            )
        ],
        metadata={"content_hash": "hash"},
    )

    chunks = DocumentProcessor().split(document)

    assert len(chunks) > 1
    assert all(chunk.text.startswith("name | value") for chunk in chunks)
    assert all(chunk.modality == "table" for chunk in chunks)
    assert all(len(chunk.text) <= 900 for chunk in chunks)
