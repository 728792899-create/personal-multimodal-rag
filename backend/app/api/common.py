from __future__ import annotations

from datetime import datetime

from app.config import settings
from app.core.store import processor, registry, retriever
from app.models.domain import Chunk, Document
from app.models.schemas import RetrievalOptions
from app.services.document_quality import (
    assess_document_quality,
    lifecycle_event,
    summarize_document,
)
from app.services.safe_logging import redact_sensitive_text
from app.services.text_utils import tokenize


def retrieval_options(payload: RetrievalOptions) -> dict:
    return {
        "top_k": payload.top_k,
        "candidate_k": payload.candidate_k,
        "search_mode": payload.search_mode,
        "search_profile": payload.search_profile,
        "document_ids": payload.document_ids,
        "knowledge_base_ids": payload.knowledge_base_ids,
        "bm25_weight": payload.bm25_weight,
        "vector_weight": payload.vector_weight,
        "mmr_lambda": payload.mmr_lambda,
        "min_score": payload.min_score,
        "query_rewrite": payload.query_rewrite,
        "rerank_enabled": payload.rerank_enabled,
    }


def friendly_index_error(exc: Exception) -> str:
    message = redact_sensitive_text(exc)
    if "expecting embedding with dimension" in message and "got" in message:
        return (
            "向量维度不匹配：当前 Chroma collection 已存入其他 embedding 维度。"
            "请为不同 embedding 模型配置独立的 CHROMA_PATH/CHROMA_COLLECTION，"
            "或清理旧 collection 后重建索引。原始错误："
            f"{message}"
        )
    return message


def chunks_for_document(document_id: str) -> list[Chunk]:
    return [
        chunk
        for chunk in retriever.vector_store.chunks.values()
        if chunk.document_id == document_id
    ]


def index_document(doc: Document, lifecycle: list[dict] | None = None) -> tuple[Document, list[Chunk]]:
    doc.metadata.setdefault("knowledge_base_id", "default")
    doc.metadata["chunker_version"] = settings.chunker_version
    doc.metadata["embedding_provider"] = settings.embedding_provider
    doc.metadata["embedding_model"] = settings.embedding_model
    doc.metadata["embedding_dimension"] = settings.resolved_embedding_dimension()
    doc.metadata["index_version"] = settings.index_version
    doc.metadata["index_status"] = "indexing"
    split_started = datetime.utcnow()
    chunks = processor.split(doc)
    split_ended = datetime.utcnow()
    index_started = datetime.utcnow()
    retriever.add_document(doc, chunks)
    index_ended = datetime.utcnow()
    doc.metadata["index_status"] = "indexed"
    doc.metadata["lifecycle"] = [
        *(lifecycle or []),
        lifecycle_event("chunk", "success", split_started, split_ended),
        lifecycle_event("index", "success", index_started, index_ended),
    ]
    doc.metadata["quality"] = assess_document_quality(doc, chunks)
    doc.metadata["summary"] = summarize_document(doc, chunks)
    registry.save_document(doc)
    return doc, chunks


def document_summary(doc: Document, chunks: list[Chunk]) -> dict:
    metadata = dict(doc.metadata)
    quality = metadata.get("quality")
    if not isinstance(quality, dict):
        quality = assess_document_quality(doc, chunks)
    summary = metadata.get("summary")
    if not isinstance(summary, dict):
        summary = summarize_document(doc, chunks)
    lifecycle = metadata.get("lifecycle")
    if not isinstance(lifecycle, list):
        lifecycle = []
    metadata["quality"] = quality
    metadata["summary"] = summary
    metadata["lifecycle"] = lifecycle
    return {
        "id": doc.id,
        "filename": doc.filename,
        "source_type": doc.source_type,
        "chunk_count": len(chunks),
        "char_count": len(doc.text),
        "metadata": metadata,
        "quality": quality,
        "summary": summary,
        "lifecycle": lifecycle,
    }


def chunk_payload(chunk: Chunk) -> dict:
    return {
        "id": chunk.id,
        "document_id": chunk.document_id,
        "filename": chunk.filename,
        "index": chunk.index,
        "text": chunk.text,
        "page_number": chunk.page_number,
        "heading_path": chunk.heading_path,
        "metadata": chunk.metadata,
    }


def feedback_eval_case(payload: dict) -> dict | None:
    if payload.get("rating") != "down":
        return None
    expected_answer = str(payload.get("expected_answer") or "")
    citations = payload.get("citations") or []
    expected_keywords = tokenize(expected_answer)[:8]
    if not expected_keywords:
        for citation in citations[:3]:
            expected_keywords.extend(citation.get("matched_terms") or [])
    expected_keywords = list(dict.fromkeys(expected_keywords))[:8]
    return {
        "question": payload.get("question", ""),
        "expected_answer": expected_answer,
        "expected_keywords": expected_keywords,
        "bad_answer": payload.get("answer", ""),
        "failure_type": payload.get("failure_type") or "bad_answer",
        "user_feedback": payload.get("feedback_text", ""),
        "citations": citations[:5],
        "status": "draft",
    }
