from __future__ import annotations

import hashlib
import json
import time
from app.services.production_metrics import production_metrics
from app.services.safe_logging import redact_sensitive_text


class SourceSyncService:
    def __init__(
        self,
        registry,
        object_store,
        connector_registry,
        settings,
        *,
        retriever=None,
    ):
        self.registry = registry
        self.object_store = object_store
        self.connector_registry = connector_registry
        self.settings = settings
        self.retriever = retriever

    def sync(self, source_id: str) -> dict:
        started_at = time.perf_counter()
        source = self.registry.get_source(source_id)
        if not source:
            raise ValueError("Source not found")
        if not source["enabled"]:
            raise ValueError("Source is disabled")
        run = self.registry.start_sync_run(source_id)
        discovered = unchanged = updated = failed = deletion_candidates = 0
        partial = False
        empty_result = False
        error_message = ""
        try:
            result = self.connector_registry.get(source["type"]).discover(source)
            discovered = len(result.candidates)
            failed = len(result.failures)
            partial = not result.complete
            empty_result = result.empty_result
            error_message = "; ".join(result.failures)

            if result.source_metadata:
                self.registry.update_source(
                    source_id,
                    config={**source["config"], **result.source_metadata},
                )

            seen: set[str] = set()
            for candidate in result.candidates:
                seen.add(candidate.external_id)
                existing = self.registry.find_source_item(source_id, candidate.external_id)
                if (
                    existing
                    and existing["content_hash"] == candidate.content_hash
                    and existing["document_id"]
                    and not existing["deletion_candidate"]
                ):
                    self.registry.upsert_source_item(
                        source_id=source_id,
                        external_id=candidate.external_id,
                        location=candidate.location,
                        title=candidate.title,
                        content_hash=candidate.content_hash,
                        etag=candidate.etag,
                        last_modified=candidate.last_modified,
                        metadata=candidate.metadata,
                        sync_run_id=run["id"],
                    )
                    unchanged += 1
                    continue
                asset_id = ""
                object_key = ""
                item_id = ""
                try:
                    item = self.registry.upsert_source_item(
                        source_id=source_id,
                        external_id=candidate.external_id,
                        location=candidate.location,
                        title=candidate.title,
                        content_hash=candidate.content_hash,
                        etag=candidate.etag,
                        last_modified=candidate.last_modified,
                        metadata=candidate.metadata,
                        sync_run_id=run["id"],
                    )
                    item_id = item["id"]
                    stored = self.object_store.put_bytes(candidate.payload)
                    object_key = stored.object_key
                    asset = self.registry.create_asset(
                        knowledge_base_id=source["knowledge_base_id"],
                        kind="source",
                        object_key=stored.object_key,
                        original_name=candidate.filename,
                        media_type=candidate.media_type,
                        sha256=stored.sha256,
                        size_bytes=stored.size_bytes,
                        metadata={
                            "role": "source_sync",
                            "source_id": source_id,
                            "source_item_id": item["id"],
                            "pending_ingestion": True,
                        },
                    )
                    asset_id = asset["id"]
                    key = self._idempotency_key(source, candidate)
                    job = self.registry.create_index_job(
                        source_type="file",
                        source_name=candidate.filename,
                        payload={
                            "asset_id": asset["id"],
                            "content_hash": candidate.content_hash,
                            "source_id": source_id,
                            "source_item_id": item["id"],
                            "source_location": candidate.location,
                            "parser_profile": "builtin",
                            "enrich_modalities": True,
                            "build_graph": True,
                        },
                        knowledge_base_id=source["knowledge_base_id"],
                        idempotency_key=key,
                    )
                    if job.get("payload", {}).get("asset_id") != asset["id"]:
                        removed = self.registry.delete_asset(asset["id"])
                        asset_id = ""
                        if removed and self.registry.asset_reference_count(stored.object_key) == 0:
                            self.object_store.delete(stored.object_key)
                            object_key = ""
                    if job["status"] in {"failed", "cancelled"}:
                        self.registry.retry_index_job(job["id"])
                    self.registry.update_source_item_status(item["id"], "indexing")
                    updated += 1
                except Exception as exc:
                    if asset_id:
                        self.registry.delete_asset(asset_id)
                    if object_key and self.registry.asset_reference_count(object_key) == 0:
                        self.object_store.delete(object_key)
                    if item_id:
                        self.registry.update_source_item_status(item_id, "failed")
                    failed += 1
                    partial = True
                    error_message = "; ".join(
                        item for item in [error_message, redact_sensitive_text(exc)] if item
                    )

            # A 304, an empty discovery, or any partial failure can never
            # produce deletion candidates.
            if result.complete and not result.empty_result and not result.not_modified:
                deletion_candidates = self.registry.mark_missing_source_items(
                    source_id,
                    seen,
                    threshold=2,
                )

            status = "partial" if partial else "succeeded"
            if failed and not result.candidates:
                status = "failed"
            completed = self.registry.complete_sync_run(
                run["id"],
                status=status,
                discovered=discovered,
                unchanged=unchanged,
                updated=updated,
                deletion_candidates=deletion_candidates,
                failed=failed,
                partial=partial,
                empty_result=empty_result,
                error_message=error_message,
            ) or run
            production_metrics.record_source_sync(completed, source_type=source["type"])
            production_metrics.observe(
                "rag_source_sync_duration_seconds",
                time.perf_counter() - started_at,
                source_type=source["type"],
                status=str(completed.get("status") or "unknown"),
            )
            return completed
        except Exception as exc:
            completed = self.registry.complete_sync_run(
                run["id"],
                status="failed",
                discovered=discovered,
                unchanged=unchanged,
                updated=updated,
                deletion_candidates=0,
                failed=max(1, failed),
                partial=True,
                empty_result=empty_result,
                error_message=redact_sensitive_text(exc),
            ) or run
            production_metrics.record_source_sync(completed, source_type=source["type"])
            production_metrics.observe(
                "rag_source_sync_duration_seconds",
                time.perf_counter() - started_at,
                source_type=source["type"],
                status="failed",
            )
            return completed

    def retry(self, run_id: str) -> dict:
        run = self.registry.get_sync_run(run_id)
        if not run:
            raise ValueError("Sync run not found")
        if run["status"] not in {"failed", "partial"}:
            raise ValueError("Only failed or partial sync runs can be retried")
        return self.sync(run["source_id"])

    def confirm_deletions(self, source_id: str, item_ids: list[str] | None = None) -> dict:
        source = self.registry.get_source(source_id)
        if not source:
            raise ValueError("Source not found")
        selected = set(item_ids or [])
        removed_items = 0
        removed_documents = 0
        for item in self.registry.list_source_items(source_id):
            if not item["deletion_candidate"]:
                continue
            if selected and item["id"] not in selected:
                continue
            document_id = item["document_id"]
            if document_id and self.registry.get_document(document_id):
                if self.retriever is not None:
                    self.retriever.delete_document(document_id)
                assets = self.registry.list_assets(document_id=document_id, include_private=True)
                self.registry.delete_document(document_id)
                for asset in assets:
                    if self.registry.asset_reference_count(asset["object_key"]) == 0:
                        self.object_store.delete(asset["object_key"])
                removed_documents += 1
            self.registry.delete_source_item(item["id"])
            removed_items += 1
        return {
            "source_id": source_id,
            "removed_items": removed_items,
            "removed_documents": removed_documents,
        }

    def _idempotency_key(self, source: dict, candidate) -> str:
        value = {
            "source_id": source["id"],
            "external_id": candidate.external_id,
            "content_hash": candidate.content_hash,
            "chunker": self.settings.chunker_version,
            "embedding_provider": self.settings.embedding_provider,
            "embedding_model": self.settings.embedding_model,
            "embedding_dimension": self.settings.resolved_embedding_dimension(),
            "index_version": self.settings.index_version,
        }
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
