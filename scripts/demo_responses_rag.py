from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv:
    load_dotenv(ROOT / ".env", override=False)
    load_dotenv(BACKEND / ".env", override=False)

from app.core.store import processor, rag_engine, retriever  # noqa: E402


def main() -> None:
    if os.getenv("ANSWER_PROVIDER", "template").lower() not in {"responses", "openai-responses"}:
        raise SystemExit("当前 ANSWER_PROVIDER 不是 responses，请检查 .env。")
    if not os.getenv("ANSWER_API_KEY") and not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("缺少 ANSWER_API_KEY 或 OPENAI_API_KEY。")

    sample = ROOT / "samples" / "rag-notes.md"
    document = processor.parse_file(sample)
    retriever.add_document(document, processor.split(document))
    result = rag_engine.ask("如何优化 RAG 的召回质量？", top_k=5)

    safe_report = {
        "answer_provider": result.get("generation_trace", {}).get("answer_provider"),
        "answer_model": result.get("generation_trace", {}).get("answer_model"),
        "embedding_provider": result["retrieval_trace"].get("embedding_provider"),
        "vector_store": result["retrieval_trace"].get("vector_store"),
        "query_rewriter": result["retrieval_trace"].get("query_rewriter"),
        "confidence": result.get("confidence"),
        "citation_count": len(result.get("citations", [])),
        "answer": result.get("answer"),
        "citations": [
            {
                "filename": item["filename"],
                "chunk": item["index"] + 1,
                "score": item["score"],
                "rerank_score": item["rerank_score"],
            }
            for item in result.get("citations", [])
        ],
    }
    print(json.dumps(safe_report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
