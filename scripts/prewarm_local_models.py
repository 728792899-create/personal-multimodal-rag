from __future__ import annotations

import argparse
import importlib.util
import os


def main() -> None:
    parser = argparse.ArgumentParser(description="预下载本地 embedding/reranker 模型。")
    parser.add_argument("--embedding-model", default="BAAI/bge-small-zh-v1.5")
    parser.add_argument("--reranker-model", default="")
    parser.add_argument(
        "--hf-endpoint",
        default=os.getenv("HF_ENDPOINT", ""),
        help="可选 HuggingFace 镜像地址，例如 https://hf-mirror.com",
    )
    args = parser.parse_args()

    if args.hf_endpoint:
        os.environ["HF_ENDPOINT"] = args.hf_endpoint
        print(f"正在使用 HF_ENDPOINT={args.hf_endpoint}")

    if importlib.util.find_spec("sentence_transformers") is None:
        raise SystemExit(
            "尚未安装 sentence-transformers。请运行：\n"
            "python3 -m pip install -r backend/requirements-bge.txt"
        )

    from sentence_transformers import CrossEncoder, SentenceTransformer

    print(f"正在加载 embedding 模型：{args.embedding_model}")
    SentenceTransformer(args.embedding_model)
    print("Embedding 模型已就绪。")

    if args.reranker_model:
        print(f"正在加载 reranker 模型：{args.reranker_model}")
        CrossEncoder(args.reranker_model)
        print("Reranker 模型已就绪。")


if __name__ == "__main__":
    main()
