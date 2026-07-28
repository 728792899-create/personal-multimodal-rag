from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from app.services.document_quality import assess_document_quality, lifecycle_event, summarize_document
from app.services.safe_logging import public_error_message, redact_sensitive_text
from app.services.url_importer import fetch_url
from app.services.object_store import LocalObjectStore
from app.services.parser_worker import ParserJobCancelled, document_from_content_list
from app.services.multimodal_assets import materialize_document_assets
from app.services.production_metrics import production_metrics


logger = logging.getLogger(__name__)


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
        job_signal_queue=None,
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
        self.job_signal_queue = job_signal_queue
        self.worker_id = f"local-{uuid.uuid4().hex[:10]}"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_stale_recovery_at = 0.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.reconcile_orphaned_vectors()
        self.registry.recover_stale_index_jobs()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="rag-index-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        self._thread = None

    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def reconcile_orphaned_vectors(self) -> int:
        known = {
            document.document_id
            for document in self.registry.load_documents()
        }
        vector_store = getattr(self.retriever, "vector_store", None)
        chunks = getattr(vector_store, "chunks", {})
        orphaned = {
            chunk.document_id
            for chunk in chunks.values()
            if chunk.document_id not in known
        }
        for document_id in orphaned:
            self.retriever.delete_document(document_id)
        if orphaned:
            self.registry.log_operation(
                "orphan_vectors_reconciled",
                "已清理未关联文档的向量",
                {"document_count": len(orphaned)},
            )
        return len(orphaned)

    def _loop(self) -> None:
        while not self._stop.is_set():
            message = None
            if self.job_signal_queue is not None:
                try:
                    message = self.job_signal_queue.wait(
                        max(self.settings.ingestion_poll_seconds, 0.1)
                    )
                except Exception:
                    self._stop.wait(self.settings.ingestion_poll_seconds)
            if message is not None and self._ack_terminal_signal(message):
                continue
            try:
                processed = self.run_once()
            except Exception as exc:
                processed = False
                logger.warning(
                    "index worker poll failed; retrying error_type=%s",
                    type(exc).__name__,
                )
            if message is not None:
                try:
                    self.job_signal_queue.acknowledge(message.message_id)
                except Exception:
                    pass
            if not processed and self.job_signal_queue is None:
                self._stop.wait(self.settings.ingestion_poll_seconds)

    def _ack_terminal_signal(self, message) -> bool:
        """Acknowledge a stale signal whose durable job is already terminal."""

        try:
            job = self.registry.get_index_job(message.aggregate_id)
        except Exception:
            return False
        if not job or job.get("status") not in {"succeeded", "failed", "cancelled"}:
            return False
        try:
            self.job_signal_queue.acknowledge(message.message_id)
        except Exception:
            return False
        return True

    def run_once(self) -> bool:
        self._recover_stale_periodically()
        job = self.registry.claim_next_index_job(
            worker_id=self.worker_id,
            lease_seconds=self.settings.ingestion_lease_seconds,
        )
        if not job:
            return False
        started_at = time.perf_counter()
        final_status = "succeeded"
        heartbeat_stop = threading.Event()
        heartbeat = threading.Thread(
            target=self._lease_heartbeat,
            args=(job["id"], heartbeat_stop),
            name=f"rag-index-lease-{job['id'][:8]}",
            daemon=True,
        )
        heartbeat.start()
        try:
            self._process(job)
        except JobCancelled:
            final_status = "cancelled"
            self.registry.complete_index_job_cancellation(job["id"])
            self._mark_source_item(job, "", "cancelled")
        except Exception as exc:
            final_status = "failed"
            self.registry.fail_index_job(
                job["id"],
                "INGESTION_FAILED",
                public_error_message(
                    exc,
                    "索引任务处理失败，请检查文件或 Provider 状态后重试。",
                ),
            )
            self._mark_source_item(job, "", "failed")
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=1)
        current = self.registry.get_index_job(job["id"]) or job
        production_metrics.record_job(
            status=final_status,
            seconds=time.perf_counter() - started_at,
            attempts=int(current.get("attempts") or job.get("attempts") or 1),
        )
        return True

    def _recover_stale_periodically(self) -> None:
        now = time.monotonic()
        if now - self._last_stale_recovery_at < 10:
            return
        self.registry.recover_stale_index_jobs()
        self._last_stale_recovery_at = now

    def _lease_heartbeat(
        self,
        job_id: str,
        stopped: threading.Event,
    ) -> None:
        lease_seconds = max(3, int(self.settings.ingestion_lease_seconds))
        interval = max(1.0, min(30.0, lease_seconds / 3))
        while not stopped.wait(interval):
            try:
                renewed = self.registry.renew_index_job_lease(
                    job_id,
                    self.worker_id,
                    lease_seconds,
                )
            except Exception:
                continue
            if not renewed:
                return

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
                raise ValueError("原始文件对象不可用，请重新上传。")
            use_worker = parser_profile in {"mineru", "docling", "paddleocr"} or (
                parser_profile == "auto" and str(self.settings.parser_provider).lower() != "builtin"
            )
            if use_worker:
                if self.parser_client is None:
                    raise ValueError("未配置解析 Worker。")
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
                        "parser_fallback_reason": public_error_message(
                            exc,
                            "高级解析失败，已回退到内置解析器。",
                        ),
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
            raise ValueError("不支持该入库来源。")
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
        if job["payload"].get("source_item_id"):
            document.metadata.update(
                {
                    "source_id": str(job["payload"].get("source_id") or ""),
                    "source_item_id": str(job["payload"]["source_item_id"]),
                    "source_location": str(job["payload"].get("source_location") or ""),
                }
            )
        existing = self.registry.find_by_content_hash(
            str(document.metadata.get("content_hash") or ""),
            job["knowledge_base_id"],
        )
        if existing:
            asset_id = str(job["payload"].get("asset_id") or "")
            if asset_id:
                self.registry.link_asset(asset_id, existing.document_id)
            else:
                staged_path = Path(
                    str(job["payload"].get("staged_path") or "")
                )
                if staged_path.name:
                    staged_path.unlink(missing_ok=True)
            self.registry.complete_index_job(job["id"], existing.document_id, deduped=True)
            self._mark_source_item(job, existing.document_id, "active")
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
        self._persist_new_document(
            job,
            document,
            chunks,
            parser_provider=parser_provider,
            parse_started=parse_started,
            parse_ended=parse_ended,
            enrich_modalities=enrich_modalities,
            enrichment_started=enrichment_started,
            enrichment_ended=enrichment_ended,
            split_started=split_started,
            split_ended=split_ended,
        )

    def _persist_new_document(
        self,
        job: dict,
        document,
        chunks,
        *,
        parser_provider: str,
        parse_started: datetime,
        parse_ended: datetime,
        enrich_modalities: bool,
        enrichment_started: datetime,
        enrichment_ended: datetime,
        split_started: datetime,
        split_ended: datetime,
    ) -> None:
        self._check_cancel(job["id"])
        self.registry.update_index_job(job["id"], stage="embed", progress=65)
        index_started = datetime.utcnow()
        index_attempted = True
        try:
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
                payload={
                    "element_count": len(document.elements),
                    "parser_profile": job["payload"].get(
                        "parser_profile",
                        "builtin",
                    ),
                },
            )
            self.registry.complete_index_job(job["id"], document.document_id)
            self._mark_source_item(job, document.document_id, "active")
            self.registry.log_operation(
                "index_job_succeeded",
                f"后台索引完成：{document.file_name}",
                {
                    "job_id": job["id"],
                    "document_id": document.document_id,
                    "chunk_count": len(chunks),
                },
            )
        except Exception:
            if (
                index_attempted
                and self.registry.get_document(document.document_id) is None
            ):
                self.retriever.delete_document(document.document_id)
            raise

    def _check_cancel(self, job_id: str) -> None:
        if self._cancel_requested(job_id):
            raise JobCancelled()

    def _cancel_requested(self, job_id: str) -> bool:
        current = self.registry.get_index_job(job_id)
        return not current or bool(current["cancel_requested"]) or self._stop.is_set()

    def _mark_source_item(self, job: dict, document_id: str, status: str) -> None:
        source_item_id = str(job.get("payload", {}).get("source_item_id") or "")
        if not source_item_id:
            return
        if document_id:
            previous = self.registry.get_source_item(source_item_id)
            self.registry.mark_source_item_indexed(source_item_id, document_id)
            previous_document_id = str(previous.get("document_id") or "") if previous else ""
            if (
                previous_document_id
                and previous_document_id != document_id
                and self.registry.source_item_document_reference_count(previous_document_id) == 0
            ):
                assets = self.registry.list_assets(
                    document_id=previous_document_id,
                    include_private=True,
                )
                self.retriever.delete_document(previous_document_id)
                self.registry.delete_document(previous_document_id)
                for asset in assets:
                    if self.registry.asset_reference_count(asset["object_key"]) == 0:
                        self.object_store.delete(asset["object_key"])
        else:
            self.registry.update_source_item_status(source_item_id, status)
