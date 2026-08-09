from app.models.domain import Chunk
import pytest

from app.services.reranker import DeepSeekReranker, KeywordReranker


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


def test_deepseek_reranker_accepts_only_the_supplied_candidate_ids():
    class FakeClient:
        def create_json(self, prompt: str):
            assert "candidate_id" in prompt
            assert "section_path" in prompt
            return {
                "scores": [
                    {"candidate_id": "doc:0", "score": 0.2},
                    {"candidate_id": "doc:1", "score": 0.9},
                ]
            }

    candidates = [
        {
            "chunk": Chunk(
                chunk_id=f"doc:{index}",
                document_id="doc",
                chunk_index=index,
            text=f"candidate {index}",
            file_name="a.md",
            heading_path=["章节", str(index)],
            ),
            "score": 0.5,
        }
        for index in range(2)
    ]

    ranked = DeepSeekReranker(FakeClient()).rerank("question", candidates, top_k=2)

    assert [item["chunk"].chunk_id for item in ranked] == ["doc:1", "doc:0"]


def test_deepseek_reranker_rejects_new_or_missing_evidence_ids():
    class InvalidClient:
        def create_json(self, prompt: str):
            return {"scores": [{"candidate_id": "invented", "score": 1.0}]}

    candidate = {
        "chunk": Chunk(
            chunk_id="doc:0",
            document_id="doc",
            chunk_index=0,
            text="evidence",
            file_name="a.md",
        ),
        "score": 0.5,
    }

    with pytest.raises(ValueError):
        DeepSeekReranker(InvalidClient()).rerank("question", [candidate], top_k=1)


def test_deepseek_reranker_truncates_candidate_text_to_cloud_budget():
    class InspectingClient:
        def create_json(self, prompt: str):
            assert "x" * 1200 in prompt
            assert "x" * 1201 not in prompt
            return {"scores": [{"candidate_id": "doc:0", "score": 0.8}]}

    candidate = {
        "chunk": Chunk(
            chunk_id="doc:0",
            document_id="doc",
            chunk_index=0,
            text="x" * 3000,
            file_name="a.md",
            heading_path=["Cloud budget"],
        ),
        "score": 0.5,
    }

    assert DeepSeekReranker(InspectingClient()).rerank("q", [candidate], 1)
