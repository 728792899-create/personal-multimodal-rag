from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class DocumentPage(BaseModel):
    page_number: Optional[int] = None
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class Document(BaseModel):
    document_id: str
    file_name: str
    file_path: str
    file_type: Literal["pdf", "markdown", "text", "image", "audio", "video"]
    title: Optional[str] = None
    created_at: datetime
    pages: list[DocumentPage]
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
