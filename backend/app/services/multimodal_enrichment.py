from __future__ import annotations

import base64
import hashlib
import json
import re
from typing import Callable

from app.models.domain import Document, DocumentElement
from app.services.context_window import ContextWindowBuilder
from app.services.responses_client import ResponsesClient
from app.services.resilience import ResilientExecutor
from app.services.safe_logging import public_error_message, redact_sensitive_text
from app.services.text_utils import tokenize


ENRICHMENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "description": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "entities": {"type": "array", "items": {"type": "string"}},
        "relationships": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "source": {"type": "string"},
                    "relation": {"type": "string"},
                    "target": {"type": "string"},
                    "evidence_span": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["source", "relation", "target", "evidence_span", "confidence"],
            },
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["description", "keywords", "entities", "relationships", "confidence", "warnings"],
}


class ProviderUnavailableError(RuntimeError):
    pass


class UnavailableMultimodalEnricher:
    def __init__(self, provider: str, reason: str):
        self.provider = provider
        self.model = "unavailable"
        self.reason = redact_sensitive_text(reason)

    def enrich(self, element: DocumentElement, context: dict, *, image_data_url: str = "") -> dict:
        raise ProviderUnavailableError(f"{self.provider} is not configured")


class FallbackMultimodalEnricher:
    def __init__(self, primary, fallback=None):
        self.primary = primary
        self.fallback = fallback or TemplateMultimodalEnricher()
        self.provider = primary.provider
        self.model = primary.model

    def enrich(self, element: DocumentElement, context: dict, *, image_data_url: str = "") -> dict:
        try:
            return self.primary.enrich(element, context, image_data_url=image_data_url)
        except Exception as exc:
            result = self.fallback.enrich(element, context, image_data_url="")
            result["warnings"] = [
                *result.get("warnings", []),
                f"{self.provider} 暂时不可用，已使用确定性离线 fallback。",
            ]
            result["fallback"] = {
                "from": self.provider,
                "to": self.fallback.provider,
                "reason": public_error_message(
                    exc,
                    "Provider 暂时不可用，已使用离线 enrichment。",
                ),
            }
            return result


class TemplateMultimodalEnricher:
    provider = "template"
    model = "deterministic-v1"

    def enrich(self, element: DocumentElement, context: dict, *, image_data_url: str = "") -> dict:
        if element.type == "table":
            rows = len(element.table)
            columns = max((len(row) for row in element.table), default=0)
            headers = element.table[0] if element.table else []
            description = f"包含 {rows} 行、{columns} 列的表格"
            if headers:
                description += "；表头：" + "、".join(headers)
            keywords = self._dedupe([*headers, *tokenize(element.text)])[:16]
        elif element.type == "equation":
            description = f"从文档中提取的公式：{element.latex or element.text}".strip()
            keywords = self._dedupe(tokenize(f"{element.latex} {context.get('text', '')}"))[:16]
        else:
            description = element.caption or element.text or "未提取到文字的图片"
            if context.get("text") and context["text"] not in description:
                description = f"{description}。相邻上下文：{context['text'][:500]}"
            keywords = self._dedupe(tokenize(f"{element.caption} {element.text} {context.get('text', '')}"))[:16]
        entities = [item for item in keywords if self._looks_like_entity(item)][:8]
        return {
            "description": description[:2_000],
            "keywords": keywords,
            "entities": entities,
            "relationships": [],
            "confidence": 1.0 if element.text or element.table or element.latex else 0.4,
            "warnings": [] if element.text or element.table or element.latex else ["未提取到元素文本。"],
        }

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            cleaned = str(value).strip()
            key = cleaned.lower()
            if cleaned and key not in seen:
                seen.add(key)
                result.append(cleaned)
        return result

    @staticmethod
    def _looks_like_entity(value: str) -> bool:
        return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{1,40}", value))


class ResponsesVisionEnricher:
    provider = "openai_responses"

    def __init__(self, client: ResponsesClient, *, image_detail: str = "auto", executor: ResilientExecutor | None = None):
        self.client = client
        self.model = client.model
        self.image_detail = image_detail if image_detail in {"low", "high", "original", "auto"} else "auto"
        self.executor = executor or ResilientExecutor("openai_responses_enrichment")

    def enrich(self, element: DocumentElement, context: dict, *, image_data_url: str = "") -> dict:
        prompt = (
            "Analyze this document element using only the supplied element and nearby context. "
            "Return evidence-focused structured metadata; do not infer unsupported relationships.\n\n"
            f"Element type: {element.type}\nElement text: {element.text[:6000]}\n"
            f"Caption: {element.caption[:1000]}\nLaTeX: {element.latex[:2000]}\n"
            f"Nearby context: {str(context.get('text') or '')[:8000]}"
        )
        requested_detail = str(context.get("image_detail") or self.image_detail)
        payload = self.executor.run(
            lambda: self.client.create_structured(
                prompt,
                schema=ENRICHMENT_SCHEMA,
                schema_name="multimodal_enrichment",
                image_data_url=image_data_url,
                image_detail=requested_detail,
            )
        )
        if not isinstance(payload, dict):
            raise ValueError("Structured enrichment returned a non-object")
        return _validate_enrichment(payload)


