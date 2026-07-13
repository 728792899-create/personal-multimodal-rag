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


@dataclass
class Settings:
    embedding_provider: str = os.getenv("EMBEDDING_PROVIDER", "mock")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    embedding_dimension: int = int(os.getenv("EMBEDDING_DIMENSION", "0") or "0")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "")

    vector_store: str = os.getenv("VECTOR_STORE", "memory")
    chroma_path: str = os.getenv("CHROMA_PATH", "./data/chroma")
    chroma_collection: str = os.getenv("CHROMA_COLLECTION", "personal_knowledge")
    pgvector_dsn: str = os.getenv("PGVECTOR_DSN", "")
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

    answer_provider: str = os.getenv("ANSWER_PROVIDER", "template")
    answer_model: str = os.getenv("ANSWER_MODEL", os.getenv("OPENAI_MODEL", "gpt-5.5"))
    answer_base_url: str = os.getenv("ANSWER_BASE_URL", os.getenv("OPENAI_BASE_URL", ""))
    answer_api_key: str = os.getenv("ANSWER_API_KEY", os.getenv("OPENAI_API_KEY", ""))
    answer_timeout_seconds: float = float(os.getenv("ANSWER_TIMEOUT_SECONDS", "45"))

    query_rewrite_provider: str = os.getenv("QUERY_REWRITE_PROVIDER", "none")
    query_rewrite_model: str = os.getenv("QUERY_REWRITE_MODEL", os.getenv("ANSWER_MODEL", answer_model))
    query_rewrite_base_url: str = os.getenv("QUERY_REWRITE_BASE_URL", answer_base_url)
    query_rewrite_api_key: str = os.getenv("QUERY_REWRITE_API_KEY", answer_api_key)
    query_rewrite_count: int = int(os.getenv("QUERY_REWRITE_COUNT", "2"))

    document_registry_path: str = os.getenv("DOCUMENT_REGISTRY_PATH", "./data/registry.sqlite3")
    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))
    upload_processing_timeout_seconds: float = float(os.getenv("UPLOAD_PROCESSING_TIMEOUT_SECONDS", "90"))
    url_import_timeout_seconds: float = float(os.getenv("URL_IMPORT_TIMEOUT_SECONDS", "12"))
    url_import_max_bytes: int = int(os.getenv("URL_IMPORT_MAX_BYTES", "2000000"))
    api_auth_token: str = os.getenv("API_AUTH_TOKEN", "")
    rate_limit_requests: int = int(os.getenv("RATE_LIMIT_REQUESTS", "120"))
    rate_limit_window_seconds: int = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
    sentry_dsn: str = os.getenv("SENTRY_DSN", "")
    sentry_environment: str = os.getenv("SENTRY_ENVIRONMENT", "local")
    sentry_traces_sample_rate: float = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.05"))
    allow_private_urls: bool = os.getenv("RAG_ALLOW_PRIVATE_URLS", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    def resolved_embedding_dimension(self) -> int:
        if self.embedding_dimension:
            return self.embedding_dimension
        if self.embedding_provider == "openai":
            return 1536
        return 256


settings = Settings()
