import os


os.environ.setdefault("EMBEDDING_PROVIDER", "mock")
os.environ.setdefault("EMBEDDING_DIMENSION", "256")
os.environ.setdefault("VECTOR_STORE", "memory")
os.environ.setdefault("RERANKER", "keyword")
os.environ.setdefault("ANSWER_PROVIDER", "template")
os.environ.setdefault("QUERY_REWRITE_PROVIDER", "none")
os.environ.setdefault("DOCUMENT_REGISTRY_PATH", ":memory:")
