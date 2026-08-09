from __future__ import annotations

import threading
from hashlib import sha256
from collections import Counter, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RetrievalHealthThresholds:
    """Configurable warning thresholds for retrieval-health diagnostics."""

    top_k: int = 10
    min_sparse_dense_overlap: int = 3
    min_channel_final_coverage: float = 0.1
    max_candidate_duplicate_rate: float = 0.2
    min_unique_documents: int = 2
    min_candidates_for_document_diversity: int = 3
    min_cross_query_window: int = 4
    max_mean_top_k_jaccard: float = 0.8
    universal_chunk_min_query_ratio: float = 0.8
    universal_chunk_min_query_count: int = 3

    def __post_init__(self) -> None:
        integer_fields = {
            "top_k": self.top_k,
            "min_sparse_dense_overlap": self.min_sparse_dense_overlap,
            "min_unique_documents": self.min_unique_documents,
            "min_candidates_for_document_diversity": (
                self.min_candidates_for_document_diversity
            ),
            "min_cross_query_window": self.min_cross_query_window,
            "universal_chunk_min_query_count": self.universal_chunk_min_query_count,
        }
        for name, value in integer_fields.items():
            if value < 0 or (name == "top_k" and value == 0):
                raise ValueError(f"{name} must be positive or zero where applicable")
        ratio_fields = {
            "min_channel_final_coverage": self.min_channel_final_coverage,
            "max_candidate_duplicate_rate": self.max_candidate_duplicate_rate,
            "max_mean_top_k_jaccard": self.max_mean_top_k_jaccard,
            "universal_chunk_min_query_ratio": self.universal_chunk_min_query_ratio,
        }
        for name, value in ratio_fields.items():
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")


class RetrievalHealthMonitor:
    """Keep a small in-memory window for online collapse diagnostics.

    The window stores only normalized query-token sets and leaf chunk IDs.  It
    is deliberately bounded, process-local, and reset on restart: it provides
    an early warning signal without adding a database, log file, or model.  A
    release decision must still use the locked evaluation dataset.
    """

    def __init__(
        self,
        *,
        max_history: int = 128,
        max_comparison_history: int = 24,
        unrelated_query_jaccard: float = 0.2,
    ) -> None:
        if max_history < 1 or max_comparison_history < 1:
            raise ValueError("retrieval health history limits must be positive")
        if not 0.0 <= float(unrelated_query_jaccard) <= 1.0:
            raise ValueError("unrelated_query_jaccard must be between 0 and 1")
        self.max_comparison_history = int(max_comparison_history)
        self.unrelated_query_jaccard = float(unrelated_query_jaccard)
        self._history: deque[dict[str, Any]] = deque(maxlen=int(max_history))
        self._lock = threading.Lock()

    def diagnose(
        self,
        channel_rankings: Sequence[Mapping[str, Any]],
        final_candidates: Sequence[Any],
        *,
        query_tokens: Sequence[str],
        scope_key: Any,
        eligible: bool = True,
        exclude_reason: str = "",
        thresholds: RetrievalHealthThresholds | None = None,
    ) -> dict[str, Any]:
        config = thresholds or RetrievalHealthThresholds()
        normalized_tokens = frozenset(
            str(token).strip().lower()
            for token in query_tokens[:64]
            if str(token).strip()
        )
        if not normalized_tokens:
            eligible = False
            exclude_reason = exclude_reason or "empty_query_tokens"

        current_ids = _unique(_candidate_ids(final_candidates))[: config.top_k]
        if not current_ids:
            eligible = False
            exclude_reason = exclude_reason or "no_final_candidates"
        scope_digest = _scope_digest(scope_key)

        with self._lock:
            in_scope = [
                row for row in self._history if row["scope_digest"] == scope_digest
            ]
            comparison_rows = [
                row
                for row in in_scope
                if _jaccard(set(normalized_tokens), set(row["query_tokens"]))
                <= self.unrelated_query_jaccard
            ][-self.max_comparison_history :]
            result = diagnose_retrieval_health(
                channel_rankings,
                final_candidates,
                history_window=[row["top_ids"] for row in comparison_rows]
                if eligible
                else None,
                thresholds=config,
            )
            duplicate_query = any(
                row["query_tokens"] == normalized_tokens for row in in_scope
            )
            if eligible and not duplicate_query:
                self._history.append(
                    {
                        "scope_digest": scope_digest,
                        "query_tokens": normalized_tokens,
                        "top_ids": current_ids,
                    }
                )

        result["eligible"] = bool(eligible)
        result["exclude_reason"] = "" if eligible else (exclude_reason or "ineligible")
        result["history"] = {
            "stored_queries_in_scope": len(in_scope),
            "unrelated_queries_compared": len(comparison_rows) if eligible else 0,
            "duplicate_query_not_stored": bool(eligible and duplicate_query),
            "capacity": self._history.maxlen,
        }
        if not eligible:
            result["status"] = "skipped"
        elif result["alerts"]:
            result["status"] = "warning"
        elif not result["cross_query"]["history_sufficient"]:
            result["status"] = "insufficient_history"
        else:
            result["status"] = "healthy"
        return result


