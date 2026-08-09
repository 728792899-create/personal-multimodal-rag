from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request

from app.api.common import chunks_for_document, feedback_eval_case, retrieval_options
from app.core.store import rag_engine, registry, retriever
from app.models.schemas import (
    EvaluationDraftRequest,
    EvaluationDraftBatchRequest,
    EvaluationRequest,
    EvaluationReviewRequest,
    FeedbackRequest,
    KnowledgeCardRequest,
    RewriteRequest,
    SearchRequest,
)
from app.services.document_quality import build_knowledge_overview
from app.services.knowledge_tools import analyze_knowledge_gaps, build_knowledge_card, rewrite_answer
from app.services.system_metrics import build_system_metrics


router = APIRouter(tags=["quality"])


def _feedback_scope(request: Request) -> tuple[str, str, str]:
    identity = request.scope.get("state", {}).get("identity")
    if identity is None:
        return "owner", "default", "owner"
    return identity.user_id, identity.workspace_id, identity.role


@router.get("/knowledge/overview")
def knowledge_overview(request: Request):
    documents = registry.load_documents()
    chunks_by_document = {doc.document_id: chunks_for_document(doc.document_id) for doc in documents}
    _, _, role = _feedback_scope(request)
    history = (
        registry.list_history(limit=20)
        if role in {"admin", "owner"}
        else []
    )
    return build_knowledge_overview(documents, chunks_by_document, history)


@router.post("/evaluate")
def evaluate(payload: EvaluationRequest):
    results = rag_engine.evaluate([case.model_dump() for case in payload.cases])
    registry.log_operation("evaluation_run", f"运行评测：{len(payload.cases)} 条用例", {"case_count": len(payload.cases)})
    return {"results": results}


@router.post("/eval/cases")
def create_eval_case(payload: EvaluationDraftRequest):
    if payload.candidate_id:
        existing = next(
            (
                item
                for item in registry.list_eval_cases(limit=10_000)
                if item.get("candidate_id") == payload.candidate_id
            ),
            None,
        )
        if existing:
            return {"case": existing, "deduped": True}
    case = registry.save_eval_case(
        {
            "question": payload.question,
            "expected_keywords": payload.expected_keywords,
            "expected_answer": payload.expected_answer,
            "note": payload.note,
            "candidate_id": payload.candidate_id,
            "source_ref": payload.source_ref,
            "status": "draft",
        }
    )
    registry.log_operation("eval_case_created", f"新增评测用例：{payload.question[:40]}", {"case_id": case["id"]})
    return {"case": case, "deduped": False}


@router.post("/eval/cases:batch")
def create_eval_case_batch(payload: EvaluationDraftBatchRequest):
    existing = {
        str(item.get("candidate_id") or ""): item
        for item in registry.list_eval_cases(limit=10_000)
        if item.get("candidate_id")
    }
    cases: list[dict] = []
    created = deduped = 0
    for candidate in payload.cases:
        if candidate.candidate_id and candidate.candidate_id in existing:
            cases.append(existing[candidate.candidate_id])
            deduped += 1
            continue
        case = registry.save_eval_case(
            {
                **candidate.model_dump(),
                "status": "draft",
            }
        )
        cases.append(case)
        created += 1
        if candidate.candidate_id:
            existing[candidate.candidate_id] = case
    registry.log_operation(
        "eval_case_batch_created",
        f"批量准备评测候选：新增 {created}，已存在 {deduped}",
        {"created": created, "deduped": deduped},
    )
    return {
        "cases": cases,
        "created": created,
        "deduped": deduped,
        "summary": registry.eval_review_summary(),
    }


@router.patch("/eval/cases/{case_id}")
def review_eval_case(case_id: str, payload: EvaluationReviewRequest):
    if payload.answerable and not (
        payload.expected_answer.strip() or payload.expected_keywords
    ):
        raise HTTPException(
            status_code=422,
            detail="可回答样本必须填写期望答案或期望关键词。",
        )
    reviewed = registry.update_eval_case(
        case_id,
        {
            **payload.model_dump(),
            "status": "reviewed",
            "reviewed_at": datetime.utcnow().isoformat(timespec="microseconds"),
        },
    )
    if not reviewed:
        raise HTTPException(status_code=404, detail="评测样本不存在或已被删除。")
    registry.log_operation(
        "eval_case_human_reviewed",
        "评测用例已完成人工复核",
        {"case_id": case_id, "answerable": payload.answerable},
    )
    return {"case": reviewed, "summary": registry.eval_review_summary()}


@router.get("/eval/review-summary")
def eval_review_summary():
    return registry.eval_review_summary()


