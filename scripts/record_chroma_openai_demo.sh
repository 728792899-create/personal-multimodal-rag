#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

QUESTION="${QUESTION:-如何优化 RAG 的召回质量？}"
DURATION="${DURATION:-45}"
DISPLAY_ID="${DISPLAY_ID:-1}"
OUT_DIR="$ROOT/demo-recordings"
OUT_FILE="$OUT_DIR/chroma-openai-$(date +%Y%m%d-%H%M%S).mov"
LOG_FILE="$OUT_DIR/dev-server.log"

mkdir -p "$OUT_DIR"

python3 - <<'PY'
import importlib.util
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

root = Path.cwd()
if load_dotenv:
    load_dotenv(root / ".env", override=False)
    load_dotenv(root / "backend" / ".env", override=False)

missing = []
if not os.getenv("OPENAI_API_KEY"):
    missing.append("OPENAI_API_KEY")
for module in ("openai", "chromadb"):
    if importlib.util.find_spec(module) is None:
        missing.append(module)

if missing:
    print("录屏前检查失败：" + ", ".join(missing))
    if "OPENAI_API_KEY" in missing:
        print("请先在项目根目录 .env 写入 OPENAI_API_KEY，本脚本不会打印 key。")
    module_missing = [name for name in missing if name != "OPENAI_API_KEY"]
    if module_missing:
        print("请先安装依赖：python3 -m pip install -r backend/requirements-optional.txt")
    raise SystemExit(1)

try:
    from openai import OpenAI

    kwargs = {"api_key": os.environ["OPENAI_API_KEY"]}
    if os.getenv("OPENAI_BASE_URL"):
        kwargs["base_url"] = os.environ["OPENAI_BASE_URL"]
    client = OpenAI(**kwargs)
    payload = {
        "model": os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
        "input": ["embedding preflight"],
    }
    dimension = os.getenv("EMBEDDING_DIMENSION", "").strip()
    if dimension and dimension != "0":
        payload["dimensions"] = int(dimension)
    response = client.embeddings.create(**payload)
    if not response.data or not response.data[0].embedding:
        raise RuntimeError("empty embedding response")
except Exception as exc:
    print("录屏前检查失败：embedding provider 无法返回向量。")
    print(f"错误类型：{exc.__class__.__name__}")
    if exc.__class__.__name__.endswith("NotFoundError"):
        print("当前 base_url/模型可能只支持 Chat API，没有 embeddings endpoint。")
    if exc.__class__.__name__.endswith("BadRequestError"):
        print("当前模型可能是 Chat/Responses 模型，不能用于 embeddings。")
    raise SystemExit(1)

print("录屏前检查通过：OPENAI_API_KEY 已设置，openai/chromadb 已安装，embedding provider 可返回向量。")
PY

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi

if [ -f "$ROOT/backend/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/backend/.env"
  set +a
fi

export EMBEDDING_PROVIDER="${EMBEDDING_PROVIDER:-openai}"
export EMBEDDING_MODEL="${EMBEDDING_MODEL:-text-embedding-3-small}"
export EMBEDDING_DIMENSION="${EMBEDDING_DIMENSION:-1536}"
export VECTOR_STORE="${VECTOR_STORE:-chroma}"
export CHROMA_PATH="${CHROMA_PATH:-./data/chroma-openai-demo}"
export CHROMA_COLLECTION="${CHROMA_COLLECTION:-personal_knowledge_demo}"
export RERANKER="${RERANKER:-keyword}"
export INITIAL_RETRIEVAL_K="${INITIAL_RETRIEVAL_K:-24}"

npm run dev >"$LOG_FILE" 2>&1 &
DEV_PID=$!
cleanup() {
  kill "$DEV_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

for _ in {1..60}; do
  if curl -fsS "http://127.0.0.1:8010/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

curl -fsS "http://127.0.0.1:8010/health" >/dev/null

for _ in {1..60}; do
  if curl -fsS "http://localhost:5173" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

curl -fsS "http://localhost:5173" >/dev/null

curl -fsS -F "file=@samples/rag-notes.md;type=text/markdown" \
  "http://127.0.0.1:8010/api/documents" >/dev/null

ENCODED_QUESTION="$(python3 - <<'PY'
import os
from urllib.parse import quote
print(quote(os.environ.get("QUESTION", "如何优化 RAG 的召回质量？")))
PY
)"
DEMO_URL="http://localhost:5173/?question=${ENCODED_QUESTION}&autoAsk=1"

echo "即将录制 ${DURATION}s：$OUT_FILE"
echo "录制内容：打开前端、自动提问、展示真实 OpenAI embedding + Chroma 检索 trace。"

(sleep 2; open "$DEMO_URL") &
screencapture -v -V "$DURATION" -D "$DISPLAY_ID" -k "$OUT_FILE"

echo "录屏已保存：$OUT_FILE"