def _scope_digest(value: Any) -> str:
    """Return a fixed-size grouping key without retaining caller data."""

    digest = sha256()

    def update(item: Any, depth: int = 0) -> None:
        if depth > 8:
            digest.update(b"depth-limit;")
            return
        if isinstance(item, Mapping):
            digest.update(f"map:{len(item)}[".encode())
            for key in sorted(item, key=lambda candidate: str(candidate)[:256]):
                update(key, depth + 1)
                update(item[key], depth + 1)
            digest.update(b"]")
            return
        if isinstance(item, (list, tuple, set, frozenset)):
            values = item
            if isinstance(item, (set, frozenset)):
                values = sorted(item, key=lambda candidate: str(candidate)[:256])
            digest.update(f"seq:{len(item)}[".encode())
            for child in values:
                update(child, depth + 1)
            digest.update(b"]")
            return
        text = str(item)
        # API identifiers are length-limited.  The prefix/suffix cap also keeps
        # internal misuse from turning this diagnostic into a CPU amplifier.
        bounded = text if len(text) <= 512 else f"{text[:240]}:{len(text)}:{text[-240:]}"
        digest.update(type(item).__name__.encode(errors="ignore"))
        digest.update(b":")
        digest.update(bounded.encode(errors="replace"))
        digest.update(b";")

    update(value)
    return digest.hexdigest()


