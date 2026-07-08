from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.services.document_processor import DocumentProcessor  # noqa: E402
from app.services.retriever import HybridRetriever  # noqa: E402


def load_cases(path: Path) -> list[dict]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            cases.append(json.loads(line))
    return cases


def main() -> None:
    sample = ROOT / "samples" / "rag-notes.md"
    cases_path = ROOT / "eval" / "cases.jsonl"

    processor = DocumentProcessor()
    document = processor.parse_file(sample)
    retriever = HybridRetriever()
    retriever.add_document(document, processor.split(document))

    rows = []
    recall_hits = 0
    reciprocal_ranks = []
    citation_precision_scores = []

    for case in load_cases(cases_path):
        results, trace = retriever.search(case["question"], top_k=5)
        expected_keywords = case.get("expected_keywords", [])
        if not expected_keywords:
            hit = not results or results[0].get("score", 0) < 0.05
            rank = None
            precision = 1.0 if hit else 0.0
            top_sources = [] if hit else [item["chunk"].file_name for item in results[:3]]
        else:
            match_ranks = []
            matched_citations = 0
            for idx, item in enumerate(results, start=1):
                text = item["chunk"].text.lower()
                if any(keyword.lower() in text for keyword in expected_keywords):
                    match_ranks.append(idx)
                    matched_citations += 1
            hit = bool(match_ranks)
            rank = match_ranks[0] if match_ranks else None
            precision = matched_citations / max(len(results), 1)
            top_sources = [item["chunk"].file_name for item in results[:3]]

        recall_hits += int(hit)
        reciprocal_ranks.append(1 / rank if rank else 0)
        citation_precision_scores.append(precision)
        rows.append(
            {
                "question": case["question"],
                "hit": hit,
                "first_relevant_rank": rank,
                "citation_precision": round(precision, 4),
                "top_sources": top_sources,
                "trace": {
                    "candidate_k": trace["candidate_k"],
                    "rewritten_queries": trace["rewritten_queries"],
                    "reranker": trace["reranker"],
                },
            }
        )

    report = {
        "cases": len(rows),
        "recall_at_5": round(recall_hits / max(len(rows), 1), 4),
        "mrr": round(sum(reciprocal_ranks) / max(len(reciprocal_ranks), 1), 4),
        "citation_precision": round(sum(citation_precision_scores) / max(len(citation_precision_scores), 1), 4),
        "rows": rows,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
