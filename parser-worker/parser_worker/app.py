from __future__ import annotations

import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import uuid
from pathlib import Path
from threading import RLock

from fastapi import FastAPI, File, Form, HTTPException, UploadFile


ROOT = Path(os.getenv("PARSER_JOB_DIR", "/tmp/parser-jobs")).resolve()
ROOT.mkdir(parents=True, exist_ok=True)
MAX_BYTES = int(os.getenv("PARSER_MAX_BYTES", str(50 * 1024 * 1024)))
PROFILES = {"auto", "mineru", "docling", "paddleocr"}
PROCESSES: dict[str, subprocess.Popen] = {}
LOCK = RLock()

app = FastAPI(title="RAG Parser Worker", version="0.3.0")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/v1/capabilities")
def capabilities():
    raganything = importlib.util.find_spec("raganything") is not None
    return {
        "profiles": [
            {
                "id": profile,
                "available": raganything,
                "formats": [".pdf", ".png", ".jpg", ".jpeg", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".txt", ".md"],
                "capabilities": ["layout", "image", "table", "equation"],
            }
            for profile in ("mineru", "docling", "paddleocr")
        ]
    }


@app.post("/v1/jobs", status_code=202)
async def create_job(file: UploadFile = File(...), profile: str = Form("auto")):
    selected = profile.strip().lower()
    if selected not in PROFILES:
        raise HTTPException(status_code=400, detail="Unsupported parser profile")
    filename = Path((file.filename or "document").replace("\\", "/")).name
    if not filename or filename in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid filename")
    job_id = uuid.uuid4().hex
    job_dir = (ROOT / job_id).resolve()
    if ROOT not in job_dir.parents:
        raise HTTPException(status_code=400, detail="Invalid job path")
    job_dir.mkdir(mode=0o700)
    source = job_dir / f"source{Path(filename).suffix.lower()}"
    written = 0
    try:
        with source.open("wb") as handle:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_BYTES:
                    raise HTTPException(status_code=413, detail="Parser input is too large")
                handle.write(chunk)
        if not written:
            raise HTTPException(status_code=400, detail="Parser input is empty")
        _write(job_dir, {"id": job_id, "status": "queued", "profile": selected, "source_name": filename})
        process = subprocess.Popen(
            [sys.executable, "-m", "parser_worker.runner", str(job_dir), str(source), filename, selected],
            cwd=str(Path(__file__).resolve().parents[1]),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        with LOCK:
            PROCESSES[job_id] = process
        return {"id": job_id, "status": "queued"}
    except Exception:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    finally:
        await file.close()


@app.get("/v1/jobs/{job_id}")
def get_job(job_id: str):
    job_dir = _job_dir(job_id)
    status_file = job_dir / "status.json"
    if not status_file.is_file():
        raise HTTPException(status_code=404, detail="Parser job not found")
    payload = json.loads(status_file.read_text(encoding="utf-8"))
    with LOCK:
        process = PROCESSES.get(job_id)
        if process is not None and process.poll() is not None:
            PROCESSES.pop(job_id, None)
    return payload


@app.delete("/v1/jobs/{job_id}")
def cancel_job(job_id: str):
    job_dir = _job_dir(job_id)
    with LOCK:
        process = PROCESSES.pop(job_id, None)
    if process is not None and process.poll() is None:
        _terminate_process_tree(process)
    current = _read(job_dir)
    if current.get("status") not in {"succeeded", "failed"}:
        current.update({"status": "cancelled", "error": "Parser job cancelled"})
        _write(job_dir, current)
    response = {"id": job_id, "status": current.get("status")}
    shutil.rmtree(job_dir, ignore_errors=True)
    return response


def _terminate_process_tree(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _job_dir(job_id: str) -> Path:
    if not job_id.isalnum():
        raise HTTPException(status_code=400, detail="Invalid parser job id")
    job_dir = (ROOT / job_id).resolve()
    if ROOT not in job_dir.parents or not job_dir.is_dir():
        raise HTTPException(status_code=404, detail="Parser job not found")
    return job_dir


def _read(job_dir: Path) -> dict:
    path = job_dir / "status.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _write(job_dir: Path, payload: dict) -> None:
    temporary = job_dir / "status.json.tmp"
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, job_dir / "status.json")
