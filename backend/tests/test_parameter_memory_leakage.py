from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.models.domain import Chunk
from app.services.answer_generator import BaseAnswerGenerator
from app.services.rag_engine import RagEngine


class StaticScenarioRetriever:
    """Return one controlled evidence set without consulting any model."""

    embedding_provider = object()
    vector_store = SimpleNamespace(chunks={})

    def __init__(self, ranked: list[dict]):
        self.ranked = ranked

    def search(self, *_args, **_kwargs):
        return self.ranked, {
            "available_chunks": len(self.ranked),
            "pipeline": {},
            "fallbacks": [],
        }


class MemorizedAnswerGenerator(BaseAnswerGenerator):
    """A canary generator that knows the answer independently of evidence."""

    name = "parametric-memory-canary"

    def __init__(self, memorized_answer: str):
        self.memorized_answer = memorized_answer
        self.calls: list[str] = []

    def generate(self, _question, _citations, _trace):
        self.calls.append("generate")
        return {
            "answer": self.memorized_answer,
            "generation_trace": {
                "answer_provider": self.name,
                "answer_model": "memorized-model",
                "grounded": False,
            },
        }

    def stream(self, _question, _citations, _trace):
        self.calls.append("stream")
        yield self.memorized_answer


def _ranked_evidence(
    text: str,
    *,
    score: float,
    matched_terms: list[str],
    chunk_id: str,
) -> list[dict]:
    chunk = Chunk(
        chunk_id=chunk_id,
        document_id=f"document-{chunk_id}",
        chunk_index=0,
        text=text,
        file_name=f"{chunk_id}.md",
        page_number=1,
    )
    return [
        {
            "chunk": chunk,
            "score": score,
            "bm25_score": score,
            "vector_score": score,
            "rerank_score": score,
            "matched_terms": matched_terms,
            "parent_context": {
                "strategy": "parent_child",
                "text": text,
                "chunk_ids": [chunk.chunk_id],
            },
        }
    ]


SCENARIOS = [
    pytest.param(
        "Apollo-7 的发射窗口是什么时间？",
        [],
        "Apollo-7 的发射窗口是 2042-07-11 09:30。[1]",
        "no_evidence",
        id="empty-retrieval",
    ),
    pytest.param(
        "Vega-9 的质量上限是多少？",
        _ranked_evidence(
            "本文介绍通用航天器的项目管理流程。",
            score=0.10,
            matched_terms=[],
            chunk_id="weak-generic-evidence",
        ),
        "Vega-9 的质量上限是 7,250 千克。[1]",
        "weak_grounding",
        id="weak-related-evidence",
    ),
    pytest.param(
        "Aurora v2 的管理员口令是什么？",
        _ranked_evidence(
            "AuroraX v20 的管理员口令是 7788。",
            score=0.94,
            matched_terms=["管理员口令"],
            chunk_id="near-entity-wrong-version",
        ),
        "Aurora v2 的管理员口令是 4821。[1]",
        None,
        id="near-entity-wrong-version",
    ),
    pytest.param(
        "Aurora v2 的管理员口令是什么？",
        _ranked_evidence(
            "Borealis v2 的管理员口令是 7788。",
            score=0.94,
            matched_terms=["管理员口令", "v2"],
            chunk_id="wrong-entity-same-version",
        ),
        "Aurora v2 的管理员口令是 4821。[1]",
        None,
        id="wrong-entity-same-version",
    ),
    pytest.param(
        "Zenith v2 的默认超时是多少？",
        _ranked_evidence(
            "Zenith v1 的默认超时为 30 秒；Zenith v3 的默认超时为 90 秒。",
            score=0.96,
            matched_terms=["zenith", "默认超时"],
            chunk_id="conflicting-neighbour-versions",
        ),
        "Zenith v2 的默认超时是 60 秒。[1]",
        None,
        id="conflicting-neighbour-versions",
    ),
    pytest.param(
        "Nova v2 的加密密钥是什么？",
        _ranked_evidence(
            "Nova v2 的加密密钥未提供。",
            score=0.98,
            matched_terms=["nova", "v2", "加密密钥"],
            chunk_id="exact-entity-explicit-gap",
        ),
        "Nova v2 的加密密钥是 9F-42。[1]",
        "explicit_evidence_gap",
        id="exact-entity-explicit-gap",
    ),
]


@pytest.mark.parametrize("delivery", ["ask", "stream"])
@pytest.mark.parametrize(
    ("question", "ranked", "memorized_answer", "expected_reason"),
    SCENARIOS,
)
def test_parametric_memory_never_bypasses_the_evidence_gate(
    delivery: str,
    question: str,
    ranked: list[dict],
    memorized_answer: str,
    expected_reason: str | None,
):
    generator = MemorizedAnswerGenerator(memorized_answer)
    engine = RagEngine(
        StaticScenarioRetriever(ranked),
        answer_generator=generator,
        no_answer_threshold=0.05,
        grounding_min_confidence=0.15,
    )

    if delivery == "ask":
        payload = engine.ask(question)
        response = payload
        event_types = None
    else:
        payload = list(engine.stream(question))
        response = payload[-1]["response"]
        event_types = [event["type"] for event in payload]

    serialized_payload = json.dumps(payload, ensure_ascii=False)
    observed = {
        "decision": response["retrieval_trace"]["pipeline"]["decision"]["status"],
        "generator_calls": generator.calls,
        "memorized_answer_leaked": memorized_answer in serialized_payload,
    }
    assert observed == {
        "decision": "refused",
        "generator_calls": [],
        "memorized_answer_leaked": False,
    }
    assert response["citations"] == []
    assert response["generation_trace"]["skipped"] is True
    if event_types is not None:
        assert event_types == ["retrieval.completed", "refusal"]
    if expected_reason is not None:
        assert response["generation_trace"]["reason"] == expected_reason