class StructuredVisionEnricher:
    def __init__(
        self,
        client,
        *,
        provider: str,
        image_detail: str = "auto",
        executor: ResilientExecutor | None = None,
    ):
        self.client = client
        self.provider = provider
        self.model = client.model
        self.image_detail = image_detail
        self.executor = executor or ResilientExecutor(f"{provider}_enrichment")

    def enrich(self, element: DocumentElement, context: dict, *, image_data_url: str = "") -> dict:
        prompt = (
            "Analyze this document element using only the supplied element and nearby context. "
            "Return JSON matching the supplied schema; omit unsupported relationships.\n\n"
            f"Element type: {element.type}\nElement text: {element.text[:6000]}\n"
            f"Caption: {element.caption[:1000]}\nLaTeX: {element.latex[:2000]}\n"
            f"Nearby context: {str(context.get('text') or '')[:8000]}"
        )
        requested_detail = str(context.get("image_detail") or self.image_detail)
        payload = self.executor.run(
            lambda: self.client.create_structured(
                prompt,
                schema=ENRICHMENT_SCHEMA,
                image_data_url=image_data_url,
                image_detail=requested_detail,
            )
        )
        return _validate_enrichment(payload)


class MultimodalEnrichmentService:
    def __init__(
        self,
        registry,
        enricher,
        context_builder: ContextWindowBuilder,
        *,
        prompt_version: str = "multimodal-v1",
        asset_loader: Callable[[str], tuple[bytes, str] | None] | None = None,
    ):
        self.registry = registry
        self.enricher = enricher
        self.context_builder = context_builder
        self.prompt_version = prompt_version
        self.asset_loader = asset_loader

    def enrich_document(self, document: Document) -> dict:
        enriched = 0
        cache_hits = 0
        warnings: list[str] = []
        for element in document.elements:
            if element.type not in {"image", "table", "equation"}:
                continue
            context = self.context_builder.build(document, element)
            cache_key = self._cache_key(element, context)
            result = self.registry.get_enrichment_cache(cache_key)
            if result is not None:
                cache_hits += 1
            else:
                image_data_url = self._image_data_url(element)
                result = _validate_enrichment(
                    self.enricher.enrich(element, context, image_data_url=image_data_url)
                )
                result.update(
                    {
                        "provider": self.enricher.provider,
                        "model": self.enricher.model,
                        "prompt_version": self.prompt_version,
                        "context_element_ids": context["element_ids"],
                    }
                )
                self.registry.set_enrichment_cache(
                    cache_key,
                    provider=self.enricher.provider,
                    model=self.enricher.model,
                    prompt_version=self.prompt_version,
                    payload=result,
                )
                enriched += 1
            element.metadata["enrichment"] = result
            warnings.extend(str(item) for item in result.get("warnings", []))
        document.metadata["enrichment"] = {
            "provider": self.enricher.provider,
            "model": self.enricher.model,
            "prompt_version": self.prompt_version,
            "enriched": enriched,
            "cache_hits": cache_hits,
            "warnings": warnings[:20],
        }
        if self.registry.get_document(document.document_id):
            self.registry.save_document(document)
        return document.metadata["enrichment"]

    def _cache_key(self, element: DocumentElement, context: dict) -> str:
        payload = {
            "type": element.type,
            "text": element.text,
            "caption": element.caption,
            "table": element.table,
            "latex": element.latex,
            "context": context.get("text", ""),
            "provider": self.enricher.provider,
            "model": self.enricher.model,
            "prompt_version": self.prompt_version,
        }
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    def _image_data_url(self, element: DocumentElement) -> str:
        if element.type != "image" or not element.asset_id or self.asset_loader is None:
            return ""
        loaded = self.asset_loader(element.asset_id)
        if loaded is None:
            return ""
        payload, media_type = loaded
        encoded = base64.b64encode(payload).decode("ascii")
        return f"data:{media_type};base64,{encoded}"


def _validate_enrichment(payload: dict) -> dict:
    description = str(payload.get("description") or "").strip()
    keywords = [str(item).strip() for item in payload.get("keywords", []) if str(item).strip()][:32]
    entities = [str(item).strip() for item in payload.get("entities", []) if str(item).strip()][:32]
    relationships = []
    for item in payload.get("relationships", []) if isinstance(payload.get("relationships"), list) else []:
        if not isinstance(item, dict) or not str(item.get("evidence_span") or "").strip():
            continue
        relationships.append(
            {
                "source": str(item.get("source") or "")[:160],
                "relation": str(item.get("relation") or "related_to")[:80],
                "target": str(item.get("target") or "")[:160],
                "evidence_span": str(item.get("evidence_span") or "")[:1000],
                "confidence": max(0.0, min(float(item.get("confidence") or 0), 1.0)),
            }
        )
    result = {
        "description": description[:4_000],
        "keywords": keywords,
        "entities": entities,
        "relationships": relationships[:32],
        "confidence": max(0.0, min(float(payload.get("confidence") or 0), 1.0)),
        "warnings": [str(item)[:300] for item in payload.get("warnings", []) if str(item).strip()][:20],
    }
    fallback = payload.get("fallback")
    if isinstance(fallback, dict):
        result["fallback"] = {
            "from": str(fallback.get("from") or "unknown")[:80],
            "to": str(fallback.get("to") or "template")[:80],
            "reason": public_error_message(
                fallback.get("reason") or "provider unavailable",
                "Provider 暂时不可用，已使用离线 enrichment。",
            )[:300],
        }
    return result