@router.post("/feedback")
def save_feedback(payload: FeedbackRequest, request: Request):
    user_id, workspace_id, _ = _feedback_scope(request)
    feedback_payload = payload.model_dump()
    if payload.history_id:
        history = registry.get_history(
            payload.history_id,
            user_id=user_id,
            workspace_id=workspace_id,
        )
        if not history:
            raise HTTPException(status_code=404, detail="问答记录不存在或不属于当前账号。")
        feedback_payload["history_snapshot"] = history
    eval_case = feedback_eval_case(feedback_payload)
    if eval_case:
        feedback_payload["eval_case"] = eval_case
    saved = registry.save_feedback(
        feedback_payload,
        user_id=user_id,
        workspace_id=workspace_id,
    )
    registry.log_operation(
        "feedback_saved",
        f"保存用户反馈：{payload.rating}",
        {"feedback_id": saved["id"], "history_id": payload.history_id, "rating": payload.rating, "failure_type": payload.failure_type},
        level="warning" if payload.rating == "down" else "info",
    )
    return {
        "feedback": saved,
        "eval_case": eval_case,
        "stats": registry.feedback_stats(
            user_id=user_id, workspace_id=workspace_id
        ),
    }


@router.get("/feedback")
def list_feedback(request: Request, limit: int = 50):
    user_id, workspace_id, role = _feedback_scope(request)
    scope = {} if role in {"admin", "owner"} else {
        "user_id": user_id,
        "workspace_id": workspace_id,
    }
    return {
        "feedback": registry.list_feedback(limit=limit, **scope),
        "stats": registry.feedback_stats(**scope),
    }


@router.get("/eval/drafts")
def list_eval_drafts(limit: int = 50):
    drafts = [item.get("eval_case") for item in registry.list_feedback(limit=limit) if isinstance(item.get("eval_case"), dict)]
    return {"drafts": [*registry.list_eval_cases(limit=limit), *drafts]}


@router.post("/eval/run-drafts")
def run_eval_drafts(limit: int = 30):
    drafts = [item for item in registry.list_eval_cases(limit=limit) if item.get("question")]
    feedback_drafts = [item.get("eval_case") for item in registry.list_feedback(limit=limit) if isinstance(item.get("eval_case"), dict)]
    cases = [{"question": item.get("question", ""), "expected_keywords": item.get("expected_keywords", [])} for item in [*drafts, *feedback_drafts] if item.get("question")]
    results = rag_engine.evaluate(cases) if cases else []
    registry.log_operation("eval_drafts_run", f"运行评测草稿：{len(cases)} 条", {"case_count": len(cases)})
    return {"case_count": len(cases), "results": results}


@router.post("/answer/rewrite")
def rewrite(payload: RewriteRequest):
    result = rewrite_answer(payload.answer, payload.style, question=payload.question, citations=[item.model_dump() for item in payload.citations])
    registry.log_operation("answer_rewritten", f"答案改写：{result['label']}", {"style": payload.style, "question": payload.question[:80]})
    return result


@router.post("/knowledge/cards")
def create_knowledge_card(payload: KnowledgeCardRequest):
    card = build_knowledge_card(payload.question, payload.answer, [item.model_dump() for item in payload.citations], tags=payload.tags)
    saved = registry.save_knowledge_card(card)
    registry.log_operation("knowledge_card_created", f"保存知识卡片：{saved['title']}", {"card_id": saved["id"], "source_documents": saved.get("source_documents", [])})
    return {"card": saved}


@router.get("/knowledge/cards")
def list_knowledge_cards(limit: int = 50):
    return {"cards": registry.list_knowledge_cards(limit=limit)}


@router.delete("/knowledge/cards/{card_id}")
def delete_knowledge_card(card_id: str):
    if not registry.delete_knowledge_card(card_id):
        raise HTTPException(status_code=404, detail="知识卡片不存在或已被删除。")
    registry.log_operation("knowledge_card_deleted", f"删除知识卡片：{card_id}", {"card_id": card_id}, level="warning")
    return {"deleted": True, "card_id": card_id}


@router.post("/knowledge/gaps")
def knowledge_gaps(payload: SearchRequest):
    search_result = rag_engine.search(payload.query, **retrieval_options(payload))
    gap_report = analyze_knowledge_gaps(payload.query, "", search_result["results"], registry.load_documents(), registry.list_feedback(limit=100))
    registry.log_operation("gap_analysis_run", f"资料缺口分析：{payload.query[:40]}", {"missing_count": len(gap_report.get("missing_topics", []))})
    return {"query": payload.query, "search": search_result, "gap_report": gap_report}


@router.get("/operations")
def list_operations(limit: int = 40):
    return {"operations": registry.list_operations(limit=limit)}


@router.get("/metrics")
def system_metrics():
    documents = registry.load_documents()
    return build_system_metrics(
        documents=documents,
        history=registry.list_history(limit=200),
        feedback_stats=registry.feedback_stats(),
        operations=registry.list_operations(limit=200),
        chunk_count=retriever.vector_store.count_chunks(),
        index_jobs=registry.list_index_jobs(limit=200),
        conversation_metrics=registry.conversation_metrics(limit=200),
        conversation_retrieval_traces=registry.conversation_retrieval_traces(
            limit=200
        ),
    )
