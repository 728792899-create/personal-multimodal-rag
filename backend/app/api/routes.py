from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.config import settings
from app.core.store import processor, rag_engine, registry, retriever
from app.models.domain import Chunk, Document
from app.models.schemas import (
    AskRequest,
    EvaluationRequest,
    EvaluationDraftRequest,
    FeedbackRequest,
    KnowledgeCardRequest,
    RetrievalOptions,
    RewriteRequest,
    SearchCompareRequest,
    SearchRequest,
    UrlImportRequest,
)
from app.services.document_quality import (
    assess_document_quality,
    build_knowledge_overview,
    lifecycle_event,
    summarize_document,
)
from app.services.document_processor import SUPPORTED_EXTENSIONS
from app.services.knowledge_tools import (
    analyze_knowledge_gaps,
    build_citation_context,
    build_knowledge_card,
    rewrite_answer,
)
from app.services.system_metrics import build_system_metrics
from app.services.text_utils import tokenize
from app.services.url_importer import fetch_url

router = APIRouter()

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "uploads"
DATA_DIR.mkdir(parents=True, exist_ok=True)


@router.get("/documents")
def list_documents():
    return {
        "documents": [
            _document_summary(doc, _chunks_for_document(doc.document_id))
            for doc in registry.load_documents()
        ]
    }


@router.get("/documents/{document_id}")
def get_document(document_id: str):
    doc = registry.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    chunks = _chunks_for_document(document_id)
    chunks = sorted(chunks, key=lambda item: item.chunk_index)
    document_payload = _document_summary(doc, chunks)
    return {
        "document": {
            **document_payload,
            "title": doc.title,
            "created_at": doc.created_at.isoformat(),
            "page_count": len(doc.pages),
            "pages": [
                {
                    "page_number": page.page_number,
                    "text": page.text,
                    "metadata": page.metadata,
                }
                for page in doc.pages
            ],
        },
        "chunks": [_chunk_payload(chunk) for chunk in chunks],
    }


@router.post("/documents")
async def upload_document(file: UploadFile = File(...)):
    target: Path | None = None
    keep_target = False
    safe_name = ""
    try:
        safe_name = _safe_upload_name(file.filename)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        target = DATA_DIR / f"{uuid.uuid4().hex}-{safe_name}"
        upload_started = datetime.utcnow()
        with target.open("wb") as f:
            written = 0
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File is too large; max {settings.max_upload_bytes} bytes",
                    )
                f.write(chunk)
        upload_ended = datetime.utcnow()
        parse_started = datetime.utcnow()
        doc = processor.parse_file(target, original_name=safe_name)
        parse_ended = datetime.utcnow()
        existing = registry.find_by_content_hash(doc.metadata.get("content_hash", ""))
        if existing:
            chunks = _chunks_for_document(existing.document_id)
            registry.log_operation(
                "document_deduped",
                f"重复文档已复用：{existing.file_name}",
                {
                    "document_id": existing.document_id,
                    "filename": existing.file_name,
                    "incoming_filename": safe_name,
                },
            )
            return {
                "deduped": True,
                "document": _document_summary(existing, chunks),
                "chunks": [_chunk_payload(chunk) for chunk in sorted(chunks, key=lambda item: item.index)[:5]],
            }
        doc, chunks = _index_document(
            doc,
            [
                lifecycle_event("upload", "success", upload_started, upload_ended),
                lifecycle_event("parse", "success", parse_started, parse_ended),
            ],
        )
        keep_target = True
        registry.log_operation(
            "document_uploaded",
            f"上传并索引文档：{doc.file_name}",
            {
                "document_id": doc.document_id,
                "filename": doc.file_name,
                "chunk_count": len(chunks),
                "quality_score": doc.metadata["quality"]["score"],
            },
        )
        return {
            "deduped": False,
            "document": _document_summary(doc, chunks),
            "chunks": [_chunk_payload(chunk) for chunk in chunks[:5]],
        }
    except HTTPException as exc:
        registry.log_operation(
            "document_upload_rejected",
            f"文档上传被拒绝：{safe_name or '未命名文件'}",
            {"filename": safe_name, "error": str(exc.detail), "status_code": exc.status_code},
            level="warning",
        )
        raise
    except ValueError as exc:
        registry.log_operation(
            "document_upload_failed",
            f"文档上传或索引失败：{safe_name or '未命名文件'}",
            {"filename": safe_name, "error": _friendly_index_error(exc)},
            level="error",
        )
        raise HTTPException(status_code=400, detail=_friendly_index_error(exc)) from exc
    finally:
        if target is not None and not keep_target:
            target.unlink(missing_ok=True)
        await file.close()


