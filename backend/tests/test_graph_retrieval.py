from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import httpx
import pytest

from app.models.domain import DocumentElement
from app.services.context_window import ContextWindowBuilder
from app.services.document_processor import DocumentProcessor
from app.services.document_registry import DocumentRegistry
from app.services.graph_store import NativeGraphStore
from app.services.graph_adapters import LightRAGNavigationAdapter
from app.services.multimodal_enrichment import (
    FallbackMultimodalEnricher,
    MultimodalEnrichmentService,
    ResponsesVisionEnricher,
    TemplateMultimodalEnricher,
)
from app.services.responses_client import ResponsesClient
from app.services.provider_clients import OpenAICompatibleVisionClient, OllamaVisionClient
from app.services.resilience import CircuitBreaker, CircuitOpenError, ResilientExecutor
from app.services.retriever import HybridRetriever


def _relationship_document(text: str = "Alpha uses Beta. Beta supports Gamma."):
    document = DocumentProcessor().parse_text_source(text, "relations.md")
    document.metadata["knowledge_base_id"] = "default"
    return document


def test_schema_v5_graph_edges_always_retain_evidence_provenance(tmp_path: Path):
    registry = DocumentRegistry(str(tmp_path / "registry.sqlite3"))
    document = _relationship_document()
    registry.save_document(document)
    graph = NativeGraphStore(registry)

    result = graph.build_document(document)
    snapshot = graph.snapshot("default")

    assert registry.schema_version == DocumentRegistry.CURRENT_SCHEMA_VERSION
    assert result["node_count"] >= 4
    assert result["edge_count"] >= 3
    assert any(edge["relation"] == "uses" for edge in snapshot["edges"])
    assert any(edge["relation"] == "supports" for edge in snapshot["edges"])
    assert all(edge["evidence_element_ids"] for edge in snapshot["edges"])
    assert all(edge["extraction_version"] for edge in snapshot["edges"])
    assert all(edge["confidence"] > 0 for edge in snapshot["edges"])


def test_context_window_collects_neighbor_elements_and_respects_bound(tmp_path: Path):
    document = DocumentProcessor().parse_text_source(
        "# Architecture\n\nBefore context.\n\nTarget table.\n\nAfter context.",
        "context.md",
    )
    target = document.elements[2]
    window = ContextWindowBuilder(max_context_chars=70).build(document, target, element_window=2)

    assert target.element_id in window["element_ids"]
    assert "Target table" in window["text"]
    assert window["character_count"] <= 70
    assert window["token_estimate"] <= 20


def test_template_enrichment_is_deterministic_and_uses_registry_cache(tmp_path: Path):
    registry = DocumentRegistry(str(tmp_path / "registry.sqlite3"))
    document = _relationship_document("# Metrics\n\nStage | State\nqueued | waiting")
    document.elements[1].type = "table"
    document.elements[1].table = [["Stage", "State"], ["queued", "waiting"]]
    registry.save_document(document)
    service = MultimodalEnrichmentService(
        registry,
        TemplateMultimodalEnricher(),
        ContextWindowBuilder(),
        prompt_version="multimodal-v1",
    )

    first = service.enrich_document(document)
    second = service.enrich_document(document)

    enrichment = document.elements[1].metadata["enrichment"]
    assert first["enriched"] == 1
    assert second["cache_hits"] == 1
    assert enrichment["description"].startswith("包含 2 行、2 列的表格")
    assert "Stage" in enrichment["keywords"]
    assert enrichment["provider"] == "template"


def test_enrichment_fallback_is_preserved_and_sanitized(tmp_path: Path):
    class FailingEnricher:
        provider = "mock_vision"
        model = "mock-v1"

        def enrich(self, element, context, *, image_data_url=""):
            raise RuntimeError("provider failed with token sk-secret-value")

    registry = DocumentRegistry(str(tmp_path / "registry.sqlite3"))
    document = _relationship_document("Stage | State\nqueued | waiting")
    document.elements[0].type = "table"
    document.elements[0].table = [["Stage", "State"], ["queued", "waiting"]]
    registry.save_document(document)
    service = MultimodalEnrichmentService(
        registry,
        FallbackMultimodalEnricher(FailingEnricher()),
        ContextWindowBuilder(),
    )

    service.enrich_document(document)

    fallback = document.elements[0].metadata["enrichment"]["fallback"]
    assert fallback["from"] == "mock_vision"
    assert fallback["to"] == "template"
    assert "secret-value" not in fallback["reason"]


