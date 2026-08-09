from __future__ import annotations

import time
from urllib.parse import urlsplit

from app.services.answer_generator import BaseAnswerGenerator, TemplateAnswerGenerator
from app.services.citation_audit import audit_answer
from app.services.embeddings import MockEmbeddingProvider
from app.services.retriever import HybridRetriever
from app.services.safe_logging import public_error_message, redact_private_metadata


LOW_INFORMATION_MATCHES = {
    "api", "app", "store", "系统", "流程", "方式", "功能", "参数", "配置", "应该", "需要",
    "问题", "资料", "文档", "项目", "目的", "规则", "内容", "相关", "什么", "怎么", "如何",
    "多少", "是否", "提供", "哪些", "当前", "自动", "恢复",
}
LOW_INFORMATION_BOUNDARY_CHARS = set("的了是在中和与或对为这那")
EVIDENCE_GAP_MARKERS = (
    "没有提供",
    "未提供",
    "并未提供",
    "没有覆盖",
    "未覆盖",
    "资料不足",
)
AVAILABILITY_QUESTION_MARKERS = (
    "是否",
    "有没有",
    "有无",
    "现有资料",
    "当前资料",
    "知识库是否",
    "是否覆盖",
    "是否提供",
    "覆盖哪些",
    "已经覆盖",
)
ASCII_LOWERCASE = frozenset("abcdefghijklmnopqrstuvwxyz")
ASCII_DIGITS = frozenset("0123456789")
IDENTIFIER_BODY = ASCII_LOWERCASE | ASCII_DIGITS | frozenset("_.-")
DNS_LABEL_CHARACTERS = ASCII_LOWERCASE | ASCII_DIGITS | frozenset("-")
DEEPSEEK_DOMAIN = "deepseek.com"


def _is_legal_dns_hostname(hostname: str) -> bool:
    """Validate the ASCII DNS form used for provider trust decisions."""

    if not hostname or len(hostname) > 253:
        return False
    labels = hostname.split(".")
    return all(
        1 <= len(label) <= 63
        and label[0] != "-"
        and label[-1] != "-"
        and all(character in DNS_LABEL_CHARACTERS for character in label)
        for label in labels
    )


def _is_deepseek_base_url(value: object) -> bool:
    """Recognize only DeepSeek itself or a syntactically valid subdomain."""

    try:
        hostname = (urlsplit(str(value or "").strip()).hostname or "").lower()
    except (TypeError, ValueError):
        return False
    # A single trailing dot is the canonical fully-qualified DNS spelling.
    if hostname.endswith("."):
        hostname = hostname[:-1]
    if not _is_legal_dns_hostname(hostname):
        return False
    return hostname == DEEPSEEK_DOMAIN or hostname.endswith(f".{DEEPSEEK_DOMAIN}")


def _extract_direct_identifiers(value: object) -> list[str]:
    """Extract version-like ASCII identifiers with a single linear scan.

    Identifiers start with a letter, contain at least one digit, and may use
    dots, underscores, or hyphens internally. Trailing separators are omitted.
    """

    text = str(value or "").lower()
    identifiers: list[str] = []
    start: int | None = None
    has_digit = False

    def is_word_character(character: str | None) -> bool:
        # Match Python's Unicode-aware ``\b`` behavior closely enough for the
        # former regex: letters/digits from any script and underscore are word
        # characters. This prevents a suffix such as Chinese ``模型v2`` from
        # being reinterpreted as the standalone identifier ``v2``.
        return character is not None and (character == "_" or character.isalnum())

    for index in range(len(text) + 1):
        character = text[index] if index < len(text) else None
        if start is None:
            if character in ASCII_LOWERCASE:
                previous = text[index - 1] if index else None
                if not is_word_character(previous):
                    start = index
                    has_digit = False
            continue

        if character in IDENTIFIER_BODY:
            has_digit = has_digit or character in ASCII_DIGITS
            continue

        end = index
        while end > start and text[end - 1] in ".-":
            end -= 1
        has_end_boundary = end < index or not is_word_character(character)
        if has_digit and end > start and has_end_boundary:
            identifiers.append(text[start:end])
        start = None
        has_digit = False

    return identifiers


