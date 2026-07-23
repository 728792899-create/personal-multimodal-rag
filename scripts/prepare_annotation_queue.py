#!/usr/bin/env python3
"""Create and optionally seed a deterministic human-review queue.

Generated questions are candidates only. They never count as human annotations
until a reviewer completes the explicit review workflow in the application.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen


HEADING = re.compile(r"^#{1,4}\s+(.+?)\s*$", re.MULTILINE)


def candidate_for(document: dict, corpus_dir: Path) -> dict:
    path = corpus_dir / str(document["file"])
    text = path.read_text(encoding="utf-8", errors="replace")
    heading_match = HEADING.search(text)
    title = str(document.get("title") or path.stem).strip()
    topic = (heading_match.group(1) if heading_match else title).strip()[:160]
    language = str(document.get("language") or "en")
    question = (
        f"请根据《{title}》说明其中关于“{topic}”的核心结论。"
        if language == "zh"
        else f'According to "{title}", what is the key guidance about "{topic}"?'
    )
    candidate_id = hashlib.sha256(
        f"human-review-v1:{document['sha256']}".encode()
    ).hexdigest()
    return {
        "candidate_id": candidate_id,
        "question": question,
        "expected_keywords": [],
        "expected_answer": "",
        "note": "Machine-prepared candidate; requires explicit human review.",
        "source_ref": str(document["source_url"]),
        "language": language,
        "corpus_sha256": str(document["sha256"]),
        "status": "draft",
        "counts_as_human_annotation": False,
    }


def build_queue(manifest_path: Path, output_path: Path, *, limit: int = 200) -> list[dict]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    documents = manifest.get("documents")
    if not isinstance(documents, list) or len(documents) < limit:
        raise ValueError(f"corpus manifest must contain at least {limit} documents")
    candidates = [
        candidate_for(document, manifest_path.parent)
        for document in documents[:limit]
    ]
    if len({item["candidate_id"] for item in candidates}) != len(candidates):
        raise ValueError("annotation candidates must be unique")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        for candidate in candidates:
            output.write(json.dumps(candidate, ensure_ascii=False, sort_keys=True) + "\n")
    temporary.replace(output_path)
    return candidates


def request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[dict, object]:
    body = json.dumps(payload).encode() if payload is not None else None
    request = Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    with urlopen(request, timeout=30) as response:
        return json.load(response), response.headers


def seed_queue(
    candidates: list[dict],
    *,
    base_url: str,
    password_file: Path,
) -> dict:
    password = password_file.read_text(encoding="utf-8").strip()
    login, login_headers = request_json(
        urljoin(base_url.rstrip("/") + "/", "api/auth/login"),
        method="POST",
        payload={"password": password},
    )
    session = login.get("session") if isinstance(login.get("session"), dict) else {}
    csrf = str(session.get("csrf_token") or "")
    set_cookie = str(login_headers.get("Set-Cookie") or "")
    cookie = set_cookie.split(";", 1)[0]
    if not csrf or not cookie:
        raise RuntimeError("production login did not return session and CSRF credentials")
    response, _ = request_json(
        urljoin(base_url.rstrip("/") + "/", "api/eval/cases:batch"),
        method="POST",
        payload={
            "cases": [
                {
                    key: candidate[key]
                    for key in (
                        "candidate_id",
                        "question",
                        "expected_keywords",
                        "expected_answer",
                        "note",
                        "source_ref",
                    )
                }
                for candidate in candidates
            ]
        },
        headers={"Cookie": cookie, "X-CSRF-Token": csrf},
    )
    return {
        "created": int(response.get("created") or 0),
        "deduped": int(response.get("deduped") or 0),
        "total": len(candidates),
        "summary": (
            response.get("summary")
            if isinstance(response.get("summary"), dict)
            else {}
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare the 1.0 human annotation queue")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/sources/real-corpus/corpus-manifest.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/validation/annotation-candidates.jsonl"),
    )
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--seed", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:5173")
    parser.add_argument("--password-file", type=Path, default=Path("secrets/operator_password"))
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=Path("data/validation/annotation-summary.json"),
    )
    args = parser.parse_args()
    candidates = build_queue(
        args.manifest.expanduser().resolve(),
        args.output.expanduser().resolve(),
        limit=max(1, args.limit),
    )
    result = {
        "candidates": len(candidates),
        "human_reviewed": 0,
        "counts_as_human_annotations": False,
        "output": str(args.output),
    }
    if args.seed:
        result["seed"] = seed_queue(
            candidates,
            base_url=args.base_url,
            password_file=args.password_file.expanduser().resolve(),
        )
        summary = result["seed"].get("summary") or {}
        args.summary_output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.summary_output.with_suffix(
            args.summary_output.suffix + ".tmp"
        )
        temporary.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(args.summary_output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
