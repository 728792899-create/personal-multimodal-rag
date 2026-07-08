from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.services.document_processor import DocumentProcessor  # noqa: E402
from app.services.embeddings import OpenAICompatibleEmbeddingProvider  # noqa: E402
from app.services.rag_engine import RagEngine  # noqa: E402
from app.services.reranker import KeywordReranker  # noqa: E402
from app.services.retriever import HybridRetriever  # noqa: E402
from app.services.vectorstore import ChromaVectorStore  # noqa: E402


def load_env_files() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    for env_path in (ROOT / ".env", BACKEND / ".env"):
        load_dotenv(env_path, override=False)


def require_module(module_name: str, install_hint: str) -> None:
    if importlib.util.find_spec(module_name) is None:
        raise SystemExit(f"缺少依赖 {module_name}，请先运行：{install_hint}")


def require_openai_key() -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("缺少 OPENAI_API_KEY。请把真实 key 写入项目根目录 .env，本脚本不会打印 key。")
    return api_key


def optional_dimension() -> int | None:
    raw = os.getenv("EMBEDDING_DIMENSION", "").strip()
    if not raw or raw == "0":
        return None
    return int(raw)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a real Chroma + OpenAI embedding RAG demo.")
    parser.add_argument("--sample", default=str(ROOT / "samples" / "rag-notes.md"))
    parser.add_argument("--question", default="如何优化 RAG 的召回质量？")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--chroma-path", default=os.getenv("CHROMA_PATH", str(ROOT / "data" / "chroma-openai-demo")))
    parser.add_argument("--collection", default="")
    return parser


def main() -> None:
    load_env_files()
    require_module("openai", "python3 -m pip install -r backend/requirements-optional.txt")
    require_module("chromadb", "python3 -m pip install -r backend/requirements-optional.txt")

    args = build_parser().parse_args()
    api_key = require_openai_key()
    sample = Path(args.sample).expanduser().resolve()
    if not sample.exists():
        raise SystemExit(f"样例文件不存在：{sample}")

    model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    dimension = optional_dimension()
    base_url = os.getenv("OPENAI_BASE_URL") or None
    collection = args.collection or f"openai_demo_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    print("=== Real Chroma + OpenAI Embedding Demo ===")
    print(
        json.dumps(
            {
                "embedding_provider": "openai",
                "embedding_model": model,
                "embedding_dimension": dimension or "provider_default",
                "openai_api_key_set": True,
                "openai_base_url_set": bool(base_url),
                "vector_store": "chroma",
                "chroma_path": str(Path(args.chroma_path).expanduser().resolve()),
                "chroma_collection": collection,
                "reranker": "keyword",
                "sample": str(sample),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    processor = DocumentProcessor()
    document = processor.parse_file(sample)
    chunks = processor.split(document)
    print(f"\nParsed document: {document.file_name}, chunks={len(chunks)}, chars={len(document.text)}")

    embedding_provider = OpenAICompatibleEmbeddingProvider(
        api_key=api_key,
        model=model,
        base_url=base_url,
        dimensions=dimension,
    )
    vector_store = ChromaVectorStore(
        persist_path=args.chroma_path,
        collection_name=collection,
    )
    retriever = HybridRetriever(
        embedding_provider=embedding_provider,
        vector_store=vector_store,
        reranker=KeywordReranker(),
        initial_retrieval_k=int(os.getenv("INITIAL_RETRIEVAL_K", "24") or "24"),
        embedding_provider_name="openai",
        embedding_model=model,
        vector_store_name="chroma",
    )
    engine = RagEngine(retriever)

    print("Embedding chunks with OpenAI and upserting into Chroma...")
    try:
        retriever.add_document(document, chunks)
    except Exception as exc:
        if exc.__class__.__name__.endswith("NotFoundError"):
            raise SystemExit(
                "Embedding 请求返回 404。当前 OPENAI_BASE_URL/模型可能只支持 Chat API，"
                "没有 OpenAI-compatible embeddings endpoint。"
            ) from exc
        if exc.__class__.__name__.endswith("BadRequestError"):
            raise SystemExit(
                "Embedding 请求被拒绝。当前模型可能是 Chat/Responses 模型，不能用于 embeddings。"
            ) from exc
        raise
    print("Chroma upsert complete.")

    answer = engine.ask(args.question, top_k=args.top_k)
    print(f"\nQuestion: {args.question}")
    print("\nAnswer:\n" + answer["answer"])
    print("\nRetrieval trace:")
    print(json.dumps(answer["retrieval_trace"], ensure_ascii=False, indent=2))
    print("\nCitations:")
    for item in answer["citations"]:
        print(
            "- "
            f"{item['filename']} chunk {item['index'] + 1} "
            f"score={item['score']} rerank={item['rerank_score']} "
            f"bm25={item['bm25_score']} vector={item['vector_score']}"
        )


if __name__ == "__main__":
    main()
