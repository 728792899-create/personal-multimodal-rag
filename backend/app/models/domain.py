from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class DocumentPage(BaseModel):
    page_number: Optional[int] = None
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentElement(BaseModel):
    """Parser-neutral unit used for multimodal indexing and precise citations."""

    element_id: str
    document_id: str
    type: Literal["text", "heading", "image", "table", "equation", "code"]
    order: int = Field(ge=0)
    text: str = ""
    page_number: Optional[int] = None
    bbox: list[float] = Field(default_factory=list)
    heading_path: list[str] = Field(default_factory=list)
    asset_id: Optional[str] = None
    caption: str = ""
    footnotes: list[str] = Field(default_factory=list)
    table: list[list[str]] = Field(default_factory=list)
    latex: str = ""
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Document(BaseModel):
    document_id: str
    file_name: str
    file_path: str
    file_type: Literal["pdf", "docx", "markdown", "text", "image", "audio", "video"]
    title: Optional[str] = None
    created_at: datetime
    pages: list[DocumentPage]
    elements: list[DocumentElement] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.document_id

    @property
    def filename(self) -> str:
        return self.file_name

    @property
    def source_type(self) -> str:
        return self.file_type

    @property
    def text(self) -> str:
        return "\n\n".join(page.text for page in self.pages if page.text.strip())


class Chunk(BaseModel):
    chunk_id: str
    document_id: str
    chunk_index: int
    text: str
    file_name: str
    page_number: Optional[int] = None
    heading_path: list[str] = Field(default_factory=list)
    element_ids: list[str] = Field(default_factory=list)
    modality: str = "text"
    parent_element_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.chunk_id

    @property
    def filename(self) -> str:
        return self.file_name

    @property
    def index(self) -> int:
        return self.chunk_index