class RagEngine:
    def __init__(
        self,
        retriever: HybridRetriever,
        answer_generator: BaseAnswerGenerator | None = None,
        no_answer_threshold: float = 0.05,
        grounding_min_confidence: float = 0.15,
        citation_overlap_threshold: float = 0.34,
        allow_generation_fallback: bool = True,
    ):
        self.retriever = retriever
        self.answer_generator = answer_generator or TemplateAnswerGenerator()
        self.no_answer_threshold = no_answer_threshold
        self.grounding_min_confidence = grounding_min_confidence
        self.citation_overlap_threshold = citation_overlap_threshold
        self.allow_generation_fallback = allow_generation_fallback

    def snapshot_answer_generator(self) -> BaseAnswerGenerator:
        """Return the generator reference that one request must use end to end.

        Runtime provider changes replace this reference atomically. Capturing it
        once prevents a request from generating with one provider while metrics
        or persisted traces are labelled with a later provider.
        """

        return self.answer_generator

    @staticmethod
    def _generation_failure(exc: Exception) -> tuple[str, str]:
        error_name = type(exc).__name__.lower()
        if isinstance(exc, TimeoutError) or "timeout" in error_name:
            return (
                "ANSWER_PROVIDER_TIMEOUT",
                public_error_message(
                    exc,
                    "回答服务在规定时间内未完成生成，已保留检索证据，请稍后重试。",
                ),
            )
        return (
            "ANSWER_PROVIDER_FAILED",
            public_error_message(
                exc,
                "回答服务暂时不可用，已保留检索证据，请稍后重试。",
            ),
        )

    def _template_fallback_allowed(
        self,
        answer_generator: BaseAnswerGenerator,
    ) -> bool:
        """Never turn a DeepSeek outage into a synthetic template answer."""

        provider = str(getattr(answer_generator, "name", "") or "").lower()
        client = getattr(answer_generator, "client", None)
        model = str(getattr(client, "model", "") or "").lower()
        base_url = getattr(client, "base_url", "")
        is_deepseek = (
            provider.startswith("deepseek")
            or model.startswith("deepseek")
            or _is_deepseek_base_url(base_url)
        )
        return self.allow_generation_fallback and not is_deepseek

    def ask(
        self,
        question: str,
        top_k: int = 5,
        retrieval_query: str | None = None,
        answer_generator_snapshot: BaseAnswerGenerator | None = None,
        **retrieval_options,
    ) -> dict:
        started = time.perf_counter()
        answer_generator = (
            answer_generator_snapshot or self.snapshot_answer_generator()
        )
        active_query = retrieval_query or question
        ranked, trace = self.retriever.search(active_query, top_k=top_k, **retrieval_options)
        trace["query_enrichment_used"] = active_query != question
        retrieval_ended = time.perf_counter()
        threshold = retrieval_options.get("min_score")
        threshold = self.no_answer_threshold if threshold is None else float(threshold)
        trace["no_answer_threshold"] = threshold
        trace.setdefault("performance", {})
        trace["performance"]["retrieval_ms"] = round((retrieval_ended - started) * 1000, 2)
        confidence = self._confidence(ranked)
        diagnostics = self._diagnostics(active_query, ranked, trace, threshold)
        refuse, refuse_reason = self._should_refuse(
            active_query, ranked, confidence, threshold
        )
        trace["refuse_reason"] = refuse_reason
        trace["refusal_reason"] = refuse_reason or None
        trace.setdefault("pipeline", {})["decision"] = {
            "status": "refused" if refuse else "answered",
            "reason": refuse_reason or "evidence_accepted",
            "threshold": threshold,
            "confidence": round(float(confidence), 4),
        }
        if refuse:
            if refuse_reason in {"weak_grounding", "explicit_evidence_gap"}:
                diagnostics.append(
                    {
                        "level": "warning",
                        "title": (
                            "证据明确标记了资料缺口"
                            if refuse_reason == "explicit_evidence_gap"
                            else "证据与问题缺少直接词项匹配"
                        ),
                        "message": (
                            "当前证据只能确认相关资料缺失，不能支撑所请的具体操作或配置。"
                            if refuse_reason == "explicit_evidence_gap"
                            else "最高分尚不足以在无关键词命中的情况下安全生成回答。"
                        ),
                        "action": "补充限定词、切换检索模式，或导入更直接的资料。",
                        "actions": [],
                    }
                )
            audit = audit_answer(
                "",
                [],
                0,
                threshold,
                overlap_threshold=self.citation_overlap_threshold,
            )
            trace["pipeline"]["citation_audit"] = {"coverage": 0, "grounding": 0, "status": "skipped"}
            trace["performance"]["total_ms"] = round((time.perf_counter() - started) * 1000, 2)
            return {
                "answer": "答案：\n根据当前知识库资料，无法确定。\n\n依据：\n没有检索到足够相关的证据片段。\n\n不确定性：\n需要导入更多相关资料后再回答。",
                "citations": [],
                "retrieval_trace": trace,
                "generation_trace": {
                    "answer_provider": answer_generator.name,
                    "answer_model": "-",
                    "grounded": True,
                    "skipped": True,
                    "reason": refuse_reason,
                },
                "confidence": 0,
                "diagnostics": diagnostics,
                **audit,
            }

        citations = [self._chunk_to_dict(item) for item in ranked]
        generation_started = time.perf_counter()
        try:
            generated = answer_generator.generate(question, citations, trace)
        except Exception as exc:
            if not self._template_fallback_allowed(answer_generator):
                generation_ended = time.perf_counter()
                code, message = self._generation_failure(exc)
                trace["performance"]["generation_ms"] = round(
                    (generation_ended - generation_started) * 1000,
                    2,
                )
                trace["performance"]["total_ms"] = round(
                    (generation_ended - started) * 1000,
                    2,
                )
                trace["pipeline"]["generation"] = {
                    "status": "failed",
                    "reason": "answer_provider_failed",
                    "error_code": code,
                }
                trace["pipeline"]["citation_audit"] = {
                    "coverage": 0,
                    "grounding": 0,
                    "status": "skipped",
                    "reason": "generation_failed",
                }
                diagnostics.append(
                    {
                        "level": "error",
                        "title": "回答生成未完成",
                        "message": message,
                        "action": "检索证据已保留，可原样重试本次问题。",
                        "actions": [],
                    }
                )
                audit = audit_answer(
                    "",
                    citations,
                    confidence,
                    threshold,
                    overlap_threshold=self.citation_overlap_threshold,
                )
                audit["citation_audit"].update(
                    {
                        "checked": False,
                        "status": "skipped",
                        "reason": "generation_failed",
                    }
                )
                return {
                    "answer": "",
                    "citations": citations,
                    "retrieval_trace": trace,
                    "generation_trace": {
                        "answer_provider": answer_generator.name,
                        "answer_model": getattr(
                            getattr(answer_generator, "client", None),
                            "model",
                            "-",
                        ),
                        "grounded": False,
                        "status": "failed",
                        "incomplete": True,
                        "failure_stage": "generation",
                        "error_code": code,
                        "message": message,
                        "retryable": True,
                    },
                    "retryable": True,
                    "retry": {
                        "action": "resubmit_same_request",
                        "preserve_retrieval_scope": True,
                    },
                    "confidence": round(float(confidence), 4),
                    "diagnostics": diagnostics,
                    **audit,
                }
            generated = TemplateAnswerGenerator().generate(question, citations, trace)
            generated["generation_trace"] = {
                **generated.get("generation_trace", {}),
                "answer_provider": "template",
                "fallback_from": answer_generator.name,
                "fallback_reason": public_error_message(
                    exc,
                    "回答 Provider 暂时不可用，已使用离线 template。",
                ),
                "grounded": True,
            }
        generation_ended = time.perf_counter()
        trace["performance"]["generation_ms"] = round((generation_ended - generation_started) * 1000, 2)
        trace["performance"]["total_ms"] = round((generation_ended - started) * 1000, 2)
        audit = audit_answer(
            generated["answer"],
            citations,
            confidence,
            threshold,
            overlap_threshold=self.citation_overlap_threshold,
        )
        trace["pipeline"]["citation_audit"] = {
            "coverage": audit.get("citation_audit", {}).get("coverage", 0),
            "grounding": audit.get("citation_audit", {}).get("grounding", 0),
            "status": "checked",
        }
        return {
            "answer": generated["answer"],
            "citations": citations,
            "retrieval_trace": trace,
            "generation_trace": generated.get("generation_trace", {}),
            "confidence": round(float(confidence), 4),
            "diagnostics": diagnostics,
            **audit,
        }

    def stream(
        self,
        question: str,
        top_k: int = 5,
        retrieval_query: str | None = None,
        answer_generator_snapshot: BaseAnswerGenerator | None = None,
        **retrieval_options,
    ):
        """Stream a grounded answer while preserving the same refusal/audit gates as ask()."""
        started = time.perf_counter()
        answer_generator = (
            answer_generator_snapshot or self.snapshot_answer_generator()
        )
        active_query = retrieval_query or question
        ranked, trace = self.retriever.search(active_query, top_k=top_k, **retrieval_options)
        trace["conversation_context_used"] = active_query != question
        retrieval_ended = time.perf_counter()
        threshold = retrieval_options.get("min_score")
        threshold = self.no_answer_threshold if threshold is None else float(threshold)
        trace["no_answer_threshold"] = threshold
        trace.setdefault("performance", {})["retrieval_ms"] = round((retrieval_ended - started) * 1000, 2)
        confidence = self._confidence(ranked)
        diagnostics = self._diagnostics(active_query, ranked, trace, threshold)
        refuse, refuse_reason = self._should_refuse(
            active_query, ranked, confidence, threshold
        )
        trace["refuse_reason"] = refuse_reason
        trace["refusal_reason"] = refuse_reason or None
        trace.setdefault("pipeline", {})["decision"] = {
            "status": "refused" if refuse else "answered",
            "reason": refuse_reason or "evidence_accepted",
            "threshold": threshold,
            "confidence": round(float(confidence), 4),
        }
        if refuse:
            audit = audit_answer("", [], 0, threshold, overlap_threshold=self.citation_overlap_threshold)
            trace["pipeline"]["citation_audit"] = {"coverage": 0, "grounding": 0, "status": "skipped"}
            trace["performance"]["total_ms"] = round((time.perf_counter() - started) * 1000, 2)
            response = {
                "answer": "答案：\n根据当前知识库资料，无法确定。\n\n依据：\n没有检索到足够相关的证据片段。\n\n不确定性：\n需要导入更多相关资料后再回答。",
                "citations": [],
                "retrieval_trace": trace,
                "generation_trace": {
                    "answer_provider": answer_generator.name,
                    "answer_model": "-",
                    "grounded": True,
                    "skipped": True,
                    "reason": refuse_reason,
                },
                "confidence": 0,
                "diagnostics": diagnostics,
                **audit,
            }
            yield {"type": "retrieval.completed", "response": response}
            yield {"type": "refusal", "response": response}
            return

        citations = [self._chunk_to_dict(item) for item in ranked]
        yield {
            "type": "retrieval.completed",
            "response": {
                "citations": citations,
                "retrieval_trace": trace,
                "generation_trace": {
                    "answer_provider": answer_generator.name,
                    "answer_model": getattr(
                        getattr(answer_generator, "client", None),
                        "model",
                        "-",
                    ),
                    "status": "pending",
                },
                "confidence": round(float(confidence), 4),
                "diagnostics": diagnostics,
            },
        }
        generation_started = time.perf_counter()
        fragments: list[str] = []
        first_token_recorded = False
        try:
            for delta in answer_generator.stream(question, citations, trace):
                if not delta:
                    continue
                fragments.append(delta)
                if not first_token_recorded:
                    trace["performance"]["first_token_ms"] = round((time.perf_counter() - started) * 1000, 2)
                    first_token_recorded = True
                yield {"type": "answer.delta", "delta": delta}
            if not "".join(fragments).strip():
                raise ValueError("Answer provider returned no text output")
        except Exception as exc:
            if not self._template_fallback_allowed(answer_generator) or fragments:
                raise
            fallback = TemplateAnswerGenerator().generate(question, citations, trace)
            fallback_answer = fallback["answer"]
            for start in range(0, len(fallback_answer), 24):
                delta = fallback_answer[start : start + 24]
                fragments.append(delta)
                yield {"type": "answer.delta", "delta": delta}
            generation_trace = {
                **fallback.get("generation_trace", {}),
                "fallback_from": answer_generator.name,
                "fallback_reason": public_error_message(
                    exc,
                    "回答 Provider 暂时不可用，已使用离线 template。",
                ),
            }
        else:
            generation_trace = {
                "answer_provider": answer_generator.name,
                "answer_model": getattr(getattr(answer_generator, "client", None), "model", "-"),
                "grounded": True,
                "citation_count": len(citations),
                "streamed": True,
            }
        answer = "".join(fragments)
        generation_ended = time.perf_counter()
        trace["performance"]["generation_ms"] = round((generation_ended - generation_started) * 1000, 2)
        trace["performance"]["total_ms"] = round((generation_ended - started) * 1000, 2)
        audit = audit_answer(answer, citations, confidence, threshold, overlap_threshold=self.citation_overlap_threshold)
        trace["pipeline"]["citation_audit"] = {
            "coverage": audit.get("citation_audit", {}).get("coverage", 0),
            "grounding": audit.get("citation_audit", {}).get("grounding", 0),
            "status": "checked",
        }
        response = {
            "answer": answer,
            "citations": citations,
            "retrieval_trace": trace,
            "generation_trace": generation_trace,
            "confidence": round(float(confidence), 4),
            "diagnostics": diagnostics,
            **audit,
        }
        yield {"type": "answer.completed", "response": response}

    def search(self, query: str, top_k: int = 5, **retrieval_options) -> dict:
        started = time.perf_counter()
        ranked, trace = self.retriever.search(query, top_k=top_k, **retrieval_options)
        threshold = retrieval_options.get("min_score")
        threshold = self.no_answer_threshold if threshold is None else float(threshold)
        trace["no_answer_threshold"] = threshold
        trace.setdefault("performance", {})
        trace["performance"]["total_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return {
            "results": [self._chunk_to_dict(item) for item in ranked],
            "trace": trace,
            "diagnostics": self._diagnostics(query, ranked, trace, threshold),
        }

    def compare(self, query: str, top_k: int = 5, **retrieval_options) -> dict:
        profiles = [
            {
                "id": "keyword",
                "label": "关键词 BM25",
                "overrides": {
                    "search_mode": "keyword",
                    "query_rewrite": False,
                    "rerank_enabled": False,
                },
            },
            {
                "id": "semantic",
                "label": "语义向量",
                "overrides": {
                    "search_mode": "semantic",
                    "query_rewrite": False,
                    "rerank_enabled": False,
                },
            },
            {
                "id": "hybrid",
                "label": "混合检索",
                "overrides": {
                    "search_mode": "hybrid",
                    "query_rewrite": retrieval_options.get("query_rewrite", True),
                    "rerank_enabled": False,
                },
            },
            {
                "id": "hybrid_rerank",
                "label": "混合 + Rerank",
                "overrides": {
                    "search_mode": "hybrid",
                    "query_rewrite": retrieval_options.get("query_rewrite", True),
                    "rerank_enabled": True,
                },
            },
        ]
        rows = []
        for profile in profiles:
            options = {**retrieval_options, **profile["overrides"]}
            result = self.search(query, top_k=top_k, **options)
            top_result = result["results"][0] if result["results"] else None
            rows.append(
                {
                    "id": profile["id"],
                    "label": profile["label"],
                    "results": result["results"],
                    "trace": result["trace"],
                    "diagnostics": result["diagnostics"],
                    "summary": {
                        "returned": len(result["results"]),
                        "top_score": top_result["rerank_score"] if top_result else 0,
                        "top_source": top_result["filename"] if top_result else "-",
                        "matched_terms": top_result.get("matched_terms", []) if top_result else [],
                    },
                }
            )
        best = max(rows, key=lambda row: row["summary"]["top_score"], default=None)
        return {
            "query": query,
            "profiles": rows,
            "best_profile": best["id"] if best else None,
        }

    def evaluate(self, cases: list[dict]) -> list[dict]:
        results = []
        for case in cases:
            question = case["question"]
            expected = case.get("expected_keywords", [])
            ranked, _ = self.retriever.search(question, top_k=5)
            joined = "\n".join(item["chunk"].text for item in ranked)
            matched = [keyword for keyword in expected if keyword.lower() in joined.lower()]
            has_evidence = bool(ranked) and ranked[0]["score"] >= 0.05
            results.append(
                {
                    "question": question,
                    "hit": bool(matched) if expected else not has_evidence,
                    "matched_keywords": matched,
                    "top_sources": [item["chunk"].filename for item in ranked[:3]] if has_evidence else [],
                }
            )
        return results

    def _confidence(self, ranked: list[dict]) -> float:
        if not ranked:
            return 0.0
        return float(ranked[0].get("rerank_score", ranked[0]["score"]))

    def _should_refuse(
        self,
        query: str,
        ranked: list[dict],
        confidence: float,
        threshold: float,
    ) -> tuple[bool, str]:
        if not ranked:
            return True, "no_evidence"
        if confidence < threshold:
            return True, "below_threshold"
        matched_terms = {str(term).lower() for term in ranked[0].get("matched_terms", [])}
        substantive_terms = {
            term
            for term in matched_terms - LOW_INFORMATION_MATCHES
            if not (
                len(term) == 2
                and (
                    term[0] in LOW_INFORMATION_BOUNDARY_CHARS
                    or term[-1] in LOW_INFORMATION_BOUNDARY_CHARS
                )
            )
        }
        mock_embeddings = isinstance(
            getattr(self.retriever, "embedding_provider", None),
            MockEmbeddingProvider,
        )
        if mock_embeddings and not substantive_terms:
            return True, "weak_grounding"
        if not matched_terms and confidence < self.grounding_min_confidence:
            return True, "weak_grounding"
        # Gate on the retrieved leaf, not its expanded parent window: a sibling
        # may describe a gap while the cited leaf directly answers the question.
        evidence_text = str(ranked[0]["chunk"].text or "")
        normalized_query = " ".join(str(query).lower().split())
        normalized_evidence = " ".join(evidence_text.lower().split())
        availability_question = any(
            marker in normalized_query for marker in AVAILABILITY_QUESTION_MARKERS
        )
        direct_identifiers = set(_extract_direct_identifiers(normalized_query))
        evidence_identifiers = set(_extract_direct_identifiers(normalized_evidence))
        has_direct_identifier_evidence = bool(
            direct_identifiers.intersection(evidence_identifiers)
        )
        if not availability_question and not has_direct_identifier_evidence and any(
            marker in normalized_evidence for marker in EVIDENCE_GAP_MARKERS
        ):
            return True, "explicit_evidence_gap"
        return False, ""

    def _chunk_to_dict(self, item: dict) -> dict:
        chunk = item["chunk"]
        return {
            "id": chunk.id,
            "document_id": chunk.document_id,
            "filename": chunk.filename,
            "index": chunk.index,
            "text": chunk.text,
            "page_number": chunk.page_number,
            "heading_path": chunk.heading_path,
            "element_ids": chunk.element_ids,
            "modality": chunk.modality,
            "parent_element_id": chunk.parent_element_id,
            "metadata": redact_private_metadata(chunk.metadata),
            "parent_context": item.get("parent_context")
            or self._parent_context(chunk, int(item.get("parent_window", 1))),
            "score": round(float(item["score"]), 4),
            "bm25_score": round(float(item["bm25_score"]), 4),
            "vector_score": round(float(item["vector_score"]), 4),
            "rerank_score": round(float(item.get("rerank_score", item["score"])), 4),
            "cross_encoder_score": (
                round(float(item["cross_encoder_score"]), 4)
                if item.get("cross_encoder_score") is not None
                else None
            ),
            "matched_terms": item.get("matched_terms", []),
            "snippet": self._snippet(chunk.text, item.get("matched_terms", [])),
            "score_breakdown": {
                **item.get("score_breakdown", {}),
                "rerank_score": round(float(item.get("rerank_score", item["score"])), 6),
            },
        }

    def _snippet(self, text: str, matched_terms: list[str], window: int = 180) -> str:
        cleaned = " ".join(text.split())
        if len(cleaned) <= window:
            return cleaned
        lower = cleaned.lower()
        positions = [lower.find(term.lower()) for term in matched_terms if term and lower.find(term.lower()) >= 0]
        center = min(positions) if positions else 0
        start = max(0, center - window // 3)
        end = min(len(cleaned), start + window)
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(cleaned) else ""
        return f"{prefix}{cleaned[start:end]}{suffix}"

    def _parent_context(self, chunk, radius: int = 1) -> dict:
        radius = max(0, min(int(radius), 3))
        vector_store = self.retriever.vector_store
        if hasattr(vector_store, "context_chunks"):
            context_chunks = vector_store.context_chunks(chunk.chunk_id, radius)
        else:
            context_chunks = [
                item
                for item in getattr(vector_store, "chunks", {}).values()
                if item.document_id == chunk.document_id
            ]
        siblings = sorted(
            context_chunks,
            key=lambda item: item.chunk_index,
        )
        index = next((idx for idx, item in enumerate(siblings) if item.chunk_id == chunk.chunk_id), -1)
        if index < 0:
            return {"strategy": "parent_child", "text": chunk.text, "chunk_ids": [chunk.chunk_id]}
        window = siblings[max(0, index - radius) : min(len(siblings), index + radius + 1)]
        return {
            "strategy": "parent_child",
            "text": "\n\n".join(item.text for item in window),
            "chunk_ids": [item.chunk_id for item in window],
            "current_chunk_id": chunk.chunk_id,
            "window": radius,
        }

    def _diagnostics(self, query: str, ranked: list[dict], trace: dict, threshold: float) -> list[dict]:
        diagnostics: list[dict] = []
        if trace.get("fallbacks"):
            diagnostics.append(
                {
                    "level": "warning",
                    "title": "已触发兜底机制",
                    "message": "部分检索或模型链路失败，系统已自动降级并保留可用结果。",
                    "action": "查看 trace.fallbacks 判断失败环节。",
                    "actions": [
                        {
                            "id": "open_expert_trace",
                            "label": "查看检索过程",
                            "type": "ui",
                            "payload": {"panel": "trace"},
                        }
                    ],
                }
            )
        if trace.get("available_chunks", 0) == 0:
            diagnostics.append(
                {
                    "level": "error",
                    "title": "当前范围没有可检索片段",
                    "message": "选中的文档范围内没有 chunk，或索引尚未建立。",
                    "action": "切换到全部文档，或重建索引。",
                    "actions": [
                        {
                            "id": "retry_all_documents",
                            "label": "切换全部资料再试",
                            "type": "retry_search",
                            "payload": {"document_ids": []},
                        },
                        {
                            "id": "rebuild_all_indexes",
                            "label": "重建全部索引",
                            "type": "index",
                            "payload": {},
                        },
                    ],
                }
            )
            return diagnostics
        if not ranked:
            diagnostics.append(
                {
                    "level": "warning",
                    "title": "没有通过阈值的证据",
                    "message": "当前检索可能被文档范围、最低分阈值或搜索模式限制。",
                    "action": "降低阈值、扩大候选池，或切换混合检索。",
                    "actions": [
                        {
                            "id": "relax_threshold",
                            "label": "降低严格度再试",
                            "type": "retry_search",
                            "payload": {"min_score": max(0.0, round(threshold * 0.5, 3))},
                        },
                        {
                            "id": "expand_candidate_pool",
                            "label": "扩大搜索范围再试",
                            "type": "retry_search",
                            "payload": {"candidate_k_multiplier": 2},
                        },
                        {
                            "id": "switch_hybrid",
                            "label": "切换混合检索",
                            "type": "retry_search",
                            "payload": {"search_mode": "hybrid"},
                        },
                    ],
                }
            )
        elif self._confidence(ranked) < threshold:
            diagnostics.append(
                {
                    "level": "warning",
                    "title": "证据置信度偏低",
                    "message": "最高分低于拒答阈值，直接生成回答可能增加幻觉风险。",
                    "action": "补充相关文档，或切换召回 profile 后重试。",
                    "actions": [
                        {
                            "id": "switch_recall_profile",
                            "label": "扩大召回再试",
                            "type": "retry_search",
                            "payload": {"search_profile": "recall"},
                        },
                        {
                            "id": "view_evidence_only",
                            "label": "只看证据",
                            "type": "ui",
                            "payload": {"work_mode": "search"},
                        },
                    ],
                }
            )
        if len(query.strip()) <= 4:
            diagnostics.append(
                {
                    "level": "info",
                    "title": "问题较短",
                    "message": "短问题容易召回过宽，关键词权重可能更可靠。",
                    "action": "补充限定词，或切换精准 profile。",
                    "actions": [
                        {
                            "id": "switch_precision_profile",
                            "label": "精准搜索再试",
                            "type": "retry_search",
                            "payload": {"search_profile": "precision"},
                        }
                    ],
                }
            )
        if trace.get("document_ids") and not ranked:
            diagnostics.append(
                {
                    "level": "info",
                    "title": "文档范围可能过窄",
                    "message": "当前只在选中文档中检索，相关证据可能在其他文档。",
                    "action": "切换到全部文档重新搜索。",
                    "actions": [
                        {
                            "id": "retry_all_documents",
                            "label": "切换全部资料再试",
                            "type": "retry_search",
                            "payload": {"document_ids": []},
                        }
                    ],
                }
            )
        if ranked and not ranked[0].get("matched_terms") and trace.get("search_mode") == "keyword":
            diagnostics.append(
                {
                    "level": "info",
                    "title": "关键词命中较弱",
                    "message": "首条证据没有明显 matched terms，可能需要语义检索补充。",
                    "action": "切换混合或语义模式。",
                    "actions": [
                        {
                            "id": "switch_hybrid",
                            "label": "混合检索再试",
                            "type": "retry_search",
                            "payload": {"search_mode": "hybrid"},
                        },
                        {
                            "id": "switch_semantic",
                            "label": "语义检索再试",
                            "type": "retry_search",
                            "payload": {"search_mode": "semantic"},
                        },
                    ],
                }
            )
        return diagnostics