def diagnose_retrieval_health(
    channel_rankings: Sequence[Mapping[str, Any]],
    final_candidates: Sequence[Any],
    *,
    history_window: Sequence[Any] | None = None,
    thresholds: RetrievalHealthThresholds | None = None,
) -> dict[str, Any]:
    """Return deterministic retrieval-health metrics without external state.

    ``channel_rankings`` accepts the retriever's current ``{name, kind, ids}``
    rows. ``final_candidates`` accepts internal ``{chunk: Chunk}`` rows,
    serialized ``{id, document_id}`` rows, Chunk-like objects, or plain IDs.
    Each history entry may be a candidate sequence or a mapping containing
    ``top_ids``, ``final_candidates``, ``results``, or ``citations``.

    Cross-query collapse alerts are meaningful only when callers provide a
    window of distinct queries; this pure function intentionally does not keep
    or infer query history itself.
    """

    config = thresholds or RetrievalHealthThresholds()
    final_rows = [_candidate_identity(item) for item in final_candidates]
    valid_final_rows = [row for row in final_rows if row[0]]
    final_ids = [row[0] for row in valid_final_rows]
    unique_final_ids = _unique(final_ids)
    final_id_set = set(unique_final_ids)

    channels = _normalise_channels(channel_rankings)
    by_channel = {
        name: _channel_final_metrics(ids, final_id_set, config.top_k)
        for name, ids in channels["by_name"].items()
    }
    by_kind = {
        kind: _channel_final_metrics(ids, final_id_set, config.top_k)
        for kind, ids in channels["by_kind"].items()
    }

    sparse_ids = channels["by_kind"].get("bm25", [])[: config.top_k]
    dense_ids = channels["by_kind"].get("dense", [])[: config.top_k]
    sparse_set = set(sparse_ids)
    dense_set = set(dense_ids)
    overlap_ids = sorted(sparse_set & dense_set)
    overlap_available = bool(sparse_ids and dense_ids)
    overlap = {
        "available": overlap_available,
        "k": config.top_k,
        "sparse_count": len(sparse_ids),
        "dense_count": len(dense_ids),
        "overlap_count": len(overlap_ids),
        "overlap_ids": overlap_ids,
        "overlap_ratio": _ratio(
            len(overlap_ids), min(len(sparse_set), len(dense_set))
        ),
        "jaccard": _jaccard(sparse_set, dense_set) if overlap_available else None,
    }

    valid_count = len(final_ids)
    unique_count = len(unique_final_ids)
    duplicate_count = max(0, valid_count - unique_count)
    document_by_chunk: dict[str, str] = {}
    for chunk_id, document_id in valid_final_rows:
        if chunk_id not in document_by_chunk or not document_by_chunk[chunk_id]:
            document_by_chunk[chunk_id] = document_id
    document_counts = Counter(
        document_id for document_id in document_by_chunk.values() if document_id
    )
    channel_occurrences = [
        candidate_id
        for row in channel_rankings
        for candidate_id in _candidate_ids(row.get("ids", []))
    ]
    candidate_diversity = {
        "candidate_count": valid_count,
        "unique_candidate_count": unique_count,
        "duplicate_count": duplicate_count,
        "duplicate_rate": _ratio(duplicate_count, valid_count),
        "unique_document_count": len(document_counts),
        "document_counts": dict(sorted(document_counts.items())),
        "missing_document_id_count": sum(
            1 for chunk_id in unique_final_ids if not document_by_chunk.get(chunk_id)
        ),
        "channel_candidate_occurrences": len(channel_occurrences),
        "unique_channel_candidates": len(set(channel_occurrences)),
        "cross_channel_duplicate_rate": _ratio(
            len(channel_occurrences) - len(set(channel_occurrences)),
            len(channel_occurrences),
        ),
    }

    current_top_ids = unique_final_ids[: config.top_k]
    historical_top_ids = [
        ids
        for entry in history_window or ()
        if (ids := _history_top_ids(entry, config.top_k))
    ]
    similarities = [
        _jaccard(set(current_top_ids), set(ids))
        for ids in historical_top_ids
        if current_top_ids
    ]
    window_sets = ([set(current_top_ids)] if current_top_ids else []) + [
        set(ids) for ids in historical_top_ids
    ]
    window_query_count = len(window_sets)
    history_sufficient = window_query_count >= config.min_cross_query_window
    frequencies = Counter(
        candidate_id for query_ids in window_sets for candidate_id in query_ids
    )
    universal_chunks = []
    if history_sufficient:
        for candidate_id, query_count in sorted(
            frequencies.items(), key=lambda row: (-row[1], row[0])
        ):
            query_ratio = _ratio(query_count, window_query_count)
            if (
                query_count >= config.universal_chunk_min_query_count
                and query_ratio >= config.universal_chunk_min_query_ratio
            ):
                universal_chunks.append(
                    {
                        "candidate_id": candidate_id,
                        "query_count": query_count,
                        "query_ratio": query_ratio,
                    }
                )
    mean_jaccard = (
        round(sum(similarities) / len(similarities), 6) if similarities else None
    )
    cross_query = {
        "k": config.top_k,
        "current_top_ids": current_top_ids,
        "history_query_count": len(historical_top_ids),
        "window_query_count": window_query_count,
        "history_sufficient": history_sufficient,
        "jaccard_by_history": similarities,
        "mean_jaccard": mean_jaccard,
        "max_jaccard": max(similarities) if similarities else None,
        "universal_chunks": universal_chunks,
    }

    alerts: list[dict[str, Any]] = []
    if overlap_available and len(overlap_ids) < config.min_sparse_dense_overlap:
        alerts.append(
            _alert(
                "low_sparse_dense_overlap",
                "channel_agreement",
                len(overlap_ids),
                config.min_sparse_dense_overlap,
            )
        )
    for kind in ("bm25", "dense"):
        metrics = by_kind.get(kind)
        if (
            metrics
            and final_id_set
            and metrics["final_evidence_coverage"]
            < config.min_channel_final_coverage
        ):
            alert = _alert(
                "low_channel_final_coverage",
                "channel_conversion",
                metrics["final_evidence_coverage"],
                config.min_channel_final_coverage,
            )
            alert["channel"] = kind
            alerts.append(alert)
    if candidate_diversity["duplicate_rate"] > config.max_candidate_duplicate_rate:
        alerts.append(
            _alert(
                "high_candidate_duplicate_rate",
                "candidate_diversity",
                candidate_diversity["duplicate_rate"],
                config.max_candidate_duplicate_rate,
            )
        )
    if (
        unique_count >= config.min_candidates_for_document_diversity
        and candidate_diversity["missing_document_id_count"] == 0
        and len(document_counts) < config.min_unique_documents
    ):
        alerts.append(
            _alert(
                "low_document_diversity",
                "candidate_diversity",
                len(document_counts),
                config.min_unique_documents,
            )
        )
    if (
        history_sufficient
        and mean_jaccard is not None
        and mean_jaccard >= config.max_mean_top_k_jaccard
    ):
        alerts.append(
            _alert(
                "high_cross_query_top_k_jaccard",
                "retrieval_collapse",
                mean_jaccard,
                config.max_mean_top_k_jaccard,
            )
        )
    if universal_chunks:
        alert = _alert(
            "universal_chunk",
            "retrieval_collapse",
            universal_chunks[0]["query_ratio"],
            config.universal_chunk_min_query_ratio,
        )
        alert["candidate_ids"] = [row["candidate_id"] for row in universal_chunks]
        alerts.append(alert)

    return {
        "version": "retrieval-health-v1",
        "healthy": not alerts,
        "sparse_dense_top10": overlap,
        "channel_final_evidence": {
            "by_channel": by_channel,
            "by_kind": by_kind,
        },
        "candidate_diversity": candidate_diversity,
        "cross_query": cross_query,
        "alerts": alerts,
    }


