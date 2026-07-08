from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.services.document_processor import DocumentProcessor  # noqa: E402
from app.services.rag_engine import RagEngine  # noqa: E402
from app.services.retriever import HybridRetriever  # noqa: E402


def main() -> None:
    sample = ROOT / "samples" / "rag-notes.md"
    processor = DocumentProcessor()
    retriever = HybridRetriever()
    engine = RagEngine(retriever)

    document = processor.parse_file(sample)
    retriever.add_document(document, processor.split(document))

    cases = [
        {
            "question": "如何优化 RAG 的召回质量？",
            "expected_keywords": ["BM25", "向量检索", "Rerank"],
        },
        {
            "question": "RAG 评测指标有哪些？",
            "expected_keywords": ["MRR", "引用准确率"],
        },
        {
            "question": "这份资料有没有提到 Kubernetes 部署？",
            "expected_keywords": [],
        },
    ]

    report = {
        "sample": str(sample),
        "results": engine.evaluate(cases),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

