#!/usr/bin/env python3
"""CLI for Retrieval v2 shadow-index estimation, rebuild and cutover."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.document_processor import DocumentProcessor
from app.services.document_registry import DocumentRegistry
from app.services.embeddings import OpenAICompatibleEmbeddingProvider
from app.services.index_versions import IndexVersionRegistry
from app.services.shadow_index import ShadowIndexRebuilder, estimate_dry_run


def _requires_file_backed_secrets() -> bool:
    """Apply the production secret policy when either runtime signal says so.

    The CLI is also invoked outside the web process, so APP_ENVIRONMENT cannot
    be its only source of truth.  Treating either production marker as
    authoritative prevents a missing or misspelled APP_ENVIRONMENT from
    weakening a RAG_RUNTIME_MODE=production launch.
    """

    production_markers = {"production", "prod"}
    app_environment = os.getenv("APP_ENVIRONMENT", "").strip().lower()
    runtime_mode = os.getenv("RAG_RUNTIME_MODE", "").strip().lower()
    return app_environment in production_markers or runtime_mode in production_markers


def _secret(name: str) -> str:
    value = os.getenv(name, "")
    file_path = os.getenv(f"{name}_FILE", "").strip()
    if _requires_file_backed_secrets():
        if value and not file_path:
            raise ValueError(
                f"{name} must be supplied through {name}_FILE in production"
            )
        return Path(file_path).read_text(encoding="utf-8").strip() if file_path else ""
    if value:
        return value
    return Path(file_path).read_text(encoding="utf-8").strip() if file_path else ""


def _write_report(report: dict, output: str) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if not output:
        print(rendered, end="")
        return
    target = Path(output).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    os.replace(temporary, target)


def main() -> int:
    parser = argparse.ArgumentParser(description="Retrieval v2 影子索引工具")
    parser.add_argument(
        "action",
        choices=("dry-run", "rebuild", "validate", "promote", "activate", "rollback"),
    )
    parser.add_argument("--index-id", default="")
    parser.add_argument(
        "--metadata-registry",
        default=_secret("METADATA_DSN")
        or os.getenv("DOCUMENT_REGISTRY_PATH", "./data/registry.sqlite3"),
    )
    parser.add_argument("--vector-dsn", default=_secret("PGVECTOR_DSN"))
    parser.add_argument("--index-registry", default="")
    parser.add_argument(
        "--parser-version",
        default=os.getenv("PARSER_VERSION", "builtin-elements-v1"),
    )
    parser.add_argument("--chunker-version", default="structure-v2")
    parser.add_argument("--dry-run-percent", type=int, default=10)
    parser.add_argument("--execute-provider", action="store_true")
    parser.add_argument("--price-per-million-tokens", type=float, default=0.13)
    parser.add_argument("--benchmark-samples", type=int, default=100)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    documents = DocumentRegistry(args.metadata_registry).load_documents()
    processor = DocumentProcessor()
    if args.action == "dry-run":
        provider = (
            OpenAICompatibleEmbeddingProvider(
                api_key=_secret("OPENAI_API_KEY"),
                model="text-embedding-3-large",
                dimensions=1536,
            )
            if args.execute_provider
            else None
        )
        report = estimate_dry_run(
            documents,
            processor=processor,
            percentage=args.dry_run_percent,
            provider=provider,
            price_per_million_tokens=args.price_per_million_tokens,
        )
        if args.index_id and args.vector_dsn:
            registry = IndexVersionRegistry(args.index_registry or args.vector_dsn)
            if registry.get(args.index_id) is None:
                registry.register_candidate(
                    index_id=args.index_id,
                    parser_version=args.parser_version,
                    chunker_version=args.chunker_version,
                    source_index_id=registry.active().index_id if registry.active() else "",
                )
            registry.record_metrics(args.index_id, {"dry_run": report})
        _write_report(report, args.output)
        return 0

    if args.action != "rollback" and not args.index_id:
        parser.error("--index-id is required for this action")
    if not args.vector_dsn:
        parser.error("--vector-dsn or PGVECTOR_DSN_FILE is required")
    registry = IndexVersionRegistry(args.index_registry or args.vector_dsn)
    if args.action == "rollback":
        report = {"index": registry.rollback().model_dump(), "state": registry.state()}
    elif args.action == "promote":
        report = {"index": registry.promote(args.index_id).model_dump()}
    elif args.action == "activate":
        report = {
            "index": registry.activate(args.index_id).model_dump(),
            "state": registry.state(),
        }
    else:
        if args.action == "rebuild" and registry.get(args.index_id) is None:
            registry.register_candidate(
                index_id=args.index_id,
                parser_version=args.parser_version,
                chunker_version=args.chunker_version,
                source_index_id=registry.active().index_id if registry.active() else "",
            )
        provider = (
            OpenAICompatibleEmbeddingProvider(
                api_key=_secret("OPENAI_API_KEY"),
                model="text-embedding-3-large",
                dimensions=1536,
            )
            if args.action == "rebuild"
            else None
        )
        rebuilder = ShadowIndexRebuilder(
            index_registry=registry,
            vector_dsn=args.vector_dsn,
            embedding_provider=provider,
            processor=processor,
            embedding_price_per_million_tokens=args.price_per_million_tokens,
        )
        report = (
            rebuilder.rebuild(args.index_id, documents)
            if args.action == "rebuild"
            else rebuilder.validate(
                args.index_id,
                documents,
                benchmark_samples=args.benchmark_samples,
            )
        )
    _write_report(report, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