def _normalise_channels(
    channel_rankings: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, list[str]]]:
    by_name: dict[str, list[str]] = {}
    by_kind: dict[str, list[str]] = {}
    for index, row in enumerate(channel_rankings):
        name = str(row.get("name") or f"channel:{index}")
        kind = str(row.get("kind") or name.split(":", 1)[0]).lower()
        ids = _candidate_ids(row.get("ids", []))
        by_name[name] = _unique([*by_name.get(name, []), *ids])
        by_kind[kind] = _unique([*by_kind.get(kind, []), *ids])
    return {"by_name": by_name, "by_kind": by_kind}


def _channel_final_metrics(
    candidate_ids: Sequence[str], final_ids: set[str], top_k: int
) -> dict[str, Any]:
    top_ids = _unique(candidate_ids)[:top_k]
    selected_ids = [candidate_id for candidate_id in top_ids if candidate_id in final_ids]
    return {
        "candidate_count": len(top_ids),
        "entered_final_count": len(selected_ids),
        "entered_final_ids": selected_ids,
        "candidate_to_final_rate": _ratio(len(selected_ids), len(top_ids)),
        "final_evidence_coverage": _ratio(len(selected_ids), len(final_ids)),
    }


def _history_top_ids(entry: Any, top_k: int) -> list[str]:
    if isinstance(entry, Mapping):
        for key in (
            "top_ids",
            "final_candidate_ids",
            "candidate_ids",
            "final_candidates",
            "results",
            "citations",
        ):
            if key in entry:
                return _unique(_candidate_ids(entry.get(key)))[:top_k]
    return _unique(_candidate_ids(entry))[:top_k]


def _candidate_ids(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, (str, bytes)) or isinstance(values, Mapping):
        values = [values]
    if not isinstance(values, Sequence):
        return []
    return [
        candidate_id
        for value in values
        if (candidate_id := _candidate_identity(value)[0])
    ]


def _candidate_identity(candidate: Any) -> tuple[str, str]:
    if candidate is None:
        return "", ""
    if isinstance(candidate, bytes):
        return candidate.decode(errors="ignore").strip(), ""
    if isinstance(candidate, str):
        return candidate.strip(), ""
    if isinstance(candidate, Mapping):
        nested = candidate.get("chunk")
        nested_id, nested_document_id = (
            _candidate_identity(nested) if nested is not None else ("", "")
        )
        candidate_id = _clean_id(
            candidate.get("chunk_id") or candidate.get("id") or nested_id
        )
        document_id = _clean_id(
            candidate.get("document_id") or nested_document_id
        )
        return candidate_id, document_id
    nested = getattr(candidate, "chunk", None)
    nested_id, nested_document_id = (
        _candidate_identity(nested) if nested is not None else ("", "")
    )
    candidate_id = _clean_id(
        getattr(candidate, "chunk_id", None)
        or getattr(candidate, "id", None)
        or nested_id
    )
    document_id = _clean_id(
        getattr(candidate, "document_id", None) or nested_document_id
    )
    return candidate_id, document_id


def _clean_id(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _ratio(numerator: int | float, denominator: int | float) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(numerator) / float(denominator), 6)


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    if not union:
        return 0.0
    return _ratio(len(left & right), len(union))


def _alert(
    code: str, category: str, observed: int | float, threshold: int | float
) -> dict[str, Any]:
    return {
        "code": code,
        "category": category,
        "severity": "warning",
        "observed": observed,
        "threshold": threshold,
    }
