from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import deque

from app.models.domain import Document, DocumentElement, GraphEdge, GraphNode, GraphPath
from app.services.text_utils import retrieval_tokens


GRAPH_EXTRACTION_VERSION = "native-graph-v1"
ENTITY_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{1,63}")
RELATION_PATTERN = re.compile(
    r"(?P<source>[A-Za-z][A-Za-z0-9_.-]{1,63})\s+"
    r"(?P<relation>uses|supports|contains|includes|depends\s+on|requires)\s+"
    r"(?P<target>[A-Za-z][A-Za-z0-9_.-]{1,63})",
    re.IGNORECASE,
)
CHINESE_RELATION_PATTERN = re.compile(
    r"(?:^|[。；;，,\n])\s*(?P<source>[A-Za-z0-9_.-]{2,63}|[\u4e00-\u9fff]{2,24})\s*"
    r"(?P<relation>使用|支持|包含|依赖于|依赖|需要)\s*"
    r"(?P<target>[A-Za-z0-9_.-]{2,63}|[\u4e00-\u9fff]{2,24})(?=$|[。；;，,\n])"
)
RELATION_NAMES = {
    "uses": "uses",
    "supports": "supports",
    "contains": "contains_explicit",
    "includes": "contains_explicit",
    "depends on": "depends_on",
    "requires": "requires",
    "使用": "uses",
    "支持": "supports",
    "包含": "contains_explicit",
    "依赖于": "depends_on",
    "依赖": "depends_on",
    "需要": "requires",
}
MULTIHOP_MARKERS = ("关系", "关联", "如何影响", "依赖", "between", "relationship", "connected", "multi-hop")
ENTITY_STOPWORDS = {
    "the", "this", "that", "with", "from", "into", "uses", "supports", "contains", "includes",
    "depends", "requires", "and", "or", "for", "what", "how", "when", "where", "document", "page",
    "image", "table", "nearby", "context", "stage", "state",
}


