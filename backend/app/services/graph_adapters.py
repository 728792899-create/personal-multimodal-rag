from __future__ import annotations

from collections.abc import Callable

from app.services.resilience import ResilientExecutor


class LightRAGNavigationAdapter:
    """Optional navigation-only bridge.

    LightRAG may suggest paths, but evidence must resolve to elements already
    owned by the selected local knowledge bases. The adapter never writes the
    local graph and never returns evidence-free paths.
    """

    name = "lightrag"

    def __init__(self, registry, query_callable: Callable[..., dict], *, executor: ResilientExecutor | None = None):
        self.registry = registry
        self.query_callable = query_callable
        self.executor = executor or ResilientExecutor("lightrag_navigation")

    def search(self, query: str, *, knowledge_base_ids: list[str] | None, max_hops: int) -> dict:
        raw = self.executor.run(
            lambda: self.query_callable(
                query=query,
                knowledge_base_ids=knowledge_base_ids or ["default"],
                max_hops=max(1, min(int(max_hops), 4)),
            )
        )
        if not isinstance(raw, dict):
            raise ValueError("LightRAG adapter returned an invalid response")
        allowed = self._allowed_element_ids(knowledge_base_ids or ["default"])
        paths: list[dict] = []
        evidence: list[str] = []
        for path in raw.get("paths", []) if isinstance(raw.get("paths"), list) else []:
            if not isinstance(path, dict):
                continue
            verified = [str(item) for item in path.get("evidence_element_ids", []) if str(item) in allowed]
            if not verified:
                continue
            paths.append(
                {
                    "labels": [str(item)[:160] for item in path.get("labels", [])][:12],
                    "relations": [str(item)[:80] for item in path.get("relations", [])][:11],
                    "evidence_element_ids": list(dict.fromkeys(verified)),
                    "score": max(0.0, min(float(path.get("score") or 0), 1.0)),
                    "backend": self.name,
                }
            )
            evidence.extend(verified)
        return {
            "backend": self.name,
            "paths": paths,
            "evidence_element_ids": list(dict.fromkeys(evidence)),
            "eligible": bool(paths),
        }

    def _allowed_element_ids(self, knowledge_base_ids: list[str]) -> set[str]:
        placeholders = ",".join("?" for _ in knowledge_base_ids)
        with self.registry.transaction() as connection:
            rows = connection.execute(
                f"SELECT element_id FROM document_elements WHERE knowledge_base_id IN ({placeholders})",
                tuple(knowledge_base_ids),
            ).fetchall()
        return {str(row["element_id"]) for row in rows}
