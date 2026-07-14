from __future__ import annotations

import threading
import uuid
from datetime import datetime
from pathlib import Path

from app.services.document_quality import assess_document_quality, lifecycle_event, summarize_document
from app.services.safe_logging import redact_sensitive_text
from app.services.url_importer import fetch_url


class JobCancelled(Exception):
    pass


class IngestionWorker:
    def __init__(self, registry, processor, retriever, settings, *, fetcher=fetch_url):
        self.registry = registry
        self.processor = processor
        self.retriever = retriever
        self.settings = settings
        self.fetcher = fetcher
        self.worker_id = f"local-{uuid.uuid4().hex[:10]}"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.registry.recover_stale_index_jobs()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="rag-index-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            if not self.run_once():
                self._stop.wait(self.settings.ingestion_poll_seconds)

    def run_once(self) -> bool:
        job = self.registry.claim_next_index_job(
            worker_id=self.worker_id,
            lease_seconds=self.settings.ingestion_lease_seconds,
        )
        if not job:
            return False
        try:
            self._process(job)
        except JobCancelled:
            self.registry.request_index_job_cancel(job["id"])
            self._cleanup_staged_file(job)
        except Exception as exc:
            failed = self.registry.fail_index_job(job["id"], "INGESTION_FAILED", redact_sensitive_text(exc))
            if failed and failed["status"] in {"failed", "cancelled"}:
                self._cleanup_staged_file(job)
        return True

    def _process(self, job: dict) -> None:
        self._check_cancel(job["id"])
        self.registry.update_index_job(job["id"], stage="parse", progress=20)
        parse_started = datetime.utcnow()
        if job["source_type"] == "file":
            path = Path(job["payload"]["staged_path"])
            if not path.is_file():
                raise ValueError("Staged upload is unavailable")
            document = self.processor.parse_file(path, original_name=job["source_name"])
        elif job["source_type"] == "url":
            imported = self.fetcher(
                job["payload"]["url"],
                title=job["payload"].get("title", ""),
                timeout=self.settings.url_import_timeout_seconds,
                max_bytes=self.settings.url_import_max_bytes,
            )
            document = self.processor.parse_text_source(
                imported.text,
                imported.filename,
                source_url=imported.url,
                parser=imported.metadata.get("parser", "url_html"),
                metadata=imported.metadata,
            )
            document.title = imported.title
        else:
            raise ValueError("Unsupported ingestion source")
        parse_ended = datetime.utcnow()
        document.metadata.update(
            {
                "knowledge_base_id": job["knowledge_base_id"],
                "chunker_version": self.settings.chunker_version,
                "embedding_provider": self.settings.embedding_provider,
                "embedding_model": self.settings.embedding_model,
                "embedding_dimension": self.settings.resolved_embedding_dimension(),
                "index_version": self.settings.index_version,
            }
        )
        existing = self.registry.find_by_content_hash(
            str(document.metadata.get("content_hash") or ""),
            job["knowledge_base_id"],
        )
        if existing:
            self.registry.complete_index_job(job["id"], existing.document_id, deduped=True)
            self._cleanup_staged_file(job)
            return

        self._check_cancel(job["id"])
        self.registry.update_index_job(job["id"], stage="chunk", progress=45)
        split_started = datetime.utcnow()
        chunks = self.processor.split(document)
        split_ended = datetime.utcnow()
        self._check_cancel(job["id"])
        self.registry.update_index_job(job["id"], stage="embed", progress=65)
        index_started = datetime.utcnow()
        self.retriever.add_document(document, chunks)
        index_ended = datetime.utcnow()
        self._check_cancel(job["id"])
        self.registry.update_index_job(job["id"], stage="quality", progress=90)
        document.metadata["index_status"] = "indexed"
        document.metadata["lifecycle"] = [
            lifecycle_event("parse", "success", parse_started, parse_ended),
            lifecycle_event("chunk", "success", split_started, split_ended),
            lifecycle_event("index", "success", index_started, index_ended),
        ]
        document.metadata["quality"] = assess_document_quality(document, chunks)
        document.metadata["summary"] = summarize_document(document, chunks)
        self.registry.save_document(document)
        self.registry.complete_index_job(job["id"], document.document_id)
        self.registry.log_operation(
            "index_job_succeeded",
            f"后台索引完成：{document.file_name}",
            {"job_id": job["id"], "document_id": document.document_id, "chunk_count": len(chunks)},
        )

    def _check_cancel(self, job_id: str) -> None:
        current = self.registry.get_index_job(job_id)
        if not current or current["cancel_requested"] or self._stop.is_set():
            raise JobCancelled()

    def _cleanup_staged_file(self, job: dict) -> None:
        if job.get("source_type") != "file":
            return
        path = Path(str(job.get("payload", {}).get("staged_path") or ""))
        if path.name:
            path.unlink(missing_ok=True)