class NativeGraphStore:
    """SQLite Graph-lite whose every retrievable edge points back to evidence."""

    def __init__(self, registry):
        self.registry = registry

    def build_document(self, document: Document) -> dict:
        knowledge_base_id = str(document.metadata.get("knowledge_base_id") or "default")
        nodes: dict[str, GraphNode] = {}
        edges: dict[str, GraphEdge] = {}
        mentions: list[dict] = []

        document_node = GraphNode(
            node_id=f"document:{document.document_id}",
            knowledge_base_id=knowledge_base_id,
            type="document",
            label=document.title or document.file_name,
            normalized_label=self._normalize(document.title or document.file_name),
            document_id=document.document_id,
            properties={"filename": document.file_name},
        )
        nodes[document_node.node_id] = document_node
        ordered = sorted(document.elements, key=lambda item: item.order)
        element_nodes: list[GraphNode] = []

        for element in ordered:
            label = self._element_label(element)
            element_node = GraphNode(
                node_id=f"element:{element.element_id}",
                knowledge_base_id=knowledge_base_id,
                type="element",
                label=label,
                normalized_label=self._normalize(label),
                document_id=document.document_id,
                element_id=element.element_id,
                properties={"type": element.type, "order": element.order, "page_number": element.page_number},
            )
            nodes[element_node.node_id] = element_node
            element_nodes.append(element_node)
            self._add_edge(
                edges,
                knowledge_base_id,
                document.document_id,
                document_node.node_id,
                element_node.node_id,
                "contains",
                [element.element_id],
                evidence_span=label[:500],
            )

            for entity in self._entities(element):
                entity_node = self._entity_node(knowledge_base_id, entity)
                nodes[entity_node.node_id] = entity_node
                start = element.text.lower().find(entity.lower())
                mentions.append(
                    {
                        "mention_id": str(uuid.uuid4()),
                        "knowledge_base_id": knowledge_base_id,
                        "document_id": document.document_id,
                        "element_id": element.element_id,
                        "entity_node_id": entity_node.node_id,
                        "evidence_span": entity,
                        "start_offset": max(start, 0),
                        "end_offset": max(start, 0) + len(entity),
                        "confidence": 1.0,
                        "extraction_version": GRAPH_EXTRACTION_VERSION,
                    }
                )
                self._add_edge(
                    edges,
                    knowledge_base_id,
                    document.document_id,
                    element_node.node_id,
                    entity_node.node_id,
                    "mentions",
                    [element.element_id],
                    evidence_span=entity,
                )

            for match in RELATION_PATTERN.finditer(element.text):
                source = match.group("source")
                target = match.group("target")
                relation = RELATION_NAMES[" ".join(match.group("relation").lower().split())]
                source_node = self._entity_node(knowledge_base_id, source)
                target_node = self._entity_node(knowledge_base_id, target)
                nodes[source_node.node_id] = source_node
                nodes[target_node.node_id] = target_node
                self._add_edge(
                    edges,
                    knowledge_base_id,
                    document.document_id,
                    source_node.node_id,
                    target_node.node_id,
                    relation,
                    [element.element_id],
                    evidence_span=match.group(0),
                )
            for match in CHINESE_RELATION_PATTERN.finditer(element.text):
                self._add_explicit_relation(
                    edges,
                    nodes,
                    knowledge_base_id,
                    document.document_id,
                    element.element_id,
                    match.group("source"),
                    match.group("target"),
                    RELATION_NAMES[match.group("relation")],
                    match.group(0).strip("。；;，,\n "),
                )
            if element.type == "table":
                for row in element.table:
                    if len(row) < 3:
                        continue
                    relation_key = " ".join(str(row[1]).lower().split())
                    if relation_key not in RELATION_NAMES:
                        continue
                    self._add_explicit_relation(
                        edges,
                        nodes,
                        knowledge_base_id,
                        document.document_id,
                        element.element_id,
                        str(row[0]),
                        str(row[2]),
                        RELATION_NAMES[relation_key],
                        " | ".join(str(cell) for cell in row[:3]),
                    )
            self._provider_relationships(element, knowledge_base_id, document.document_id, nodes, edges)

        for left, right in zip(element_nodes, element_nodes[1:]):
            evidence = [item for item in (left.element_id, right.element_id) if item]
            self._add_edge(
                edges,
                knowledge_base_id,
                document.document_id,
                left.node_id,
                right.node_id,
                "adjacent",
                evidence,
                evidence_span=f"order {left.properties['order']} -> {right.properties['order']}",
            )

        with self.registry.transaction() as connection:
            connection.execute("DELETE FROM graph_edges WHERE document_id = ?", (document.document_id,))
            connection.execute("DELETE FROM entity_mentions WHERE document_id = ?", (document.document_id,))
            connection.execute("DELETE FROM graph_nodes WHERE document_id = ?", (document.document_id,))
            self._delete_orphan_entities(connection)
            now = _now(connection)
            for node in nodes.values():
                connection.execute(
                    """
                    INSERT INTO graph_nodes
                      (node_id, knowledge_base_id, document_id, element_id, node_type,
                       label, normalized_label, payload, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(node_id) DO UPDATE SET
                      label = excluded.label, normalized_label = excluded.normalized_label,
                      payload = excluded.payload
                    """,
                    (
                        node.node_id,
                        node.knowledge_base_id,
                        node.document_id,
                        node.element_id,
                        node.type,
                        node.label,
                        node.normalized_label,
                        node.model_dump_json(),
                        now,
                    ),
                )
            for edge in edges.values():
                connection.execute(
                    """
                    INSERT INTO graph_edges
                      (edge_id, knowledge_base_id, document_id, source_node_id, target_node_id,
                       relation, evidence_element_ids, evidence_span, confidence,
                       extraction_version, payload, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        edge.edge_id,
                        edge.knowledge_base_id,
                        edge.document_id,
                        edge.source_node_id,
                        edge.target_node_id,
                        edge.relation,
                        json.dumps(edge.evidence_element_ids),
                        edge.evidence_span,
                        edge.confidence,
                        edge.extraction_version,
                        edge.model_dump_json(),
                        now,
                    ),
                )
            for mention in mentions:
                connection.execute(
                    """
                    INSERT INTO entity_mentions
                      (mention_id, knowledge_base_id, document_id, element_id, entity_node_id,
                       evidence_span, start_offset, end_offset, confidence,
                       extraction_version, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        mention["mention_id"], mention["knowledge_base_id"], mention["document_id"],
                        mention["element_id"], mention["entity_node_id"], mention["evidence_span"],
                        mention["start_offset"], mention["end_offset"], mention["confidence"],
                        mention["extraction_version"], now,
                    ),
                )
        return {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "mention_count": len(mentions),
            "evidence_element_count": len({item for edge in edges.values() for item in edge.evidence_element_ids}),
            "extraction_version": GRAPH_EXTRACTION_VERSION,
        }

    def search(
        self,
        query: str,
        *,
        knowledge_base_ids: list[str] | None = None,
        max_hops: int = 2,
    ) -> dict:
        nodes, edges = self._load_graph(knowledge_base_ids)
        query_lower = query.lower()
        query_tokens = set(retrieval_tokens(query))
        seeds = [
            node
            for node in nodes.values()
            if node.type == "entity"
            and (
                node.normalized_label in query_lower
                or bool(set(retrieval_tokens(node.label)) & query_tokens)
            )
        ]
        seeds = sorted(seeds, key=lambda item: (-len(item.normalized_label), item.node_id))[:12]
        navigable = [
            edge for edge in edges.values()
            if edge.relation not in {"contains", "mentions", "adjacent"} and edge.evidence_element_ids
        ]
        adjacency: dict[str, list[tuple[str, GraphEdge]]] = {}
        for edge in navigable:
            adjacency.setdefault(edge.source_node_id, []).append((edge.target_node_id, edge))
            adjacency.setdefault(edge.target_node_id, []).append((edge.source_node_id, edge))
        paths: list[GraphPath] = []
        for index, source in enumerate(seeds):
            for target in seeds[index + 1 :]:
                path = self._shortest_path(source.node_id, target.node_id, adjacency, nodes, max_hops)
                if path is not None:
                    paths.append(path)
        paths.sort(key=lambda item: (-item.score, len(item.edge_ids), item.node_ids))

        evidence: list[str] = []
        for path in paths:
            evidence.extend(path.evidence_element_ids)
        if not evidence:
            seed_ids = {seed.node_id for seed in seeds}
            for edge in navigable:
                if edge.source_node_id in seed_ids or edge.target_node_id in seed_ids:
                    evidence.extend(edge.evidence_element_ids)
        evidence = list(dict.fromkeys(evidence))
        has_multihop_intent = any(marker in query_lower for marker in MULTIHOP_MARKERS)
        eligible = bool(paths) and (len(seeds) >= 2 or has_multihop_intent)
        return {
            "seed_nodes": [self._node_payload(seed) for seed in seeds],
            "seed_count": len(seeds),
            "paths": [path.model_dump() for path in paths[:20]],
            "evidence_element_ids": evidence,
            "eligible": eligible,
            "max_hops": max(1, min(max_hops, 4)),
            "extraction_version": GRAPH_EXTRACTION_VERSION,
        }

    def snapshot(self, knowledge_base_id: str, *, limit: int = 500) -> dict:
        nodes, edges = self._load_graph([knowledge_base_id])
        node_values = list(nodes.values())[: max(1, min(limit, 2_000))]
        edge_values = list(edges.values())[: max(1, min(limit, 2_000))]
        evidence_elements = {
            element_id for edge in edge_values for element_id in edge.evidence_element_ids
        }
        return {
            "knowledge_base_id": knowledge_base_id,
            "nodes": [self._node_payload(node) for node in node_values],
            "edges": [edge.model_dump() for edge in edge_values],
            "summary": {
                "node_count": len(nodes),
                "edge_count": len(edges),
                "evidence_element_count": len(evidence_elements),
                "extraction_version": GRAPH_EXTRACTION_VERSION,
            },
        }

    def _load_graph(self, knowledge_base_ids: list[str] | None) -> tuple[dict[str, GraphNode], dict[str, GraphEdge]]:
        clauses = ""
        params: tuple = ()
        if knowledge_base_ids:
            placeholders = ",".join("?" for _ in knowledge_base_ids)
            clauses = f" WHERE knowledge_base_id IN ({placeholders})"
            params = tuple(knowledge_base_ids)
        with self.registry.transaction() as connection:
            node_rows = connection.execute(f"SELECT payload FROM graph_nodes{clauses}", params).fetchall()
            edge_rows = connection.execute(f"SELECT payload FROM graph_edges{clauses}", params).fetchall()
        nodes = {node.node_id: node for node in (GraphNode.model_validate_json(row["payload"]) for row in node_rows)}
        edges = {edge.edge_id: edge for edge in (GraphEdge.model_validate_json(row["payload"]) for row in edge_rows)}
        return nodes, edges

    def _provider_relationships(self, element, knowledge_base_id, document_id, nodes, edges) -> None:
        enrichment = element.metadata.get("enrichment")
        if not isinstance(enrichment, dict):
            return
        version = str(enrichment.get("prompt_version") or GRAPH_EXTRACTION_VERSION)
        evidence_text = "\n".join((element.text, element.caption, element.latex))
        for relation in enrichment.get("relationships", []):
            if not isinstance(relation, dict):
                continue
            span = str(relation.get("evidence_span") or "").strip()
            source = str(relation.get("source") or "").strip()
            target = str(relation.get("target") or "").strip()
            if not span or span.lower() not in evidence_text.lower() or not source or not target:
                continue
            source_node = self._entity_node(knowledge_base_id, source)
            target_node = self._entity_node(knowledge_base_id, target)
            nodes[source_node.node_id] = source_node
            nodes[target_node.node_id] = target_node
            self._add_edge(
                edges,
                knowledge_base_id,
                document_id,
                source_node.node_id,
                target_node.node_id,
                str(relation.get("relation") or "related_to")[:80],
                [element.element_id],
                evidence_span=span,
                confidence=max(0.0, min(float(relation.get("confidence") or 0), 1.0)),
                extraction_version=version,
                properties={"provider": enrichment.get("provider"), "model": enrichment.get("model")},
            )

    def _add_explicit_relation(
        self,
        edges,
        nodes,
        knowledge_base_id,
        document_id,
        element_id,
        source,
        target,
        relation,
        evidence_span,
    ) -> None:
        source = str(source).strip()
        target = str(target).strip()
        if not source or not target:
            return
        source_node = self._entity_node(knowledge_base_id, source)
        target_node = self._entity_node(knowledge_base_id, target)
        nodes[source_node.node_id] = source_node
        nodes[target_node.node_id] = target_node
        self._add_edge(
            edges,
            knowledge_base_id,
            document_id,
            source_node.node_id,
            target_node.node_id,
            relation,
            [element_id],
            evidence_span=evidence_span,
        )

    @staticmethod
    def _shortest_path(source_id, target_id, adjacency, nodes, max_hops) -> GraphPath | None:
        queue = deque([(source_id, [source_id], [])])
        visited = {source_id}
        while queue:
            current, node_path, edge_path = queue.popleft()
            if current == target_id and edge_path:
                evidence = list(dict.fromkeys(
                    element_id for edge in edge_path for element_id in edge.evidence_element_ids
                ))
                return GraphPath(
                    node_ids=node_path,
                    edge_ids=[edge.edge_id for edge in edge_path],
                    labels=[nodes[node_id].label for node_id in node_path if node_id in nodes],
                    relations=[edge.relation for edge in edge_path],
                    evidence_element_ids=evidence,
                    score=sum(edge.confidence for edge in edge_path) / len(edge_path),
                )
            if len(edge_path) >= max(1, min(max_hops, 4)):
                continue
            for neighbor, edge in adjacency.get(current, []):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                queue.append((neighbor, [*node_path, neighbor], [*edge_path, edge]))
        return None

    @staticmethod
    def _element_label(element: DocumentElement) -> str:
        return (element.caption or element.text or element.latex or f"{element.type} {element.order}")[:240]

    @staticmethod
    def _entities(element: DocumentElement) -> list[str]:
        values = []
        for match in ENTITY_PATTERN.finditer(" ".join((element.text, element.caption, element.latex))):
            candidate = match.group(0).strip(".,:;()[]{}")
            if candidate.lower() in ENTITY_STOPWORDS:
                continue
            if candidate[:1].isupper() or any(char.isdigit() for char in candidate) or any(char in "_.-" for char in candidate):
                values.append(candidate)
        enrichment = element.metadata.get("enrichment")
        if isinstance(enrichment, dict):
            evidence = " ".join((element.text, element.caption, element.latex)).lower()
            values.extend(
                str(item) for item in enrichment.get("entities", [])
                if str(item).strip() and str(item).lower() in evidence
            )
        return list(dict.fromkeys(value.strip(".,:;()[]{}") for value in values if len(value.strip(".,:;()[]{}")) >= 2))[:32]

    @classmethod
    def _entity_node(cls, knowledge_base_id: str, label: str) -> GraphNode:
        display_label = str(label).strip().strip(".,:;()[]{}")
        normalized = cls._normalize(display_label)
        digest = hashlib.sha256(f"{knowledge_base_id}:{normalized}".encode()).hexdigest()[:24]
        return GraphNode(
            node_id=f"entity:{knowledge_base_id}:{digest}",
            knowledge_base_id=knowledge_base_id,
            type="entity",
            label=display_label[:160],
            normalized_label=normalized,
        )

    @staticmethod
    def _normalize(label: str) -> str:
        return " ".join(str(label).lower().split()).strip(".,:;()[]{}")[:240]

    @staticmethod
    def _node_payload(node: GraphNode) -> dict:
        return node.model_dump()

    @staticmethod
    def _add_edge(
        edges,
        knowledge_base_id,
        document_id,
        source_node_id,
        target_node_id,
        relation,
        evidence_element_ids,
        *,
        evidence_span,
        confidence=1.0,
        extraction_version=GRAPH_EXTRACTION_VERSION,
        properties=None,
    ) -> None:
        evidence = list(dict.fromkeys(str(item) for item in evidence_element_ids if item))
        if not evidence:
            return
        digest = hashlib.sha256(
            f"{document_id}:{source_node_id}:{relation}:{target_node_id}:{'|'.join(evidence)}".encode()
        ).hexdigest()[:32]
        edge = GraphEdge(
            edge_id=f"edge:{digest}",
            knowledge_base_id=knowledge_base_id,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            relation=relation,
            document_id=document_id,
            evidence_element_ids=evidence,
            evidence_span=str(evidence_span)[:1000],
            confidence=confidence,
            extraction_version=extraction_version,
            properties=properties or {},
        )
        edges[edge.edge_id] = edge

    @staticmethod
    def _delete_orphan_entities(connection) -> None:
        connection.execute(
            """
            DELETE FROM graph_nodes
            WHERE node_type = 'entity'
              AND node_id NOT IN (SELECT entity_node_id FROM entity_mentions)
              AND node_id NOT IN (SELECT source_node_id FROM graph_edges)
              AND node_id NOT IN (SELECT target_node_id FROM graph_edges)
            """
        )


def _now(connection) -> str:
    return str(connection.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ', 'now')").fetchone()[0])
