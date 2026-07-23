from typing import Literal, Optional

from pydantic import BaseModel, Field


class DocumentMeta(BaseModel):
    id: str
    filename: str
    source_type: str
    chunk_count: int
    char_count: int
    element_count: int = 0
    modality_counts: dict[str, int] = Field(default_factory=dict)
    source_available: bool = False
    metadata: dict = Field(default_factory=dict)


class ChunkOut(BaseModel):
    id: str
    document_id: str
    filename: str
    index: int
    text: str
    page_number: Optional[int] = None
    heading_path: list[str] = Field(default_factory=list)
    element_ids: list[str] = Field(default_factory=list)
    modality: str = "text"
    parent_element_id: Optional[str] = None
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
    strategy: Literal["hybrid", "hybrid_graph", "auto"] = "hybrid"
    document_ids: list[str] = Field(default_factory=list)
    knowledge_base_ids: list[str] = Field(default_factory=list)
    bm25_weight: Optional[float] = Field(None, ge=0, le=1)
    vector_weight: Optional[float] = Field(None, ge=0, le=1)
    mmr_lambda: Optional[float] = Field(None, ge=0, le=1)
    min_score: Optional[float] = Field(None, ge=0, le=1)
    query_rewrite: bool = True
    rerank_enabled: bool = True
    graph_weight: float = Field(0.25, ge=0, le=1)
    graph_max_hops: int = Field(2, ge=1, le=4)
    modality_filters: list[Literal["text", "heading", "image", "table", "equation", "code", "mixed"]] = Field(default_factory=list)
    parent_window: int = Field(1, ge=0, le=3)


class QueryAttachmentRef(BaseModel):
    id: str = Field(..., min_length=1, max_length=80)
    detail: Literal["low", "high", "original", "auto"] = "auto"


class AskRequest(RetrievalOptions):
    question: str = Field(..., min_length=1, max_length=4000)
    attachments: list[QueryAttachmentRef] = Field(default_factory=list, max_length=4)


class SearchRequest(RetrievalOptions):
    query: str = Field(..., min_length=1, max_length=4000)


class SearchCompareRequest(RetrievalOptions):
    query: str = Field(..., min_length=1, max_length=4000)


class UrlImportRequest(BaseModel):
    url: str = Field(..., min_length=8, max_length=2048)
    title: str = Field("", max_length=200)
    knowledge_base_id: str = Field("default", min_length=1, max_length=80)
    parser_profile: Literal["builtin", "auto", "mineru", "docling", "paddleocr"] = "builtin"
    enrich_modalities: bool = True
    build_graph: bool = True


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field("", max_length=500)


class KnowledgeBaseUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: Optional[str] = Field(None, max_length=500)


class IngestionUrlRequest(UrlImportRequest):
    pass


class ConversationCreate(BaseModel):
    title: str = Field("新会话", max_length=160)
    knowledge_base_ids: list[str] = Field(default_factory=lambda: ["default"])


class ConversationUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=160)
    knowledge_base_ids: Optional[list[str]] = None


class ConversationMessageRequest(RetrievalOptions):
    question: str = Field(..., min_length=1, max_length=4000)
    attachments: list[QueryAttachmentRef] = Field(default_factory=list, max_length=4)


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


class WorkspaceContext(BaseModel):
    workspace_id: str
    user_id: str
    role: Literal["owner", "member"] = "owner"


class StorageStatus(BaseModel):
    provider: str
    configured: bool
    healthy: bool


class QueueStatus(BaseModel):
    provider: str
    configured: bool
    healthy: bool
    depth: int = 0
    dead_letters: int = 0


class ReleaseGate(BaseModel):
    id: str
    label: str
    passed: bool
    observed: bool | int | float | str
    required: bool | int | float | str


class ReleaseReadiness(BaseModel):
    target_version: str
    candidate_version: str
    ready: bool
    status: Literal["ready", "blocked"]
    passed_gates: int
    total_gates: int
    gates: list[ReleaseGate]
    errors: list[str] = Field(default_factory=list)
    evidence_updated_at: str = ""
    production_ready_claim: bool = False


class DeadLetterJob(BaseModel):
    id: str
    job_id: str
    error_code: str = ""
    error_message: str = ""
    created_at: str
