from __future__ import annotations

import threading
import uuid
from datetime import datetime
from pathlib import Path

from app.services.document_quality import assess_document_quality, lifecycle_event, summarize_document
from app.services.safe_logging import redact_sensitive_text
from app.services.url_importer import fetch_url
from app.services.object_store import LocalObjectStore
from app.services.parser_worker import ParserJobCancelled, document_from_content_list
from app.services.multimodal_assets import materialize_document_assets


class JobCancelled(Exception):
    pass


class IngestionWorker:
    def __init__(
        self,
        registry,
        processor,
        retriever,
        settings,
        *,
        fetcher=fetch_url,
        object_store=None,
        parser_client=None,
        enrichment_service=None,
        graph_store=None,
    ):
        self.registry = registry
        self.processor = processor
        self.retriever = retriever
        self.settings = settings
        self.fetcher = fetcher
        self.object_store = object_store or LocalObjectStore(settings.object_store_path)
        self.parser_client = parser_client
        self.enrichment_service = enrichment_service
        self.graph_store = graph_store
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
            self.registry.complete_index_job_cancellation(job["id"])
            self._cleanup_source_asset(job)
        except Exception as exc:
            self.registry.fail_index_job(job["id"], "INGESTION_FAILED", redact_sensitive_text(exc))
        return True

    def _process(self, job: dict) -> None:
        self._check_cancel(job["id"])
        self.registry.update_index_job(job["id"], stage="parse", progress=20)
        parse_started = datetime.utcnow()
        parser_provider = "builtin"
        parser_profile = str(job["payload"].get("parser_profile") or "builtin")
        if job["source_type"] == "file":
            asset_id = str(job["payload"].get("asset_id") or "")
            asset = self.registry.get_asset(asset_id, include_private=True) if asset_id else None
            path = self.object_store.path_for(asset["object_key"]) if asset else Path(str(job["payload"].get("staged_path") or ""))
            if not path.is_file():
                raise ValueError("Durable source object is unavailable")
            use_worker = parser_profile in {"mineru", "docling", "paddleocr"} or (
                parser_profile == "auto" and str(self.settings.parser_provider).lower() != "builtin"
            )
            if use_worker:
                if self.parser_client is None:
                    raise ValueError("Parser worker is not configured")
                try:
                    parsed = self.parser_client.parse(
                        path,
                        job["source_name"],
                        parser_profile,
                        cancel_check=lambda: self._cancel_requested(job["id"]),
                    )
                    document = document_from_content_list(
                        parsed.get("content_list") or [],
                        source_path=path,
                        original_name=job["source_name"],
                        parser_name=str(parsed.get("parser") or parser_profile),
                    )
                    parser_provider = "raganything_worker"
                except ParserJobCancelled as exc:
                    raise JobCancelled() from exc
                except Exception as exc:
                    if not self.settings.parser_fallback_allowed:
                        raise
                    document = self.processor.parse_file(path, original_name=job["source_name"])
                    document.metadata.update({
                        "parser_fallback_from": parser_profile,
                        "parser_fallback_reason": redact_sensitive_text(exc),
                    })
            else:
                document = self.processor.parse_file(path, original_name=job["source_name"])
            document.file_path = str(path)
            if asset:
                document.metadata.update({
                    "source_available": True,
                    "source_asset_id": asset["id"],
                    "source_sha256": asset["sha256"],
                })
                if document.file_type == "image":
                    for element in document.elements:
                        if element.type == "image" and element.metadata.get("source_asset_role"):
                            element.asset_id = asset["id"]
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
                "parser_version": self.settings.parser_version,
                "enrichment_version": self.settings.enrichment_prompt_version,
                "parser_provider": parser_provider,
                "parser_profile": parser_profile,
            }
        )
        existing = self.registry.find_by_content_hash(
            str(document.metadata.get("content_hash") or ""),
            job["knowledge_base_id"],
        )
        if existing:
            self.registry.complete_index_job(job["id"], existing.document_id, deduped=True)
            self._cleanup_source_asset(job)
            return

        self._check_cancel(job["id"])
        self.registry.update_index_job(job["id"], stage="extract_elements", progress=35)
        self._check_cancel(job["id"])
        self.registry.update_index_job(job["id"], stage="enrich_modalities", progress=42)
        enrich_modalities = bool(job["payload"].get("enrich_modalities", True))
        enrichment_started = datetime.utcnow()
        if enrich_modalities and self.enrichment_service is not None:
            self.enrichment_service.enrich_document(document)
        enrichment_ended = datetime.utcnow()
        self._check_cancel(job["id"])
        self.registry.update_index_job(job["id"], stage="chunk", progress=50)
        split_started = datetime.utcnow()
        chunks = self.processor.split(document)
        split_ended = datetime.utcnow()
        self._check_cancel(job["id"])
        self.registry.update_index_job(job["id"], stage="embed", progress=65)
        index_started = datetime.utcnow()
        self.retriever.add_document(document, chunks)
        index_ended = datetime.utcnow()
        self._check_cancel(job["id"])
        self.registry.update_index_job(job["id"], stage="graph_extract", progress=78)
        document.metadata["index_status"] = "indexed"
        document.metadata["lifecycle"] = [
            lifecycle_event("parse", "success", parse_started, parse_ended),
            lifecycle_event(
                "enrich_modalities",
                "success" if enrich_modalities else "skipped",
                enrichment_started,
                enrichment_ended,
            ),
            lifecycle_event("chunk", "success", split_started, split_ended),
            lifecycle_event("index", "success", index_started, index_ended),
        ]
        document.metadata["quality"] = assess_document_quality(document, chunks)
        document.metadata["summary"] = summarize_document(document, chunks)
        self.registry.save_document(document)
        build_graph = bool(job["payload"].get("build_graph", True))
        self.registry.update_index_job(job["id"], stage="graph_write", progress=84)
        if build_graph and self.graph_store is not None:
            document.metadata["graph"] = self.graph_store.build_document(document)
            document.metadata["quality"] = assess_document_quality(document, chunks)
            self.registry.save_document(document)
        self._check_cancel(job["id"])
        self.registry.update_index_job(job["id"], stage="quality", progress=90)
        asset_id = str(job["payload"].get("asset_id") or "")
        if asset_id:
            self.registry.link_asset(asset_id, document.document_id)
        materialize_document_assets(document, self.registry, self.object_store)
        self.registry.create_parser_run(
            document_id=document.document_id,
            job_id=job["id"],
            provider=parser_provider,
            parser=str(document.metadata.get("parser") or "builtin"),
            status="succeeded",
            payload={"element_count": len(document.elements), "parser_profile": job["payload"].get("parser_profile", "builtin")},
        )
        self.registry.complete_index_job(job["id"], document.document_id)
        self.registry.log_operation(
            "index_job_succeeded",
            f"后台索引完成：{document.file_name}",
            {"job_id": job["id"], "document_id": document.document_id, "chunk_count": len(chunks)},
        )

    def _check_cancel(self, job_id: str) -> None:
        if self._cancel_requested(job_id):
            raise JobCancelled()

    def _cancel_requested(self, job_id: str) -> bool:
        current = self.registry.get_index_job(job_id)
        return not current or bool(current["cancel_requested"]) or self._stop.is_set()

    def _cleanup_source_asset(self, job: dict) -> None:
        if job.get("source_type") != "file":
            return
        asset_id = str(job.get("payload", {}).get("asset_id") or "")
        if asset_id:
            asset = self.registry.delete_asset(asset_id)
            if asset and self.registry.asset_reference_count(asset["object_key"]) == 0:
                self.object_store.delete(asset["object_key"])
            return
        path = Path(str(job.get("payload", {}).get("staged_path") or ""))
        if path.name:
            path.unlink(missing_ok=True)
