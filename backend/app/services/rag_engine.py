from __future__ import annotations

import time

from app.services.answer_generator import BaseAnswerGenerator, TemplateAnswerGenerator
from app.services.citation_audit import audit_answer
from app.services.retriever import HybridRetriever


class RagEngine:
    def __init__(
        self,
        retriever: HybridRetriever,
        answer_generator: BaseAnswerGenerator | None = None,
        no_answer_threshold: float = 0.05,
        grounding_min_confidence: float = 0.15,
        citation_overlap_threshold: float = 0.34,
    ):
        self.retriever = retriever
        self.answer_generator = answer_generator or TemplateAnswerGenerator()
        self.no_answer_threshold = no_answer_threshold
        self.grounding_min_confidence = grounding_min_confidence
        self.citation_overlap_threshold = citation_overlap_threshold

    def ask(self, question: str, top_k: int = 5, **retrieval_options) -> dict:
        started = time.perf_counter()
        ranked, trace = self.retriever.search(question, top_k=top_k, **retrieval_options)
        retrieval_ended = time.perf_counter()
        threshold = retrieval_options.get("min_score")
        threshold = self.no_answer_threshold if threshold is None else float(threshold)
        trace["no_answer_threshold"] = threshold
        trace.setdefault("performance", {})
        trace["performance"]["retrieval_ms"] = round((retrieval_ended - started) * 1000, 2)
        confidence = self._confidence(ranked)
        diagnostics = self._diagnostics(question, ranked, trace, threshold)
        refuse, refuse_reason = self._should_refuse(ranked, confidence, threshold)
        trace["refuse_reason"] = refuse_reason
        trace["refusal_reason"] = refuse_reason or None
        if refuse:
            if refuse_reason == "weak_grounding":
                diagnostics.append(
                    {
                        "level": "warning",
                        "title": "证据与问题缺少直接词项匹配",
                        "message": "最高分尚不足以在无关键词命中的情况下安全生成回答。",
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
            trace["performance"]["total_ms"] = round((time.perf_counter() - started) * 1000, 2)
            return {
                "answer": "答案：\n根据当前知识库资料，无法确定。\n\n依据：\n没有检索到足够相关的证据片段。\n\n不确定性：\n需要导入更多相关资料后再回答。",
                "citations": [],
                "retrieval_trace": trace,
                "generation_trace": {
                    "answer_provider": self.answer_generator.name,
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
            generated = self.answer_generator.generate(question, citations, trace)
        except Exception as exc:
            generated = TemplateAnswerGenerator().generate(question, citations, trace)
            generated["generation_trace"] = {
                **generated.get("generation_trace", {}),
                "answer_provider": "template",
                "fallback_from": self.answer_generator.name,
                "fallback_reason": str(exc),
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
        return {
            "answer": generated["answer"],
            "citations": citations,
            "retrieval_trace": trace,
            "generation_trace": generated.get("generation_trace", {}),
            "confidence": round(float(confidence), 4),
            "diagnostics": diagnostics,
            **audit,
        }

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

    def _should_refuse(self, ranked: list[dict], confidence: float, threshold: float) -> tuple[bool, str]:
        if not ranked:
            return True, "no_evidence"
        if confidence < threshold:
            return True, "below_threshold"
        if not ranked[0].get("matched_terms") and confidence < self.grounding_min_confidence:
            return True, "weak_grounding"
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
            "metadata": chunk.metadata,
            "parent_context": self._parent_context(chunk),
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

    def _parent_context(self, chunk) -> dict:
        siblings = sorted(
            [
                item
                for item in self.retriever.vector_store.chunks.values()
                if item.document_id == chunk.document_id
            ],
            key=lambda item: item.chunk_index,
        )
        index = next((idx for idx, item in enumerate(siblings) if item.chunk_id == chunk.chunk_id), -1)
        if index < 0:
            return {"strategy": "parent_child", "text": chunk.text, "chunk_ids": [chunk.chunk_id]}
        window = siblings[max(0, index - 1) : min(len(siblings), index + 2)]
        return {
            "strategy": "parent_child",
            "text": "\n\n".join(item.text for item in window),
            "chunk_ids": [item.chunk_id for item in window],
            "current_chunk_id": chunk.chunk_id,
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