def test_hybrid_graph_uses_paths_but_plain_hybrid_stays_compatible(tmp_path: Path):
    registry = DocumentRegistry(str(tmp_path / "registry.sqlite3"))
    document = _relationship_document()
    registry.save_document(document)
    graph = NativeGraphStore(registry)
    graph.build_document(document)
    processor = DocumentProcessor()
    chunks = processor.split(document)
    retriever = HybridRetriever(graph_store=graph)
    retriever.add_document(document, chunks)

    plain, plain_trace = retriever.search("Alpha 与 Gamma 有什么关系？", query_rewrite=False)
    ranked, trace = retriever.search(
        "Alpha 与 Gamma 有什么关系？",
        strategy="hybrid_graph",
        graph_weight=0.25,
        graph_max_hops=2,
        query_rewrite=False,
    )

    assert plain_trace["strategy"] == "hybrid"
    assert "graph" not in plain_trace["pipeline"]
    assert ranked
    assert trace["strategy"] == "hybrid_graph"
    assert trace["pipeline"]["graph"]["status"] == "success"
    assert trace["pipeline"]["graph"]["seed_count"] >= 2
    assert trace["pipeline"]["graph"]["paths"]
    assert trace["pipeline"]["graph"]["evidence_element_ids"]
    assert plain[0]["chunk"].document_id == ranked[0]["chunk"].document_id


def test_auto_graph_requires_provenance_backed_multi_entity_path(tmp_path: Path):
    registry = DocumentRegistry(str(tmp_path / "registry.sqlite3"))
    document = _relationship_document()
    registry.save_document(document)
    graph = NativeGraphStore(registry)
    graph.build_document(document)
    processor = DocumentProcessor()
    retriever = HybridRetriever(graph_store=graph)
    retriever.add_document(document, processor.split(document))

    _, single_trace = retriever.search("Alpha", strategy="auto", query_rewrite=False)
    _, path_trace = retriever.search("Alpha 与 Gamma 的关系", strategy="auto", query_rewrite=False)

    assert single_trace["strategy"] == "hybrid"
    assert single_trace["graph_requested_strategy"] == "auto"
    assert path_trace["strategy"] == "hybrid_graph"
    assert path_trace["pipeline"]["graph"]["status"] == "success"


def test_responses_vision_enrichment_uses_current_structured_contract():
    captured = {}

    def handler(request: httpx.Request):
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "description": "Architecture diagram",
                                        "keywords": ["retrieval"],
                                        "entities": ["BM25"],
                                        "relationships": [],
                                        "confidence": 0.93,
                                        "warnings": [],
                                    }
                                ),
                            }
                        ]
                    }
                ]
            },
        )

    client = ResponsesClient(
        api_key="test-key",
        model="gpt-5.6",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    enricher = ResponsesVisionEnricher(client, image_detail="high")
    element = DocumentElement(
        element_id="doc:element:0",
        document_id="doc",
        type="image",
        order=0,
        text="OCR: retrieval stages",
    )

    result = enricher.enrich(
        element,
        {"text": "Nearby architecture section", "element_ids": [element.element_id]},
        image_data_url="data:image/png;base64,aW1hZ2U=",
    )

    assert result["description"] == "Architecture diagram"
    assert captured["model"] == "gpt-5.6"
    assert captured["store"] is False
    assert captured["input"][0]["content"][1] == {
        "type": "input_image",
        "image_url": "data:image/png;base64,aW1hZ2U=",
        "detail": "high",
    }
    assert captured["text"]["format"]["type"] == "json_schema"
    assert captured["text"]["format"]["strict"] is True


def test_v4_registry_is_backed_up_and_migrated_to_v5(tmp_path: Path):
    path = tmp_path / "v4.sqlite3"
    registry = DocumentRegistry(str(path))
    document = _relationship_document()
    registry.save_document(document)
    registry.close()
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE entity_mentions")
        connection.execute("DROP TABLE graph_edges")
        connection.execute("DROP TABLE graph_nodes")
        connection.execute("DELETE FROM schema_migrations")
        connection.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (4, 'v4')")

    migrated = DocumentRegistry(str(path))

    assert migrated.schema_version == DocumentRegistry.CURRENT_SCHEMA_VERSION
    assert migrated.get_document(document.document_id) is not None
    assert list(tmp_path.glob("v4.sqlite3.bak-*"))
    assert NativeGraphStore(migrated).snapshot("default")["summary"]["node_count"] == 0


def test_graph_search_is_isolated_by_knowledge_base_and_rejects_hallucinated_edges(tmp_path: Path):
    registry = DocumentRegistry(str(tmp_path / "registry.sqlite3"))
    private_kb = registry.create_knowledge_base("Private")
    default_doc = _relationship_document("Alpha uses Beta.")
    private_doc = _relationship_document("Alpha supports SecretSystem.")
    private_doc.metadata["knowledge_base_id"] = private_kb["id"]
    private_doc.elements[0].metadata["enrichment"] = {
        "provider": "mock_vlm",
        "prompt_version": "test-v1",
        "relationships": [
            {
                "source": "Alpha",
                "relation": "owns",
                "target": "PayrollKey",
                "evidence_span": "Alpha owns PayrollKey",
                "confidence": 0.99,
            }
        ],
    }
    registry.save_document(default_doc)
    registry.save_document(private_doc)
    graph = NativeGraphStore(registry)
    graph.build_document(default_doc)
    graph.build_document(private_doc)

    default_result = graph.search("Alpha 与 SecretSystem 的关系", knowledge_base_ids=["default"])
    private_result = graph.search("Alpha 与 SecretSystem 的关系", knowledge_base_ids=[private_kb["id"]])
    private_snapshot = graph.snapshot(private_kb["id"])

    assert default_result["seed_count"] == 1
    assert private_result["seed_count"] >= 2
    assert private_result["paths"]
    assert not any(edge["relation"] == "owns" for edge in private_snapshot["edges"])


def test_parent_window_controls_returned_parent_child_context(tmp_path: Path):
    document = DocumentProcessor(chunk_size=18, overlap=0).parse_text_source(
        "Alpha first paragraph.\n\nBeta second paragraph.\n\nGamma third paragraph.",
        "window.md",
    )
    processor = DocumentProcessor(chunk_size=18, overlap=0)
    retriever = HybridRetriever()
    retriever.add_document(document, processor.split(document))

    ranked, trace = retriever.search("Beta", parent_window=0, query_rewrite=False)

    assert trace["parent_window"] == 0
    assert ranked[0]["parent_window"] == 0


def test_compatible_and_ollama_vision_contracts_use_images_without_leaking_data_url_shape():
    compatible_body = {}
    ollama_body = {}
    result = {
        "description": "diagram",
        "keywords": [],
        "entities": [],
        "relationships": [],
        "confidence": 1,
        "warnings": [],
    }

    def compatible_handler(request: httpx.Request):
        compatible_body.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(result)}}]})

    def ollama_handler(request: httpx.Request):
        ollama_body.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": json.dumps(result)}})

    data_url = "data:image/png;base64,aW1hZ2U="
    compatible = OpenAICompatibleVisionClient(
        "http://vision.local/v1",
        "vision-model",
        http_client=httpx.Client(transport=httpx.MockTransport(compatible_handler)),
    )
    ollama = OllamaVisionClient(
        "http://ollama.local",
        "vision-model",
        http_client=httpx.Client(transport=httpx.MockTransport(ollama_handler)),
    )

    assert compatible.create_structured("analyze", schema={"type": "object"}, image_data_url=data_url) == result
    assert ollama.create_structured("analyze", schema={"type": "object"}, image_data_url=data_url) == result
    assert compatible_body["messages"][0]["content"][1]["image_url"]["url"] == data_url
    assert compatible_body["response_format"]["type"] == "json_schema"
    assert ollama_body["messages"][0]["images"] == ["aW1hZ2U="]
    assert ollama_body["format"] == {"type": "object"}


