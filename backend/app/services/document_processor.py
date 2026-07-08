from __future__ import annotations

import re
import uuid
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional

import fitz

from app.models.domain import Chunk, Document, DocumentPage
from app.services.ocr import ImageOCRAdapter


SUPPORTED_EXTENSIONS = {".txt", ".md", ".markdown", ".pdf", ".png", ".jpg", ".jpeg"}


class DocumentProcessor:
    def __init__(self, chunk_size: int = 520, overlap: int = 90, ocr_adapter: ImageOCRAdapter | None = None):
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.ocr_adapter = ocr_adapter or ImageOCRAdapter()

    def parse_file(self, file_path: Path, original_name: Optional[str] = None) -> Document:
        filename = original_name or file_path.name
        suffix = file_path.suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported file type: {suffix}")

        if suffix == ".pdf":
            pages, metadata = self._parse_pdf(file_path)
        elif suffix in {".png", ".jpg", ".jpeg"}:
            pages, metadata = self._parse_image(file_path)
        else:
            pages, metadata = self._parse_text_file(file_path, suffix)

        if not any(page.text.strip() for page in pages):
            raise ValueError("No readable text extracted from document")

        metadata.update(
            {
                "file_size": file_path.stat().st_size,
                "content_hash": self._content_hash(file_path),
                "source_path": str(file_path),
                "parser": metadata.get("parser", "plain_text"),
                "index_status": "parsed",
            }
        )

        return Document(
            document_id=str(uuid.uuid4()),
            file_name=filename,
            file_path=str(file_path),
            file_type=self._file_type(suffix),
            title=Path(filename).stem,
            created_at=datetime.utcnow(),
            pages=pages,
            metadata=metadata,
        )

    def parse_text_source(
        self,
        text: str,
        source_name: str,
        source_url: str = "",
        parser: str = "plain_text",
        metadata: Optional[dict] = None,
    ) -> Document:
        normalized = self.normalize_text(text)
        if not normalized:
            raise ValueError("No readable text extracted from document")
        payload = {
            "parser": parser,
            "index_status": "parsed",
            "source_url": source_url,
            "content_hash": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            **(metadata or {}),
        }
        return Document(
            document_id=str(uuid.uuid4()),
            file_name=source_name,
            file_path=source_url or source_name,
            file_type="text",
            title=Path(source_name).stem,
            created_at=datetime.utcnow(),
            pages=[DocumentPage(page_number=None, text=normalized, metadata={"source_url": source_url})],
            metadata=payload,
        )

    def split(self, doc: Document) -> list[Chunk]:
        paragraphs = self._paragraphs(doc)
        chunks: list[Chunk] = []
        current = ""
        current_meta = {"page_number": None, "heading_path": [], "metadata": {}}

        for paragraph, meta in paragraphs:
            if len(paragraph) > self.chunk_size:
                if current.strip():
                    chunks.append(self._make_chunk(doc, len(chunks), current, current_meta))
                    current = ""
                for part in self._hard_split(paragraph):
                    chunks.append(self._make_chunk(doc, len(chunks), part, meta))
                continue

            candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
            if len(candidate) <= self.chunk_size:
                current = candidate
                current_meta = meta
            else:
                if current.strip():
                    chunks.append(self._make_chunk(doc, len(chunks), current, current_meta))
                current = f"{self._tail(current)}\n\n{paragraph}".strip()
                current_meta = meta

        if current.strip():
            chunks.append(self._make_chunk(doc, len(chunks), current, current_meta))

        return chunks

    def normalize_text(self, text: str) -> str:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _content_hash(self, file_path: Path) -> str:
        digest = hashlib.sha256()
        with file_path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _parse_pdf(self, file_path: Path) -> tuple[list[DocumentPage], dict]:
        pages: list[DocumentPage] = []
        try:
            pdf = fitz.open(str(file_path))
            for index, page in enumerate(pdf, start=1):
                text = self.normalize_text(page.get_text("text"))
                if text:
                    pages.append(
                        DocumentPage(
                            page_number=index,
                            text=text,
                            metadata={"page_index": index - 1},
                        )
                    )
            metadata = {"page_count": pdf.page_count, "parser": "pymupdf"}
            pdf.close()
            return pages, metadata
        except Exception as exc:
            raise ValueError(f"Failed to parse PDF: {exc}") from exc

    def _parse_text_file(self, file_path: Path, suffix: str) -> tuple[list[DocumentPage], dict]:
        text = self.normalize_text(file_path.read_text(encoding="utf-8", errors="ignore"))
        metadata = {"parser": "markdown" if suffix in {".md", ".markdown"} else "plain_text"}
        return [DocumentPage(page_number=None, text=text, metadata={})], metadata

    def _parse_image(self, file_path: Path) -> tuple[list[DocumentPage], dict]:
        result = self.ocr_adapter.extract_text(file_path)
        if result.text:
            text = f"图片文件：{file_path.name}\n\nOCR 提取文本：\n{self.normalize_text(result.text)}"
        else:
            text = (
                f"图片文件：{file_path.name}。\n"
                "当前环境未完成 OCR 文本提取，已记录图片元数据；安装 tesseract + pytesseract 后可自动提取图片文本。"
            )
        page = DocumentPage(
            page_number=None,
            text=text,
            metadata={
                "image_path": str(file_path),
                "ocr_status": result.status,
                "ocr_engine": result.engine,
                "ocr_error": result.error,
            },
        )
        return [page], {"parser": "image_ocr", "ocr_status": result.status, "ocr_engine": result.engine}

    def _paragraphs(self, doc: Document) -> list[tuple[str, dict]]:
        paragraphs: list[tuple[str, dict]] = []
        heading_path: list[str] = []
        for page in doc.pages:
            for part in re.split(r"\n\s*\n", page.text):
                paragraph = part.strip()
                if not paragraph:
                    continue
                heading = re.match(r"^(#{1,6})\s+(.+)$", paragraph)
                if heading:
                    level = len(heading.group(1))
                    heading_path = heading_path[: level - 1] + [heading.group(2).strip()]
                paragraphs.append(
                    (
                        paragraph,
                        {
                            "page_number": page.page_number,
                            "heading_path": list(heading_path),
                            "metadata": dict(page.metadata),
                        },
                    )
                )
        return paragraphs

    def _hard_split(self, text: str) -> list[str]:
        parts = []
        start = 0
        while start < len(text):
            end = start + self.chunk_size
            parts.append(text[start:end])
            if end >= len(text):
                break
            start = max(end - self.overlap, start + 1)
        return parts

    def _tail(self, text: str) -> str:
        if not text:
            return ""
        return text[-self.overlap :]

    def _make_chunk(self, doc: Document, index: int, text: str, meta: dict) -> Chunk:
        return Chunk(
            chunk_id=f"{doc.document_id}:{index}",
            document_id=doc.document_id,
            file_name=doc.file_name,
            chunk_index=index,
            text=text.strip(),
            page_number=meta.get("page_number"),
            heading_path=meta.get("heading_path", []),
            metadata=meta.get("metadata", {}),
        )

    def _file_type(self, suffix: str):
        if suffix == ".pdf":
            return "pdf"
        if suffix in {".md", ".markdown"}:
            return "markdown"
        if suffix in {".png", ".jpg", ".jpeg"}:
            return "image"
        return "text"