def _safe_upload_name(filename: str | None) -> str:
    normalized = (filename or "").strip().replace("\\", "/")
    safe_name = Path(normalized).name
    if not safe_name or safe_name in {".", ".."} or "\x00" in safe_name:
        raise HTTPException(status_code=400, detail="A valid filename is required")
    suffix = Path(safe_name).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix or '(none)'}; allowed: {supported}")
    return safe_name


@router.post("/imports/url")
def import_url(payload: UrlImportRequest):
    try:
        fetch_started = datetime.utcnow()
        imported = fetch_url(payload.url, title=payload.title)
        fetch_ended = datetime.utcnow()
        parse_started = datetime.utcnow()
        doc = processor.parse_text_source(
            imported.text,
            imported.filename,
            source_url=imported.url,
            parser=imported.metadata.get("parser", "url_html"),
            metadata=imported.metadata,
        )
        doc.title = imported.title
        parse_ended = datetime.utcnow()
        existing = registry.find_by_content_hash(doc.metadata.get("content_hash", ""))
        if existing:
            chunks = _chunks_for_document(existing.document_id)
            registry.log_operation(
                "url_deduped",
                f"URL 已存在：{imported.url}",
                {"document_id": existing.document_id, "url": imported.url},
            )
            return {
                "deduped": True,
                "document": _document_summary(existing, chunks),
                "chunks": [_chunk_payload(chunk) for chunk in sorted(chunks, key=lambda item: item.index)[:5]],
            }
        doc, chunks = _index_document(
            doc,
            [
                lifecycle_event("fetch_url", "success", fetch_started, fetch_ended),
                lifecycle_event("parse", "success", parse_started, parse_ended),
            ],
        )
        registry.log_operation(
            "url_imported",
            f"导入 URL：{imported.title}",
            {
                "document_id": doc.document_id,
                "url": imported.url,
                "chunk_count": len(chunks),
                "quality_score": doc.metadata["quality"]["score"],
            },
        )
        return {
            "deduped": False,
            "document": _document_summary(doc, chunks),
            "chunks": [_chunk_payload(chunk) for chunk in chunks[:5]],
        }
    except Exception as exc:
        registry.log_operation(
            "url_import_failed",
            f"URL 导入失败：{payload.url}",
            {"url": payload.url, "error": str(exc)},
            level="error",
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/knowledge/overview")
def knowledge_overview():
    documents = registry.load_documents()
    chunks_by_document = {
        doc.document_id: _chunks_for_document(doc.document_id)
        for doc in documents
    }
    return build_knowledge_overview(documents, chunks_by_document, registry.list_history(limit=20))


@router.get("/search")
def search(q: str, top_k: int = 5, search_mode: str = "hybrid"):
    return rag_engine.search(q, top_k=top_k, search_mode=search_mode)


@router.get("/chunks/{chunk_id:path}/context")
def chunk_context(chunk_id: str, window: int = 1):
    result = build_citation_context(list(retriever.vector_store.chunks.values()), chunk_id, window=max(0, min(window, 3)))
    if not result.get("found"):
        raise HTTPException(status_code=404, detail="Chunk not found")
    return result


@router.post("/search")
def advanced_search(payload: SearchRequest):
    return rag_engine.search(
        payload.query,
        **_retrieval_options(payload),
    )


@router.post("/search/compare")
def compare_search(payload: SearchCompareRequest):
    return rag_engine.compare(
        payload.query,
        **_retrieval_options(payload),
    )


@router.delete("/documents/{document_id}")
def delete_document(document_id: str):
    doc = registry.get_document(document_id)
    deleted = retriever.delete_document(document_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
    registry.delete_document(document_id)
    source_deleted = _delete_uploaded_source(doc)
    registry.log_operation(
        "document_deleted",
        f"删除文档：{doc.file_name if doc else document_id}",
        {
            "document_id": document_id,
            "filename": doc.file_name if doc else "",
            "source_deleted": source_deleted,
        },
        level="warning",
    )
    return {"deleted": True, "document_id": document_id}


def _delete_uploaded_source(doc: Document | None) -> bool:
    if not doc or not doc.file_path:
        return False
    source = Path(doc.file_path).resolve()
    upload_root = DATA_DIR.resolve()
    if source.parent != upload_root or not source.is_file():
        return False
    source.unlink()
    return True


@router.post("/documents/{document_id}/rebuild")
def rebuild_document(document_id: str):
    doc = registry.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        registry.update_document_status(document_id, "indexing")
        retriever.delete_document(document_id)
        source_path = Path(doc.file_path)
        if source_path.exists():
            doc = processor.parse_file(source_path, original_name=doc.file_name)
            doc.document_id = document_id
        doc.metadata["index_status"] = "indexing"
        split_started = datetime.utcnow()
        chunks = processor.split(doc)
        split_ended = datetime.utcnow()
        index_started = datetime.utcnow()
        retriever.add_document(doc, chunks)
        index_ended = datetime.utcnow()
        doc.metadata["index_status"] = "indexed"
        doc.metadata["lifecycle"] = [
            lifecycle_event("chunk", "success", split_started, split_ended),
            lifecycle_event("index", "success", index_started, index_ended),
        ]
        doc.metadata["quality"] = assess_document_quality(doc, chunks)
        doc.metadata["summary"] = summarize_document(doc, chunks)
        registry.save_document(doc)
        registry.log_operation(
            "document_rebuilt",
            f"重建索引：{doc.file_name}",
            {
                "document_id": document_id,
                "filename": doc.file_name,
                "chunk_count": len(chunks),
                "quality_score": doc.metadata["quality"]["score"],
            },
        )
        return {
            "rebuilt": True,
            "document_id": document_id,
            "chunk_count": len(chunks),
            "metadata": doc.metadata,
        }
    except Exception as exc:
        message = _friendly_index_error(exc)
        registry.update_document_status(document_id, "failed", message)
        registry.log_operation(
            "document_rebuild_failed",
            f"重建索引失败：{doc.file_name}",
            {"document_id": document_id, "filename": doc.file_name, "error": message},
            level="error",
        )
        raise HTTPException(status_code=500, detail=f"Failed to rebuild document: {message}") from exc


@router.post("/documents/rebuild-all")
def rebuild_all_documents():
    results = []
    for doc in registry.load_documents():
        try:
            registry.update_document_status(doc.document_id, "indexing")
            retriever.delete_document(doc.document_id)
            source_path = Path(doc.file_path)
            rebuilt_doc = doc
            if source_path.exists():
                rebuilt_doc = processor.parse_file(source_path, original_name=doc.file_name)
                rebuilt_doc.document_id = doc.document_id
            rebuilt_doc.metadata["index_status"] = "indexing"
            split_started = datetime.utcnow()
            chunks = processor.split(rebuilt_doc)
            split_ended = datetime.utcnow()
            index_started = datetime.utcnow()
            retriever.add_document(rebuilt_doc, chunks)
            index_ended = datetime.utcnow()
            rebuilt_doc.metadata["index_status"] = "indexed"
            rebuilt_doc.metadata["lifecycle"] = [
                lifecycle_event("chunk", "success", split_started, split_ended),
                lifecycle_event("index", "success", index_started, index_ended),
            ]
            rebuilt_doc.metadata["quality"] = assess_document_quality(rebuilt_doc, chunks)
            rebuilt_doc.metadata["summary"] = summarize_document(rebuilt_doc, chunks)
            registry.save_document(rebuilt_doc)
            results.append(
                {
                    "document_id": doc.document_id,
                    "filename": doc.file_name,
                    "status": "indexed",
                    "chunk_count": len(chunks),
                }
            )
        except Exception as exc:
            message = _friendly_index_error(exc)
            registry.update_document_status(doc.document_id, "failed", message)
            results.append(
                {
                    "document_id": doc.document_id,
                    "filename": doc.file_name,
                    "status": "failed",
                    "error": message,
                }
            )
    return {"rebuilt": True, "results": results}


@router.post("/ask")
def ask(payload: AskRequest):
    response = rag_engine.ask(
        payload.question,
        **_retrieval_options(payload),
    )
    response["gap_report"] = analyze_knowledge_gaps(
        payload.question,
        response.get("answer", ""),
        response.get("citations", []),
        registry.load_documents(),
        registry.list_feedback(limit=100),
    )
    history = registry.save_history(payload.question, response)
    response["history_id"] = history["id"]
    response["created_at"] = history["created_at"]
    registry.log_operation(
        "ask",
        f"完成问答：{payload.question[:40]}",
        {
            "history_id": history["id"],
            "confidence": response.get("confidence"),
            "trust": response.get("trust", {}).get("label"),
            "citation_count": len(response.get("citations", [])),
        },
    )
    return response


@router.get("/history")
def list_history(limit: int = 30):
    return {"history": registry.list_history(limit=limit)}


@router.delete("/history")
def clear_history():
    registry.clear_history()
    registry.log_operation("history_cleared", "清空问答历史", {}, level="warning")
    return {"deleted": True}


@router.post("/evaluate")
def evaluate(payload: EvaluationRequest):
    results = rag_engine.evaluate([case.model_dump() for case in payload.cases])
    registry.log_operation(
        "evaluation_run",
        f"运行评测：{len(payload.cases)} 条 case",
        {"case_count": len(payload.cases)},
    )
    return {"results": results}


@router.post("/eval/cases")
def create_eval_case(payload: EvaluationDraftRequest):
    case = registry.save_eval_case(
        {
            "question": payload.question,
            "expected_keywords": payload.expected_keywords,
            "expected_answer": payload.expected_answer,
            "note": payload.note,
            "status": "draft",
        }
    )
    registry.log_operation("eval_case_created", f"新增评测 case：{payload.question[:40]}", {"case_id": case["id"]})
    return {"case": case}


@router.post("/feedback")
def save_feedback(payload: FeedbackRequest):
    feedback_payload = payload.model_dump()
    if payload.history_id:
        history = registry.get_history(payload.history_id)
        if history:
            feedback_payload["history_snapshot"] = history
    eval_case = _feedback_eval_case(feedback_payload)
    if eval_case:
        feedback_payload["eval_case"] = eval_case
    saved = registry.save_feedback(feedback_payload)
    registry.log_operation(
        "feedback_saved",
        f"保存用户反馈：{payload.rating}",
        {
            "feedback_id": saved["id"],
            "history_id": payload.history_id,
            "rating": payload.rating,
            "failure_type": payload.failure_type,
        },
        level="warning" if payload.rating == "down" else "info",
    )
    return {"feedback": saved, "eval_case": eval_case, "stats": registry.feedback_stats()}


@router.get("/feedback")
def list_feedback(limit: int = 50):
    return {"feedback": registry.list_feedback(limit=limit), "stats": registry.feedback_stats()}


@router.get("/eval/drafts")
def list_eval_drafts(limit: int = 50):
    drafts = [
        item.get("eval_case")
        for item in registry.list_feedback(limit=limit)
        if isinstance(item.get("eval_case"), dict)
    ]
    return {"drafts": [*registry.list_eval_cases(limit=limit), *drafts]}


@router.post("/eval/run-drafts")
def run_eval_drafts(limit: int = 30):
    drafts = [
        item
        for item in registry.list_eval_cases(limit=limit)
        if item.get("question")
    ]
    feedback_drafts = [
        item.get("eval_case")
        for item in registry.list_feedback(limit=limit)
        if isinstance(item.get("eval_case"), dict)
    ]
    cases = [
        {
            "question": item.get("question", ""),
            "expected_keywords": item.get("expected_keywords", []),
        }
        for item in [*drafts, *feedback_drafts]
        if item.get("question")
    ]
    results = rag_engine.evaluate(cases) if cases else []
    registry.log_operation("eval_drafts_run", f"运行评测草稿：{len(cases)} 条", {"case_count": len(cases)})
    return {"case_count": len(cases), "results": results}


@router.post("/answer/rewrite")
def rewrite(payload: RewriteRequest):
    result = rewrite_answer(
        payload.answer,
        payload.style,
        question=payload.question,
        citations=[item.model_dump() for item in payload.citations],
    )
    registry.log_operation(
        "answer_rewritten",
        f"答案改写：{result['label']}",
        {"style": payload.style, "question": payload.question[:80]},
    )
    return result


@router.post("/knowledge/cards")
def create_knowledge_card(payload: KnowledgeCardRequest):
    card = build_knowledge_card(
        payload.question,
        payload.answer,
        [item.model_dump() for item in payload.citations],
        tags=payload.tags,
    )
    saved = registry.save_knowledge_card(card)
    registry.log_operation(
        "knowledge_card_created",
        f"保存知识卡片：{saved['title']}",
        {"card_id": saved["id"], "source_documents": saved.get("source_documents", [])},
    )
    return {"card": saved}


@router.get("/knowledge/cards")
def list_knowledge_cards(limit: int = 50):
    return {"cards": registry.list_knowledge_cards(limit=limit)}


@router.delete("/knowledge/cards/{card_id}")
def delete_knowledge_card(card_id: str):
    deleted = registry.delete_knowledge_card(card_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Card not found")
    registry.log_operation("knowledge_card_deleted", f"删除知识卡片：{card_id}", {"card_id": card_id}, level="warning")
    return {"deleted": True, "card_id": card_id}


@router.post("/knowledge/gaps")
def knowledge_gaps(payload: SearchRequest):
    search_result = rag_engine.search(payload.query, **_retrieval_options(payload))
    gap_report = analyze_knowledge_gaps(
        payload.query,
        "",
        search_result["results"],
        registry.load_documents(),
        registry.list_feedback(limit=100),
    )
    registry.log_operation(
        "gap_analysis_run",
        f"资料缺口分析：{payload.query[:40]}",
        {"missing_count": len(gap_report.get("missing_topics", []))},
    )
    return {
        "query": payload.query,
        "search": search_result,
        "gap_report": gap_report,
    }


@router.get("/operations")
def list_operations(limit: int = 40):
    return {"operations": registry.list_operations(limit=limit)}


@router.get("/metrics")
def system_metrics():
    documents = registry.load_documents()
    chunk_count = len(retriever.vector_store.chunks)
    return build_system_metrics(
        documents=documents,
        history=registry.list_history(limit=200),
        feedback_stats=registry.feedback_stats(),
        operations=registry.list_operations(limit=200),
        chunk_count=chunk_count,
    )


def _retrieval_options(payload: RetrievalOptions) -> dict:
    return {
        "top_k": payload.top_k,
        "candidate_k": payload.candidate_k,
        "search_mode": payload.search_mode,
        "search_profile": payload.search_profile,
        "document_ids": payload.document_ids,
        "bm25_weight": payload.bm25_weight,
        "vector_weight": payload.vector_weight,
        "mmr_lambda": payload.mmr_lambda,
        "min_score": payload.min_score,
        "query_rewrite": payload.query_rewrite,
        "rerank_enabled": payload.rerank_enabled,
    }


def _friendly_index_error(exc: Exception) -> str:
    message = str(exc)
    if "expecting embedding with dimension" in message and "got" in message:
        return (
            "向量维度不匹配：当前 Chroma collection 已存入其他 embedding 维度。"
            "请为不同 embedding 模型配置独立的 CHROMA_PATH/CHROMA_COLLECTION，"
            "或清理旧 collection 后重建索引。原始错误："
            f"{message}"
        )
    return message


def _chunks_for_document(document_id: str) -> list[Chunk]:
    return [
        chunk
        for chunk in retriever.vector_store.chunks.values()
        if chunk.document_id == document_id
    ]


def _index_document(doc: Document, lifecycle: list[dict] | None = None) -> tuple[Document, list[Chunk]]:
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


def _document_summary(doc: Document, chunks: list[Chunk]) -> dict:
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


def _chunk_payload(chunk: Chunk) -> dict:
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


def _feedback_eval_case(payload: dict) -> dict | None:
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