def test_resilience_retries_transient_errors_and_opens_circuit_without_real_sleep():
    attempts = 0
    delays = []
    breaker = CircuitBreaker("test", failure_threshold=1, reset_timeout_seconds=60)
    executor = ResilientExecutor(
        "test",
        attempts=3,
        base_delay_seconds=0.1,
        jitter_ratio=0,
        breaker=breaker,
        sleeper=delays.append,
    )

    def flaky():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.ConnectError("temporary")
        return "ok"

    assert executor.run(flaky) == "ok"
    assert delays == [0.1, 0.2]
    with pytest.raises(ValueError):
        executor.run(lambda: (_ for _ in ()).throw(ValueError("permanent")))
    with pytest.raises(CircuitOpenError):
        executor.run(lambda: "not called")


def test_native_graph_extracts_chinese_and_table_relationships(tmp_path: Path):
    registry = DocumentRegistry(str(tmp_path / "registry.sqlite3"))
    document = _relationship_document("检索器使用BM25。\n\nEntity | Relation | Target")
    table = document.elements[-1]
    table.type = "table"
    table.table = [["Atlas", "supports", "Vega"]]
    registry.save_document(document)

    snapshot = NativeGraphStore(registry)
    snapshot.build_document(document)
    edges = snapshot.snapshot("default")["edges"]

    assert any(edge["relation"] == "uses" and "检索器使用BM25" in edge["evidence_span"] for edge in edges)
    assert any(edge["relation"] == "supports" and "Atlas | supports | Vega" in edge["evidence_span"] for edge in edges)


def test_lightrag_bridge_only_returns_locally_owned_provenance(tmp_path: Path):
    registry = DocumentRegistry(str(tmp_path / "registry.sqlite3"))
    private_kb = registry.create_knowledge_base("Private")
    default_doc = _relationship_document("Alpha uses Beta.")
    private_doc = _relationship_document("Secret supports Vault.")
    private_doc.metadata["knowledge_base_id"] = private_kb["id"]
    registry.save_document(default_doc)
    registry.save_document(private_doc)

    adapter = LightRAGNavigationAdapter(
        registry,
        lambda **_: {
            "paths": [
                {
                    "labels": ["Alpha", "Beta"],
                    "relations": ["uses"],
                    "evidence_element_ids": [
                        default_doc.elements[0].element_id,
                        private_doc.elements[0].element_id,
                        "invented:element",
                    ],
                    "score": 2,
                },
                {"labels": ["Ghost"], "evidence_element_ids": ["invented:element"]},
            ]
        },
    )

    result = adapter.search("Alpha", knowledge_base_ids=["default"], max_hops=9)

    assert result["eligible"] is True
    assert result["evidence_element_ids"] == [default_doc.elements[0].element_id]
    assert len(result["paths"]) == 1
    assert result["paths"][0]["score"] == 1.0
