from typing import Literal, Optional

from pydantic import BaseModel, Field


class DocumentMeta(BaseModel):
    id: str
    filename: str
    source_type: str
    chunk_count: int
    char_count: int
    metadata: dict = Field(default_factory=dict)


class ChunkOut(BaseModel):
    id: str
    document_id: str
    filename: str
    index: int
    text: str
    page_number: Optional[int] = None
    heading_path: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    score: float = 0
    bm25_score: float = 0
    vector_score: float = 0
    rerank_score: float = 0
    cross_encoder_score: Optional[float] = None
    matched_terms: list[str] = Field(default_factory=list)
    snippet: str = ""
    score_breakdown: dict = Field(default_factory=dict)
    parent_context: dict = Field(default_factory=dict)


class RetrievalOptions(BaseModel):
    top_k: int = Field(5, ge=1, le=12)
    candidate_k: Optional[int] = Field(None, ge=1, le=80)
    search_mode: Literal["hybrid", "keyword", "semantic"] = "hybrid"
    search_profile: Literal["balanced", "precision", "recall"] = "balanced"
    document_ids: list[str] = Field(default_factory=list)
    bm25_weight: Optional[float] = Field(None, ge=0, le=1)
    vector_weight: Optional[float] = Field(None, ge=0, le=1)
    mmr_lambda: Optional[float] = Field(None, ge=0, le=1)
    min_score: Optional[float] = Field(None, ge=0, le=1)
    query_rewrite: bool = True
    rerank_enabled: bool = True


class AskRequest(RetrievalOptions):
    question: str = Field(..., min_length=1, max_length=4000)


class SearchRequest(RetrievalOptions):
    query: str = Field(..., min_length=1, max_length=4000)


class SearchCompareRequest(RetrievalOptions):
    query: str = Field(..., min_length=1, max_length=4000)


class UrlImportRequest(BaseModel):
    url: str = Field(..., min_length=8, max_length=2048)
    title: str = Field("", max_length=200)


class AskResponse(BaseModel):
    answer: str
    citations: list[ChunkOut]
    retrieval_trace: dict
    generation_trace: dict = Field(default_factory=dict)
    confidence: Optional[float] = None
    trust: dict = Field(default_factory=dict)
    citation_audit: dict = Field(default_factory=dict)


class SearchResponse(BaseModel):
    results: list[ChunkOut]
    trace: dict


class EvaluationCase(BaseModel):
    question: str
    expected_keywords: list[str] = Field(default_factory=list)


class EvaluationRequest(BaseModel):
    cases: list[EvaluationCase]


class EvaluationDraftRequest(BaseModel):
    question: str = Field(..., min_length=1)
    expected_keywords: list[str] = Field(default_factory=list)
    expected_answer: str = ""
    note: str = ""


class EvaluationResult(BaseModel):
    question: str
    hit: bool
    matched_keywords: list[str]
    top_sources: list[str]


class FeedbackRequest(BaseModel):
    history_id: Optional[str] = None
    question: str = Field(..., min_length=1)
    answer: str = ""
    rating: Literal["up", "down"] = "down"
    feedback_text: str = ""
    failure_type: Optional[
        Literal[
            "no_evidence",
            "low_confidence",
            "wrong_citation",
            "unsupported_claim",
            "bad_answer",
            "retrieval_miss",
            "other",
        ]
    ] = None
    expected_answer: str = ""
    citations: list[ChunkOut] = Field(default_factory=list)


class RewriteRequest(BaseModel):
    question: str = ""
    answer: str = Field(..., min_length=1)
    style: Literal["short", "detailed", "briefing", "highlights", "study", "faq"] = "short"
    citations: list[ChunkOut] = Field(default_factory=list)


class KnowledgeCardRequest(BaseModel):
    question: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)
    citations: list[ChunkOut] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
