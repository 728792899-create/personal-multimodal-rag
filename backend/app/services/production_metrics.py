from __future__ import annotations

import math
import re
import threading
from collections import defaultdict
from dataclasses import dataclass, field


_UUID_SEGMENT = re.compile(
    r"^(?:[0-9a-f]{8}-[0-9a-f-]{27,}|[0-9a-f]{24,}|[A-Za-z0-9_-]{36,})$",
    re.IGNORECASE,
)
_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, math.inf)


def safe_path_class(path: str) -> str:
    """Return a low-cardinality path label without query strings or resource IDs."""
    segments = []
    for segment in path.split("?", 1)[0].split("/"):
        if not segment:
            continue
        if _UUID_SEGMENT.fullmatch(segment) or segment.isdigit():
            segments.append(":id")
        elif len(segment) > 80:
            segments.append(":value")
        else:
            segments.append(segment[:80])
    return "/" + "/".join(segments)


def _labels(**labels: str) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((name, str(value)[:80]) for name, value in labels.items()))


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _label_text(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    return "{" + ",".join(f'{name}="{_escape(value)}"' for name, value in labels) + "}"


@dataclass
class Histogram:
    count: int = 0
    total: float = 0.0
    buckets: dict[float, int] = field(default_factory=lambda: {bucket: 0 for bucket in _BUCKETS})


class ProductionMetrics:
    """Small dependency-free Prometheus registry with deliberately bounded labels."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._histograms: dict[tuple[str, tuple[tuple[str, str], ...]], Histogram] = {}

    def increment(self, name: str, value: float = 1.0, **labels: str) -> None:
        with self._lock:
            self._counters[(name, _labels(**labels))] += float(value)

    def observe(self, name: str, value: float, **labels: str) -> None:
        sample = max(0.0, float(value))
        key = (name, _labels(**labels))
        with self._lock:
            histogram = self._histograms.setdefault(key, Histogram())
            histogram.count += 1
            histogram.total += sample
            for bucket in _BUCKETS:
                if sample <= bucket:
                    histogram.buckets[bucket] += 1

    def observe_http(self, *, method: str, path: str, status: int, seconds: float) -> None:
        labels = {
            "method": method.upper()[:12],
            "path": safe_path_class(path),
            "status": str(int(status)),
        }
        self.increment("rag_http_requests_total", **labels)
        self.observe("rag_http_request_duration_seconds", seconds, **labels)

    def record_answer(self, response: dict, *, provider: str) -> None:
        trace = response.get("retrieval_trace") or {}
        decision = (trace.get("pipeline") or {}).get("decision") or {}
        refused = decision.get("status") == "refused" or not response.get("citations")
        self.increment(
            "rag_answers_total",
            provider=(provider or "unknown"),
            outcome="refused" if refused else "answered",
        )
        audit = response.get("citation_audit") or {}
        self.observe(
            "rag_citation_coverage_ratio",
            float(audit.get("coverage") or 0.0),
            outcome="refused" if refused else "answered",
        )
        performance = trace.get("performance") or {}
        for key, metric in (
            ("retrieval_ms", "rag_retrieval_duration_seconds"),
            ("first_token_ms", "rag_first_token_duration_seconds"),
        ):
            if isinstance(performance.get(key), (int, float)):
                self.observe(metric, float(performance[key]) / 1000.0, provider=(provider or "unknown"))

    def record_provider_error(self, *, provider: str, operation: str) -> None:
        self.increment(
            "rag_provider_errors_total",
            provider=(provider or "unknown"),
            operation=(operation or "unknown"),
        )

    def record_source_sync(self, run: dict, *, source_type: str) -> None:
        status = str(run.get("status") or "unknown")
        self.increment("rag_source_sync_runs_total", source_type=source_type, status=status)
        for field in ("discovered", "unchanged", "updated", "failed", "deletion_candidates"):
            self.increment(
                "rag_source_sync_items_total",
                float(run.get(field) or 0),
                source_type=source_type,
                outcome=field,
            )

    def record_job(self, *, status: str, seconds: float, attempts: int = 1) -> None:
        self.increment("rag_index_jobs_total", status=status)
        self.observe("rag_index_job_duration_seconds", seconds, status=status)
        if attempts > 1:
            self.increment("rag_index_job_retries_total", attempts=str(min(int(attempts), 10)))

    def render(self, *, registry=None) -> str:
        lines = [
            "# HELP rag_build_info Static release identity.",
            "# TYPE rag_build_info gauge",
            'rag_build_info{version="0.4.0-rc.1"} 1',
            "# HELP rag_provider_cost_usd_total Provider-reported cost; zero when the provider does not return cost metadata.",
            "# TYPE rag_provider_cost_usd_total counter",
            "rag_provider_cost_usd_total 0",
        ]
        if registry is not None:
            jobs = registry.list_index_jobs(500)
            counts: dict[str, int] = defaultdict(int)
            for job in jobs:
                counts[str(job.get("status") or "unknown")] += 1
            lines.extend(
                [
                    "# HELP rag_index_queue_jobs Current durable index jobs by state.",
                    "# TYPE rag_index_queue_jobs gauge",
                    *[
                        f'rag_index_queue_jobs{{status="{_escape(status)}"}} {count}'
                        for status, count in sorted(counts.items())
                    ],
                    "# HELP rag_dead_letter_jobs Current dead-letter records.",
                    "# TYPE rag_dead_letter_jobs gauge",
                    f"rag_dead_letter_jobs {len(registry.list_dead_letter_jobs(500))}",
                ]
            )
        with self._lock:
            counters = list(self._counters.items())
            histograms = list(self._histograms.items())
        emitted_types: set[str] = set()
        for (name, labels), value in sorted(counters):
            if name not in emitted_types:
                lines.extend([f"# TYPE {name} counter"])
                emitted_types.add(name)
            lines.append(f"{name}{_label_text(labels)} {value:g}")
        for (name, labels), histogram in sorted(histograms):
            if name not in emitted_types:
                lines.extend([f"# TYPE {name} histogram"])
                emitted_types.add(name)
            for bucket in _BUCKETS:
                bucket_labels = tuple(sorted((*labels, ("le", "+Inf" if math.isinf(bucket) else f"{bucket:g}"))))
                lines.append(f"{name}_bucket{_label_text(bucket_labels)} {histogram.buckets[bucket]}")
            lines.append(f"{name}_count{_label_text(labels)} {histogram.count}")
            lines.append(f"{name}_sum{_label_text(labels)} {histogram.total:g}")
        return "\n".join(lines) + "\n"


production_metrics = ProductionMetrics()
