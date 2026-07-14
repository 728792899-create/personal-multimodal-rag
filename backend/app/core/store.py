from app.config import settings
from app.services.document_processor import DocumentProcessor
from app.services.document_registry import DocumentRegistry
from app.services.embeddings import (
    LocalSentenceTransformerEmbeddingProvider,
    MockEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
    OllamaEmbeddingProvider,
)
from app.services.answer_generator import (
    GroundedChatAnswerGenerator,
    ResponsesAnswerGenerator,
    TemplateAnswerGenerator,
    UnavailableAnswerGenerator,
)
from app.services.query_rewriter import NoopQueryRewriter, ResponsesQueryRewriter
from app.services.rag_engine import RagEngine
from app.services.reranker import CrossEncoderReranker, KeywordReranker, NoopReranker
from app.services.retriever import HybridRetriever
from app.services.responses_client import ResponsesClient
from app.services.index_hydration import hydrate_retriever
from app.services.vectorstore import ChromaVectorStore, MemoryVectorStore, PgVectorStore
from app.services.ingestion_jobs import IngestionWorker
from app.services.provider_clients import OllamaChatClient, OpenAICompatibleChatClient


def create_embedding_provider():
    provider = settings.embedding_provider.lower()
    if provider == "mock":
        return MockEmbeddingProvider(vector_dim=settings.resolved_embedding_dimension())
    if provider in {"local", "sentence-transformers", "sentence_transformers", "huggingface"}:
        return LocalSentenceTransformerEmbeddingProvider(model_name=settings.embedding_model)
    if provider in {"openai", "openai-compatible"}:
        return OpenAICompatibleEmbeddingProvider(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url or None,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimension or None,
        )
    if provider == "ollama":
        return OllamaEmbeddingProvider(
            base_url=settings.ollama_base_url,
            model=settings.ollama_embedding_model,
            timeout_seconds=settings.answer_timeout_seconds,
        )
    raise ValueError(f"Unsupported EMBEDDING_PROVIDER: {settings.embedding_provider}")


def create_vector_store():
    store = settings.vector_store.lower()
    if store == "memory":
        return MemoryVectorStore()
    if store == "chroma":
        return ChromaVectorStore(
            persist_path=settings.chroma_path,
            collection_name=settings.chroma_collection,
            expected_dimension=settings.resolved_embedding_dimension(),
            index_version=settings.index_version,
            embedding_model=settings.embedding_model,
        )
    if store == "pgvector":
        return PgVectorStore(
            dsn=settings.pgvector_dsn,
            table_name=settings.pgvector_table,
            dimension=settings.resolved_embedding_dimension(),
        )
    raise ValueError(f"Unsupported VECTOR_STORE: {settings.vector_store}")


def create_reranker():
    reranker = settings.reranker.lower()
    if reranker in {"keyword", "local"}:
        return KeywordReranker()
    if reranker in {"cross-encoder", "cross_encoder", "bge-reranker"}:
        try:
            return CrossEncoderReranker(settings.reranker_model)
        except Exception:
            return KeywordReranker()
    if reranker in {"none", "off"}:
        return NoopReranker()
    raise ValueError(f"Unsupported RERANKER: {settings.reranker}")


def create_answer_generator():
    provider = settings.answer_provider.lower()
    if provider in {"template", "local", "none"}:
        return TemplateAnswerGenerator()
    if provider in {"responses", "openai-responses", "openai_responses"}:
        try:
            return ResponsesAnswerGenerator(
                ResponsesClient(
                    api_key=settings.answer_api_key,
                    base_url=settings.answer_base_url,
                    model=settings.answer_model,
                    timeout_seconds=settings.answer_timeout_seconds,
                )
            )
        except Exception as exc:
            if settings.provider_fallback_allowed:
                return TemplateAnswerGenerator()
            return UnavailableAnswerGenerator("openai_responses", str(exc))
    if provider in {"openai-compatible-chat", "openai_compatible_chat"}:
        try:
            return GroundedChatAnswerGenerator(
                OpenAICompatibleChatClient(
                    base_url=settings.answer_base_url,
                    model=settings.answer_model,
                    api_key=settings.answer_api_key,
                    timeout_seconds=settings.answer_timeout_seconds,
                ),
                "openai_compatible_chat",
            )
        except Exception as exc:
            if settings.provider_fallback_allowed:
                return TemplateAnswerGenerator()
            return UnavailableAnswerGenerator("openai_compatible_chat", str(exc))
    if provider == "ollama":
        return GroundedChatAnswerGenerator(
            OllamaChatClient(
                base_url=settings.ollama_base_url,
                model=settings.ollama_chat_model,
                timeout_seconds=settings.answer_timeout_seconds,
            ),
            "ollama",
        )
    raise ValueError(f"Unsupported ANSWER_PROVIDER: {settings.answer_provider}")


def create_query_rewriter():
    provider = settings.query_rewrite_provider.lower()
    if provider in {"none", "off", "noop"}:
        return NoopQueryRewriter()
    if provider in {"responses", "openai-responses"}:
        try:
            return ResponsesQueryRewriter(
                ResponsesClient(
                    api_key=settings.query_rewrite_api_key,
                    base_url=settings.query_rewrite_base_url,
                    model=settings.query_rewrite_model,
                    timeout_seconds=settings.answer_timeout_seconds,
                ),
                rewrite_count=settings.query_rewrite_count,
            )
        except Exception:
            return NoopQueryRewriter()
    raise ValueError(f"Unsupported QUERY_REWRITE_PROVIDER: {settings.query_rewrite_provider}")


processor = DocumentProcessor()
registry = DocumentRegistry(settings.document_registry_path)
retriever = HybridRetriever(
    embedding_provider=create_embedding_provider(),
    vector_store=create_vector_store(),
    reranker=create_reranker(),
    initial_retrieval_k=settings.initial_retrieval_k,
    embedding_provider_name=settings.embedding_provider.lower(),
    embedding_model=settings.embedding_model,
    vector_store_name=settings.vector_store.lower(),
    query_rewriter=create_query_rewriter(),
    mmr_lambda=settings.mmr_lambda,
    bm25_weight=settings.bm25_weight,
    vector_weight=settings.vector_weight,
)
hydrate_retriever(
    retriever,
    processor,
    registry.load_documents(),
    expected_embedding_provider=settings.embedding_provider.lower(),
    expected_embedding_model=settings.embedding_model,
    expected_embedding_dimension=settings.resolved_embedding_dimension(),
    expected_index_version=settings.index_version,
    on_mismatch=registry.save_document,
)
rag_engine = RagEngine(
    retriever,
    answer_generator=create_answer_generator(),
    no_answer_threshold=settings.no_answer_threshold,
    grounding_min_confidence=settings.grounding_min_confidence,
    citation_overlap_threshold=settings.citation_overlap_threshold,
    allow_generation_fallback=settings.provider_fallback_allowed,
)
ingestion_worker = IngestionWorker(registry, processor, retriever, settings)
