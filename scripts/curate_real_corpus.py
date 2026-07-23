#!/usr/bin/env python3
"""Build a licensed bilingual corpus from live Wikipedia revisions.

Downloaded material is operator evidence under ``data/`` and is intentionally
excluded from Git. Each document retains its canonical URL, revision ID,
retrieval time, license metadata, and SHA-256 digest.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SEARCH_TERMS = {
    "en": [
        "information retrieval",
        "retrieval augmented generation",
        "natural language processing",
        "machine learning",
        "computer vision",
        "database systems",
        "distributed systems",
        "computer security",
        "software engineering",
        "knowledge graph",
        "digital libraries",
        "open source software",
    ],
    "zh": [
        "信息检索",
        "检索增强生成",
        "自然语言处理",
        "机器学习",
        "计算机视觉",
        "数据库",
        "分布式系统",
        "计算机安全",
        "软件工程",
        "知识图谱",
        "数字图书馆",
        "开放源代码",
    ],
}
USER_AGENT = (
    "PersonalMultimodalRAG/0.4 corpus-validation "
    "(https://github.com/728792899-create/personal-multimodal-rag)"
)
GITHUB_REPOSITORIES = [
    "fastapi/fastapi",
    "vitejs/vite",
    "encode/httpx",
    "encode/starlette",
    "pytest-dev/pytest",
    "pydantic/pydantic",
    "pallets/flask",
    "django/django",
    "tiangolo/sqlmodel",
    "chroma-core/chroma",
    "minio/minio",
    "ollama/ollama",
    "docling-project/docling",
    "PaddlePaddle/PaddleOCR",
    "pandas-dev/pandas",
    "scikit-learn/scikit-learn",
    "huggingface/transformers",
    "langchain-ai/langchain",
    "HKUDS/RAG-Anything",
    "psf/requests",
    "urllib3/urllib3",
    "sqlalchemy/sqlalchemy",
    "sqlalchemy/alembic",
    "boto/boto3",
    "prometheus/prometheus",
    "grafana/grafana",
    "open-telemetry/opentelemetry-python",
    "getsentry/sentry-python",
    "encode/uvicorn",
]
ALLOWED_LICENSES = {
    "AGPL-3.0",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "MIT",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def slugify(value: str, limit: int = 72) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    normalized = re.sub(r"[^\w\u3400-\u9fff-]+", "-", normalized, flags=re.UNICODE)
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return (normalized or "article")[:limit].rstrip("-")


def api(language: str, params: dict, *, attempts: int = 4) -> dict:
    endpoint = f"https://{language}.wikipedia.org/w/api.php"
    query = {
        "format": "json",
        "formatversion": "2",
        "utf8": "1",
        **params,
    }
    request = Request(
        f"{endpoint}?{urlencode(query)}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    raise RuntimeError(f"Wikipedia API failed for {language}: {type(last_error).__name__}")


def rights(language: str) -> dict:
    payload = api(
        language,
        {"action": "query", "meta": "siteinfo", "siprop": "rightsinfo"},
    )
    value = payload.get("query", {}).get("rightsinfo", {})
    return {
        "name": str(value.get("text") or ""),
        "url": str(value.get("url") or ""),
    }


def discover_page_ids(language: str, needed: int) -> list[int]:
    found: list[int] = []
    seen: set[int] = set()
    for term in SEARCH_TERMS[language]:
        payload = api(
            language,
            {
                "action": "query",
                "list": "search",
                "srsearch": term,
                "srnamespace": "0",
                "srlimit": "50",
            },
        )
        for item in payload.get("query", {}).get("search", []):
            page_id = int(item.get("pageid") or 0)
            if page_id and page_id not in seen:
                seen.add(page_id)
                found.append(page_id)
        if len(found) >= needed * 2:
            break
    return found


def fetch_pages(language: str, page_ids: list[int]) -> list[dict]:
    pages: list[dict] = []
    for offset in range(0, len(page_ids), 20):
        payload = api(
            language,
            {
                "action": "query",
                "pageids": "|".join(str(value) for value in page_ids[offset : offset + 20]),
                "prop": "extracts|info|revisions",
                "explaintext": "1",
                "exsectionformat": "plain",
                "inprop": "url",
                "rvprop": "ids|timestamp",
                "redirects": "1",
            },
        )
        pages.extend(payload.get("query", {}).get("pages", []))
    return pages


def render_document(page: dict, *, language: str, license_info: dict, retrieved_at: str) -> bytes:
    title = str(page["title"]).strip()
    revision = (page.get("revisions") or [{}])[0]
    metadata = {
        "source": "Wikipedia",
        "source_url": page.get("canonicalurl") or page.get("fullurl") or "",
        "language": language,
        "page_id": page.get("pageid"),
        "revision_id": revision.get("revid"),
        "revision_timestamp": revision.get("timestamp"),
        "retrieved_at": retrieved_at,
        "license_name": license_info["name"],
        "license_url": license_info["url"],
    }
    header = "\n".join(
        [
            "---",
            *(f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in metadata.items()),
            "---",
            "",
            f"# {title}",
            "",
        ]
    )
    extract = str(page.get("extract") or "").strip()[:120_000]
    return (header + extract + "\n").encode("utf-8")


def verify_manifest(output: Path, manifest: dict, *, minimum_documents: int) -> dict:
    documents = manifest.get("documents") if isinstance(manifest.get("documents"), list) else []
    errors: list[str] = []
    hashes: set[str] = set()
    sources: set[str] = set()
    for item in documents:
        relative = Path(str(item.get("file") or ""))
        path = (output / relative).resolve()
        if output.resolve() not in path.parents or not path.is_file():
            errors.append(f"missing or unsafe corpus file: {relative}")
            continue
        digest = sha256(path.read_bytes())
        if digest != item.get("sha256"):
            errors.append(f"checksum mismatch: {relative}")
        if digest in hashes:
            errors.append(f"duplicate content hash: {relative}")
        hashes.add(digest)
        source_url = str(item.get("source_url") or "")
        if not source_url or source_url in sources:
            errors.append(f"missing or duplicate source URL: {relative}")
        sources.add(source_url)
        if not item.get("license_name") or not item.get("license_url"):
            errors.append(f"license metadata missing: {relative}")
    if len(documents) < minimum_documents:
        errors.append(f"only {len(documents)} documents; {minimum_documents} required")
    return {
        "valid": not errors,
        "documents": len(documents),
        "unique_hashes": len(hashes),
        "unique_sources": len(sources),
        "licenses": sorted(
            {
                f"{item.get('license_name')} — {item.get('license_url')}"
                for item in documents
                if item.get("license_name") and item.get("license_url")
            }
        ),
        "errors": errors,
    }


def build_wikipedia(output: Path, *, per_language: int) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    retrieved_at = utc_now()
    documents: list[dict] = []
    for language in ("en", "zh"):
        license_info = rights(language)
        if not license_info["name"] or not license_info["url"]:
            raise RuntimeError(f"Wikipedia did not return license metadata for {language}")
        candidates = fetch_pages(
            language,
            discover_page_ids(language, per_language),
        )
        accepted = 0
        for page in candidates:
            if accepted >= per_language:
                break
            extract = str(page.get("extract") or "").strip()
            revision = (page.get("revisions") or [{}])[0]
            source_url = str(page.get("canonicalurl") or page.get("fullurl") or "")
            if len(extract) < 800 or not source_url or not revision.get("revid"):
                continue
            filename = (
                f"{language}-{int(page['pageid'])}-"
                f"{slugify(str(page['title']))}.md"
            )
            payload = render_document(
                page,
                language=language,
                license_info=license_info,
                retrieved_at=retrieved_at,
            )
            target = output / filename
            temporary = target.with_suffix(".tmp")
            temporary.write_bytes(payload)
            os.replace(temporary, target)
            documents.append(
                {
                    "file": filename,
                    "title": page["title"],
                    "language": language,
                    "source_url": source_url,
                    "page_id": page["pageid"],
                    "revision_id": revision["revid"],
                    "revision_timestamp": revision.get("timestamp"),
                    "retrieved_at": retrieved_at,
                    "license_name": license_info["name"],
                    "license_url": license_info["url"],
                    "bytes": len(payload),
                    "sha256": sha256(payload),
                }
            )
            accepted += 1
        if accepted < per_language:
            raise RuntimeError(
                f"only {accepted} suitable {language} documents found; {per_language} required"
            )
    manifest = {
        "schema_version": 1,
        "corpus_id": f"wikipedia-bilingual-{retrieved_at[:10]}",
        "created_at": retrieved_at,
        "non_fixture": True,
        "documents": documents,
    }
    temporary = output / "corpus-manifest.json.tmp"
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, output / "corpus-manifest.json")
    return manifest


def gh_api(endpoint: str) -> dict:
    result = subprocess.run(
        ["gh", "api", endpoint],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
    )
    if result.returncode:
        raise RuntimeError(
            f"GitHub API failed for {endpoint}: "
            f"{result.stderr.strip().splitlines()[-1] if result.stderr.strip() else 'unknown error'}"
        )
    return json.loads(result.stdout)


def github_document_paths(tree: dict, *, per_repository: int) -> list[dict]:
    candidates: list[tuple[tuple[int, int, int, str], dict]] = []
    for item in tree.get("tree", []):
        path = str(item.get("path") or "")
        lower = path.lower()
        size = int(item.get("size") or 0)
        if (
            item.get("type") != "blob"
            or not lower.endswith((".md", ".markdown", ".rst", ".txt"))
            or size < 800
            or size > 200_000
            or any(
                part in lower
                for part in (
                    "node_modules/",
                    "vendor/",
                    "fixtures/",
                    "testdata/",
                    "tests/",
                    "changelog",
                    "history",
                    "code_of_conduct",
                    "security.md",
                )
            )
        ):
            continue
        preferred = 0 if lower.startswith(("docs/", "doc/", "documentation/")) else 1
        readme = 0 if Path(lower).name.startswith("readme") else 1
        chinese_path = (
            0
            if any(
                marker in lower
                for marker in (
                    "/zh/",
                    "/zh-cn/",
                    "/zh_cn/",
                    "readme_zh",
                    "readme-cn",
                    "chinese",
                )
            )
            else 1
        )
        candidates.append(((chinese_path, preferred, readme, lower), item))
    return [item for _, item in sorted(candidates, key=lambda value: value[0])[:per_repository]]


def detect_language(content: str) -> str:
    chinese = len(re.findall(r"[\u3400-\u9fff]", content))
    return "zh" if chinese / max(1, len(content)) >= 0.01 else "en"


def render_github_document(
    content: str,
    *,
    repository: str,
    commit: str,
    path: str,
    license_id: str,
    license_url: str,
    retrieved_at: str,
) -> bytes:
    source_url = f"https://github.com/{repository}/blob/{commit}/{path}"
    metadata = {
        "source": "GitHub",
        "repository": repository,
        "source_url": source_url,
        "commit": commit,
        "path": path,
        "retrieved_at": retrieved_at,
        "license_name": license_id,
        "license_url": license_url,
    }
    header = "\n".join(
        [
            "---",
            *(f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in metadata.items()),
            "---",
            "",
        ]
    )
    return (header + content.strip() + "\n").encode("utf-8")


def build_github(
    output: Path,
    *,
    target_documents: int,
    minimum_repositories: int = 20,
    per_repository: int = 10,
) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    retrieved_at = utc_now()
    documents: list[dict] = []
    content_hashes: set[str] = set()
    repositories_used: set[str] = set()
    failures: list[str] = []
    for repository in GITHUB_REPOSITORIES:
        if len(documents) >= target_documents and len(repositories_used) >= minimum_repositories:
            break
        try:
            info = gh_api(f"repos/{repository}")
            branch = str(info["default_branch"])
            commit = str(
                gh_api(f"repos/{repository}/commits/{branch}")["sha"]
            )
            license_payload = gh_api(f"repos/{repository}/license")
            license_id = str(license_payload.get("license", {}).get("spdx_id") or "")
            license_url = str(license_payload.get("html_url") or "")
            if license_id not in ALLOWED_LICENSES or not license_url:
                failures.append(f"{repository}: unsupported or unrecognized license {license_id}")
                continue
            tree = gh_api(f"repos/{repository}/git/trees/{commit}?recursive=1")
            accepted_from_repo = 0
            for item in github_document_paths(tree, per_repository=per_repository):
                if len(documents) >= target_documents and accepted_from_repo:
                    break
                blob = gh_api(f"repos/{repository}/git/blobs/{item['sha']}")
                if blob.get("encoding") != "base64":
                    continue
                try:
                    content = base64.b64decode(blob["content"]).decode("utf-8")
                except (ValueError, UnicodeDecodeError):
                    continue
                if len(content.strip()) < 800:
                    continue
                payload = render_github_document(
                    content,
                    repository=repository,
                    commit=commit,
                    path=item["path"],
                    license_id=license_id,
                    license_url=license_url,
                    retrieved_at=retrieved_at,
                )
                digest = sha256(payload)
                if digest in content_hashes:
                    continue
                content_hashes.add(digest)
                filename = (
                    f"gh-{repository.replace('/', '-')}-"
                    f"{slugify(Path(item['path']).stem, 48)}-{item['sha'][:10]}.md"
                )
                target = output / filename
                temporary = target.with_suffix(".tmp")
                temporary.write_bytes(payload)
                os.replace(temporary, target)
                source_url = (
                    f"https://github.com/{repository}/blob/{commit}/{item['path']}"
                )
                documents.append(
                    {
                        "file": filename,
                        "title": Path(item["path"]).name,
                        "language": detect_language(content),
                        "repository": repository,
                        "source_url": source_url,
                        "commit": commit,
                        "source_path": item["path"],
                        "retrieved_at": retrieved_at,
                        "license_name": license_id,
                        "license_url": license_url,
                        "bytes": len(payload),
                        "sha256": digest,
                    }
                )
                accepted_from_repo += 1
            if accepted_from_repo:
                repositories_used.add(repository)
        except (KeyError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            failures.append(f"{repository}: {type(exc).__name__}")
    final_documents = documents[:target_documents]
    final_repositories = {
        str(item["repository"]) for item in final_documents
    }
    if len(final_documents) < target_documents:
        raise RuntimeError(
            f"only {len(documents)} licensed GitHub documents collected; "
            f"{target_documents} required"
        )
    if len(final_repositories) < minimum_repositories:
        raise RuntimeError(
            f"only {len(final_repositories)} licensed repositories represented; "
            f"{minimum_repositories} required"
        )
    kept_files = {str(item["file"]) for item in final_documents}
    for path in output.glob("gh-*.md"):
        if path.name not in kept_files:
            path.unlink()
    manifest = {
        "schema_version": 1,
        "corpus_id": f"github-open-source-{retrieved_at[:10]}",
        "created_at": retrieved_at,
        "non_fixture": True,
        "licensed_materials": len(final_repositories),
        "repositories": sorted(final_repositories),
        "collection_failures": failures,
        "documents": final_documents,
    }
    temporary = output / "corpus-manifest.json.tmp"
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, output / "corpus-manifest.json")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Curate and verify a licensed real corpus")
    parser.add_argument("--output", type=Path, default=Path("data/sources/real-corpus"))
    parser.add_argument("--source", choices=["github", "wikipedia"], default="github")
    parser.add_argument("--target", type=int, default=200)
    parser.add_argument("--per-language", type=int, default=100)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    manifest_path = output / "corpus-manifest.json"
    if args.verify_only:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    elif manifest_path.is_file() and not args.refresh:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = (
            build_github(output, target_documents=max(1, args.target))
            if args.source == "github"
            else build_wikipedia(output, per_language=max(1, args.per_language))
        )
    result = verify_manifest(
        output,
        manifest,
        minimum_documents=(
            max(1, args.target)
            if args.source == "github"
            else max(1, args.per_language) * 2
        ),
    )
    result["licensed_materials"] = int(manifest.get("licensed_materials") or 0)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
