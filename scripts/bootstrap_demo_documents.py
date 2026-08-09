from __future__ import annotations

import json
import mimetypes
import os
import sys
from pathlib import Path
from urllib import request


ROOT = Path(__file__).resolve().parents[1]
API_BASE = os.getenv("RAG_API_BASE", "http://127.0.0.1:8010").rstrip("/")
SAMPLES = ROOT / "samples" / "demo-documents"


DEMO_CASES = [
    {
        "question": "这个 RAG 系统的核心工程亮点是什么？",
        "expected_keywords": ["混合检索", "引用审计", "反馈评测"],
    },
    {
        "question": "这个系统如何通过引用和拒答机制降低幻觉？",
        "expected_keywords": ["引用", "拒答", "评测"],
    },
    {
        "question": "AIGC 工作流资料里提到了哪些工程能力？",
        "expected_keywords": ["Vue", "RAG", "工程"],
    },
    {
        "question": "这份资料有没有提到 Kubernetes 部署？",
        "expected_keywords": [],
    },
]


def main() -> None:
    health = get_json("/health")
    if health.get("status") != "ok":
        raise SystemExit("后端健康检查未通过。请运行：cd backend && python3 -m uvicorn app.main:app --reload --port 8010")

    files = sorted(SAMPLES.glob("*.md"))
    if not files:
        raise SystemExit(f"在 {SAMPLES} 下未找到演示文件。")

    print("正在上传演示文档……")
    for file_path in files:
        result = upload_file(file_path)
        doc = result.get("document", {})
        status = "deduped" if result.get("deduped") else "indexed"
        print(f"- {status}: {doc.get('filename')} chunks={doc.get('chunk_count')}")

    print("正在创建评测用例……")
    for case in DEMO_CASES:
        created = post_json("/api/eval/cases", case)
        print(f"- 用例：{created.get('case', {}).get('question')}")

    print("\n演示问题：")
    for case in DEMO_CASES:
        print(f"- {case['question']}")

    print("\n打开工作台：http://127.0.0.1:5173")


def get_json(path: str) -> dict:
    with request.urlopen(f"{API_BASE}{path}", timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(path: str, payload: dict) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        f"{API_BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def upload_file(file_path: Path) -> dict:
    boundary = "----DemoDocumentsBoundary"
    content_type = mimetypes.guess_type(file_path.name)[0] or "text/markdown"
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'.encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            file_path.read_bytes(),
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    req = request.Request(
        f"{API_BASE}/api/documents",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"演示资料初始化失败：{exc}", file=sys.stderr)
        raise
