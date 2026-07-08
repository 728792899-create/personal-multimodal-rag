from app.models.domain import Chunk
from app.services.reranker import KeywordReranker


def test_keyword_reranker_promotes_token_overlap():
    reranker = KeywordReranker()
    candidates = [
        {
            "chunk": Chunk(
                chunk_id="doc:0",
                document_id="doc",
                chunk_index=0,
                text="无关内容",
                file_name="a.md",
            ),
            "score": 0.4,
        },
        {
            "chunk": Chunk(
                chunk_id="doc:1",
                document_id="doc",
                chunk_index=1,
                text="RAG 召回质量 可以通过 BM25 向量检索 和 Rerank 优化",
                file_name="a.md",
            ),
            "score": 0.4,
        },
    ]

    result = reranker.rerank("RAG 召回质量 如何优化", candidates, top_k=1)

    assert result[0]["chunk"].chunk_id == "doc:1"
    assert result[0]["rerank_score"] > result[0]["score"]
