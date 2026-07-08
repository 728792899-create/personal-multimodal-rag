from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.services.document_processor import DocumentProcessor  # noqa: E402
from app.services.reranker import KeywordReranker, NoopReranker  # noqa: E402
from app.services.retriever import HybridRetriever  # noqa: E402


def load_cases(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def score_profile(profile: dict, cases: list[dict]) -> dict:
    processor = DocumentProcessor()
    document = processor.parse_file(ROOT / "samples" / "rag-notes.md")
    retriever = HybridRetriever(
        reranker=profile["reranker"],
        bm25_weight=profile["bm25_weight"],
        vector_weight=profile["vector_weight"],
        mmr_lambda=profile["mmr_lambda"],
    )
    retriever.add_document(document, processor.split(document))

    recall_hits = 0
    reciprocal_ranks = []
    precision_scores = []
    no_answer_hits = 0
    no_answer_total = 0

    for case in cases:
        results, _ = retriever.search(case["question"], top_k=5)
        expected = case.get("expected_keywords", [])
        if not expected:
            no_answer_total += 1
            hit = not results or results[0].get("score", 0) < 0.05
            no_answer_hits += int(hit)
            precision = 1.0 if hit else 0.0
            rank = None
        else:
            ranks = []
            relevant = 0
            for idx, item in enumerate(results, start=1):
                text = item["chunk"].text.lower()
                if any(keyword.lower() in text for keyword in expected):
                    ranks.append(idx)
                    relevant += 1
            hit = bool(ranks)
            rank = ranks[0] if ranks else None
            precision = relevant / max(len(results), 1)

        recall_hits += int(hit)
        reciprocal_ranks.append(1 / rank if rank else 0)
        precision_scores.append(precision)

    return {
        "profile": profile["name"],
        "recall_at_5": round(recall_hits / max(len(cases), 1), 4),
        "mrr": round(sum(reciprocal_ranks) / max(len(reciprocal_ranks), 1), 4),
        "citation_precision": round(sum(precision_scores) / max(len(precision_scores), 1), 4),
        "no_answer_accuracy": round(no_answer_hits / max(no_answer_total, 1), 4),
    }


def main() -> None:
    cases = load_cases(ROOT / "eval" / "cases.jsonl")
    profiles = [
        {
            "name": "bm25_only",
            "bm25_weight": 1.0,
            "vector_weight": 0.0,
            "reranker": NoopReranker(),
            "mmr_lambda": 1.0,
        },
        {
            "name": "vector_only",
            "bm25_weight": 0.0,
            "vector_weight": 1.0,
            "reranker": NoopReranker(),
            "mmr_lambda": 1.0,
        },
        {
            "name": "hybrid_no_rerank",
            "bm25_weight": 0.62,
            "vector_weight": 0.38,
            "reranker": NoopReranker(),
            "mmr_lambda": 0.78,
        },
        {
            "name": "hybrid_keyword_rerank",
            "bm25_weight": 0.62,
            "vector_weight": 0.38,
            "reranker": KeywordReranker(),
            "mmr_lambda": 0.78,
        },
    ]
    report = {
        "cases": len(cases),
        "profiles": [score_profile(profile, cases) for profile in profiles],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
