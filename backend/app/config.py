from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except Exception:
        return

    project_root = Path(__file__).resolve().parents[2]
    backend_root = Path(__file__).resolve().parents[1]
    for env_path in (project_root / ".env", backend_root / ".env"):
        load_dotenv(env_path, override=False)


_load_dotenv()


def _env_or_file(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is not None:
        return value
    secret_path = os.getenv(f"{name}_FILE", "").strip()
    if not secret_path:
        return default
    try:
        return Path(secret_path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError(f"Unable to read {name}_FILE") from exc


@dataclass
class Settings:
    runtime_mode: str = os.getenv("RAG_RUNTIME_MODE", "demo")
    app_environment: str = os.getenv("APP_ENVIRONMENT", "local")
    embedding_provider: str = os.getenv("EMBEDDING_PROVIDER", "mock")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    embedding_dimension: int = int(os.getenv("EMBEDDING_DIMENSION", "0") or "0")
    embedding_batch_size: int = int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))
    openai_api_key: str = _env_or_file("OPENAI_API_KEY")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "")

    vector_store: str = os.getenv("VECTOR_STORE", "memory")
    chroma_path: str = os.getenv("CHROMA_PATH", "./data/chroma")
    chroma_collection: str = os.getenv("CHROMA_COLLECTION", "personal_knowledge")
    pgvector_dsn: str = _env_or_file("PGVECTOR_DSN")
    pgvector_table: str = os.getenv("PGVECTOR_TABLE", "rag_chunks")

    reranker: str = os.getenv("RERANKER", "keyword")
    reranker_model: str = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-base")
    initial_retrieval_k: int = int(os.getenv("INITIAL_RETRIEVAL_K", "24"))
    bm25_weight: float = float(os.getenv("BM25_WEIGHT", "0.62"))
    vector_weight: float = float(os.getenv("VECTOR_WEIGHT", "0.38"))
    no_answer_threshold: float = float(os.getenv("NO_ANSWER_THRESHOLD", "0.05"))
    grounding_min_confidence: float = float(os.getenv("GROUNDING_MIN_CONFIDENCE", "0.15"))
    citation_overlap_threshold: float = float(os.getenv("CITATION_OVERLAP_THRESHOLD", "0.34"))
    mmr_lambda: float = float(os.getenv("MMR_LAMBDA", "0.78"))
    graph_weight: float = float(os.getenv("GRAPH_WEIGHT", "0.25"))
    graph_max_hops: int = int(os.getenv("GRAPH_MAX_HOPS", "2"))
    enrichment_provider: str = os.getenv("ENRICHMENT_PROVIDER", "template")
    enrichment_model: str = os.getenv("ENRICHMENT_MODEL", os.getenv("OPENAI_MODEL", "gpt-5.6"))
    enrichment_base_url: str = os.getenv("ENRICHMENT_BASE_URL", os.getenv("OPENAI_BASE_URL", ""))
    enrichment_api_key: str = _env_or_file("ENRICHMENT_API_KEY", _env_or_file("OPENAI_API_KEY"))
    enrichment_prompt_version: str = os.getenv("ENRICHMENT_PROMPT_VERSION", "multimodal-v1")
    enrichment_image_detail: str = os.getenv("ENRICHMENT_IMAGE_DETAIL", "auto")
    enrichment_context_chars: int = int(os.getenv("ENRICHMENT_CONTEXT_CHARS", "8000"))

    answer_provider: str = os.getenv("ANSWER_PROVIDER", "template")
    answer_model: str = os.getenv("ANSWER_MODEL", os.getenv("OPENAI_MODEL", "gpt-5.6"))
    answer_base_url: str = os.getenv("ANSWER_BASE_URL", os.getenv("OPENAI_BASE_URL", ""))
    answer_api_key: str = _env_or_file("ANSWER_API_KEY", _env_or_file("OPENAI_API_KEY"))
    answer_timeout_seconds: float = float(os.getenv("ANSWER_TIMEOUT_SECONDS", "45"))
    embedding_timeout_seconds: float = float(
        os.getenv("EMBEDDING_TIMEOUT_SECONDS", "120")
    )

    query_rewrite_provider: str = os.getenv("QUERY_REWRITE_PROVIDER", "none")
    query_rewrite_model: str = os.getenv("QUERY_REWRITE_MODEL", os.getenv("ANSWER_MODEL", answer_model))
    query_rewrite_base_url: str = os.getenv("QUERY_REWRITE_BASE_URL", answer_base_url)
    query_rewrite_api_key: str = _env_or_file("QUERY_REWRITE_API_KEY", answer_api_key)
    query_rewrite_count: int = int(os.getenv("QUERY_REWRITE_COUNT", "2"))

    document_registry_path: str = os.getenv("DOCUMENT_REGISTRY_PATH", "./data/registry.sqlite3")
    metadata_backend: str = os.getenv("METADATA_BACKEND", "sqlite")
    metadata_dsn: str = _env_or_file("METADATA_DSN")
    object_store_path: str = os.getenv("OBJECT_STORE_PATH", "./data/objects")
    staging_path: str = os.getenv("RAG_STAGING_PATH", "./data/staging")
    source_roots: str = os.getenv("SOURCE_ROOTS", "")
    source_sync_max_items: int = int(os.getenv("SOURCE_SYNC_MAX_ITEMS", "200"))
    source_sync_max_bytes: int = int(os.getenv("SOURCE_SYNC_MAX_BYTES", str(20 * 1024 * 1024)))
    object_store_backend: str = os.getenv("OBJECT_STORE_BACKEND", "local")
    s3_endpoint_url: str = os.getenv("S3_ENDPOINT_URL", "")
    s3_region: str = os.getenv("S3_REGION", "us-east-1")
    s3_bucket: str = os.getenv("S3_BUCKET", "")
    s3_access_key: str = _env_or_file("S3_ACCESS_KEY")
    s3_secret_key: str = _env_or_file("S3_SECRET_KEY")
    s3_cache_path: str = os.getenv("S3_CACHE_PATH", "./data/object-cache")
    clamav_host: str = os.getenv("CLAMAV_HOST", "")
    clamav_port: int = int(os.getenv("CLAMAV_PORT", "3310"))
    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))
    query_asset_max_bytes: int = int(os.getenv("QUERY_ASSET_MAX_BYTES", str(10 * 1024 * 1024)))
    query_asset_max_count: int = int(os.getenv("QUERY_ASSET_MAX_COUNT", "4"))
    query_asset_ttl_hours: int = int(os.getenv("QUERY_ASSET_TTL_HOURS", "24"))
    query_asset_max_pixels: int = int(os.getenv("QUERY_ASSET_MAX_PIXELS", "40000000"))
    upload_processing_timeout_seconds: float = float(os.getenv("UPLOAD_PROCESSING_TIMEOUT_SECONDS", "90"))
    url_import_timeout_seconds: float = float(os.getenv("URL_IMPORT_TIMEOUT_SECONDS", "12"))
    url_import_max_bytes: int = int(os.getenv("URL_IMPORT_MAX_BYTES", "2000000"))
    fetch_worker_url: str = os.getenv("FETCH_WORKER_URL", "")
    api_auth_token: str = _env_or_file("API_AUTH_TOKEN")
    auth_mode: str = os.getenv("AUTH_MODE", "disabled")
    admin_password_hash: str = _env_or_file("ADMIN_PASSWORD_HASH")
    session_secret: str = _env_or_file("SESSION_SECRET")
    session_ttl_seconds: int = int(os.getenv("SESSION_TTL_SECONDS", "43200"))
    session_cookie_secure: bool = os.getenv(
        "SESSION_COOKIE_SECURE",
        "1" if os.getenv("APP_ENVIRONMENT", "local") == "production" else "0",
    ).strip().lower() in {"1", "true", "yes", "on"}
    rate_limit_requests: int = int(os.getenv("RATE_LIMIT_REQUESTS", "120"))
    rate_limit_window_seconds: int = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
    login_rate_limit_requests: int = int(os.getenv("LOGIN_RATE_LIMIT_REQUESTS", "8"))
    login_rate_limit_window_seconds: int = int(os.getenv("LOGIN_RATE_LIMIT_WINDOW_SECONDS", "300"))
    job_queue_backend: str = os.getenv("JOB_QUEUE_BACKEND", "sqlite")
    redis_url: str = _env_or_file("REDIS_URL")
    embedded_worker: bool = os.getenv("EMBEDDED_WORKER", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    sentry_dsn: str = os.getenv("SENTRY_DSN", "")
    sentry_environment: str = os.getenv("SENTRY_ENVIRONMENT", "local")
    sentry_traces_sample_rate: float = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.05"))
    otel_exporter_otlp_endpoint: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    otel_service_name: str = os.getenv("OTEL_SERVICE_NAME", "personal-multimodal-rag")
    otel_traces_sample_ratio: float = float(os.getenv("OTEL_TRACES_SAMPLE_RATIO", "0.05"))
    release_evidence_path: str = os.getenv("RELEASE_EVIDENCE_PATH", "./data/release-evidence.json")
    allow_private_urls: bool = os.getenv("RAG_ALLOW_PRIVATE_URLS", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    provider_fallback_allowed: bool = os.getenv(
        "PROVIDER_FALLBACK_ALLOWED",
        "1" if os.getenv("APP_ENVIRONMENT", "local") in {"local", "test", "development"} else "0",
    ).strip().lower() in {"1", "true", "yes", "on"}
    chunker_version: str = os.getenv("CHUNKER_VERSION", "paragraph-v1")
    index_version: str = os.getenv("INDEX_VERSION", "multimodal-v1")
    parser_version: str = os.getenv("PARSER_VERSION", "builtin-elements-v1")
    ingestion_poll_seconds: float = float(os.getenv("INGESTION_POLL_SECONDS", "0.10"))
    ingestion_lease_seconds: int = int(os.getenv("INGESTION_LEASE_SECONDS", "120"))
    parser_provider: str = os.getenv("PARSER_PROVIDER", "builtin")
    parser_worker_url: str = os.getenv("PARSER_WORKER_URL", "http://parser-worker:8090")
    parser_timeout_seconds: float = float(os.getenv("PARSER_TIMEOUT_SECONDS", "300"))
    parser_fallback_allowed: bool = os.getenv(
        "PARSER_FALLBACK_ALLOWED",
        "1" if os.getenv("APP_ENVIRONMENT", "local") in {"local", "test", "development"} else "0",
    ).strip().lower() in {"1", "true", "yes", "on"}
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    ollama_chat_model: str = os.getenv("OLLAMA_CHAT_MODEL", "qwen3:8b")
    ollama_embedding_model: str = os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")

    def resolved_embedding_dimension(self) -> int:
        if self.embedding_dimension:
            return self.embedding_dimension
        if self.embedding_provider == "openai":
            return 1536
        return 256


settings = Settings()
