from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path


def write_status(job_dir: Path, payload: dict) -> None:
    temporary = job_dir / "status.json.tmp"
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, job_dir / "status.json")


async def run(job_dir: Path, source: Path, source_name: str, profile: str) -> None:
    write_status(job_dir, {"id": job_dir.name, "status": "running", "profile": profile})
    try:
        from raganything import RAGAnything, RAGAnythingConfig

        selected = "mineru" if profile == "auto" else profile
        config = RAGAnythingConfig(
            working_dir=str(job_dir / "rag-storage"),
            parser=selected,
            parser_output_dir=str(job_dir / "output"),
            display_content_stats=False,
        )
        rag = RAGAnything(config=config)
        content_list, _ = await rag.parse_document(str(source))
        write_status(
            job_dir,
            {
                "id": job_dir.name,
                "status": "succeeded",
                "profile": profile,
                "result": {"parser": selected, "source_name": source_name, "content_list": content_list},
            },
        )
    except Exception as exc:
        write_status(
            job_dir,
            {"id": job_dir.name, "status": "failed", "profile": profile, "error": f"{type(exc).__name__}: {exc}"[:1000]},
        )


if __name__ == "__main__":
    if len(sys.argv) != 5:
        raise SystemExit(2)
    asyncio.run(run(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4]))
