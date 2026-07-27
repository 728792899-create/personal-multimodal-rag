from pathlib import Path

from PIL import Image

from app.services.document_processor import DocumentProcessor


def test_markdown_parse_and_chunk_metadata(tmp_path: Path):
    file_path = tmp_path / "note.md"
    file_path.write_text("# RAG\n\n## 召回\n\nBM25 和向量检索可以组合使用。", encoding="utf-8")

    processor = DocumentProcessor(chunk_size=80, overlap=10)
    document = processor.parse_file(file_path)
    chunks = processor.split(document)

    assert document.file_type == "markdown"
    assert document.metadata["parser"] == "markdown"
    assert chunks
    assert chunks[0].chunk_index == 0
    assert "RAG" in chunks[0].heading_path


def test_empty_document_is_rejected(tmp_path: Path):
    file_path = tmp_path / "empty.md"
    file_path.write_text("   \n\n", encoding="utf-8")

    processor = DocumentProcessor()

    try:
        processor.parse_file(file_path)
    except ValueError as exc:
        assert "未能从文档中提取可读文本" in str(exc)
    else:
        raise AssertionError("empty document should be rejected")


def test_image_parse_records_ocr_status_when_runtime_missing(tmp_path: Path):
    file_path = tmp_path / "scan.png"
    Image.new("RGB", (160, 80), "white").save(file_path)

    processor = DocumentProcessor()
    document = processor.parse_file(file_path)

    assert document.file_type == "image"
    assert document.metadata["parser"] == "image_ocr"
    assert "ocr_status" in document.metadata
    assert "图片文件" in document.text
    assert document.pages[0].metadata["image_width"] == 160
    assert document.pages[0].metadata["image_height"] == 80
    public_payload = "".join(page.model_dump_json() for page in document.pages)
    public_payload += "".join(element.model_dump_json() for element in document.elements)
    public_payload += str(document.metadata)
    assert str(tmp_path) not in public_payload
