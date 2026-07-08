from __future__ import annotations

import argparse
import importlib.util
import os


def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-download local embedding/reranker models.")
    parser.add_argument("--embedding-model", default="BAAI/bge-small-zh-v1.5")
    parser.add_argument("--reranker-model", default="")
    parser.add_argument(
        "--hf-endpoint",
        default=os.getenv("HF_ENDPOINT", ""),
        help="Optional HuggingFace mirror endpoint, for example https://hf-mirror.com",
    )
    args = parser.parse_args()

    if args.hf_endpoint:
        os.environ["HF_ENDPOINT"] = args.hf_endpoint
        print(f"Using HF_ENDPOINT={args.hf_endpoint}")

    if importlib.util.find_spec("sentence_transformers") is None:
        raise SystemExit(
            "sentence-transformers is not installed. Run:\n"
            "python3 -m pip install -r backend/requirements-bge.txt"
        )

    from sentence_transformers import CrossEncoder, SentenceTransformer

    print(f"Loading embedding model: {args.embedding_model}")
    SentenceTransformer(args.embedding_model)
    print("Embedding model ready.")

    if args.reranker_model:
        print(f"Loading reranker model: {args.reranker_model}")
        CrossEncoder(args.reranker_model)
        print("Reranker model ready.")


if __name__ == "__main__":
    main()
