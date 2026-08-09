from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


EVIDENCE_SCHEMA_VERSION = 2
CANDIDATE_VERSION = "1.0.0-rc.1"


def _load_evidence(path: str | Path) -> tuple[dict, list[str]]:
    target = Path(path)
    if not target.is_file():
        return {}, ["发布证据文件不存在。"]
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, ["发布证据文件不可读，或不是有效的 JSON。"]
    if not isinstance(payload, dict):
        return {}, ["发布证据的 JSON 根节点必须是对象。"]
    return payload, []


def _group(evidence: dict, key: str) -> dict:
    value = evidence.get(key)
    return value if isinstance(value, dict) else {}


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def build_release_readiness(path: str | Path) -> dict:
    """Evaluate auditable RC evidence without treating missing values as zero.

    A zero-target gate (for example, fabricated citations) is especially easy to
    pass accidentally when an absent value is coerced to ``0``. Every gate below
    therefore checks both presence/type and the threshold.
    """

    evidence, errors = _load_evidence(path)
    corpus = _group(evidence, "corpus")
    usage = _group(evidence, "usage")
    operations = _group(evidence, "operations")
    quality = _group(evidence, "quality")
    ann = _group(evidence, "ann")
    comparison = _group(evidence, "comparison")
    reranking = _group(evidence, "reranking")
    performance = _group(evidence, "performance")
    audit = _group(evidence, "audit")

    gates: list[dict[str, Any]] = []

    def exact(gate_id: str, label: str, observed: object, required: object) -> None:
        gates.append(
            {
                "id": gate_id,
                "label": label,
                "passed": observed == required,
                "observed": observed,
                "required": required,
            }
        )

    def minimum(gate_id: str, label: str, observed: object, required: float) -> None:
        numeric = _number(observed)
        gates.append(
            {
                "id": gate_id,
                "label": label,
                "passed": numeric is not None and numeric >= required,
                "observed": observed if numeric is not None else None,
                "required": required,
            }
        )

    def maximum(gate_id: str, label: str, observed: object, required: float) -> None:
        numeric = _number(observed)
        gates.append(
            {
                "id": gate_id,
                "label": label,
                "passed": numeric is not None and numeric <= required,
                "observed": observed if numeric is not None else None,
                "required": required,
            }
        )

    def boolean(gate_id: str, label: str, observed: object) -> None:
        gates.append(
            {
                "id": gate_id,
                "label": label,
                "passed": observed is True,
                "observed": observed if isinstance(observed, bool) else None,
                "required": True,
            }
        )

    def mapping_minimum(
        gate_id: str,
        label: str,
        observed: object,
        required: float,
    ) -> None:
        values = list(observed.values()) if isinstance(observed, dict) else []
        numerics = [_number(value) for value in values]
        valid = bool(numerics) and all(value is not None for value in numerics)
        lowest = min(value for value in numerics if value is not None) if valid else None
        gates.append(
            {
                "id": gate_id,
                "label": label,
                "passed": lowest is not None and lowest >= required,
                "observed": {
                    "minimum": lowest,
                    "strata": observed if isinstance(observed, dict) else None,
                },
                "required": {"each_at_least": required, "non_empty": True},
            }
        )

    # Evidence identity and auditability.
    exact(
        "evidence_schema",
        "发布证据模式版本",
        evidence.get("schema_version"),
        EVIDENCE_SCHEMA_VERSION,
    )
    exact(
        "candidate_version",
        "候选版本与本次 RC 一致",
        evidence.get("candidate_version"),
        CANDIDATE_VERSION,
    )
    boolean("indexed_hashes_match", "索引内容哈希与语料清单一致", audit.get("indexed_hashes_match"))
    boolean("soak_chain_valid", "14 天持续运行证据链有效", audit.get("soak_chain_valid"))

    # Team baseline and human-labelled corpus.
    minimum("licensed_materials", "有明确许可证的真实资料来源", corpus.get("licensed_materials"), 20)
    minimum("non_fixture_documents", "已索引的非 fixture 文档", corpus.get("non_fixture_documents"), 200)
    minimum("annotated_questions", "人工标注的基准问题", corpus.get("annotated_questions"), 200)
    minimum("locked_regression_questions", "锁定的回归集问题", corpus.get("locked_regression_questions"), 140)
    minimum("second_reviewed_questions", "盲态二次复核问题", corpus.get("second_reviewed_questions"), 40)
    minimum("label_agreement_kappa", "标签一致性 κ", corpus.get("label_agreement_kappa"), 0.75)
    minimum("evidence_agreement_f1", "证据一致性 F1", corpus.get("evidence_agreement_f1"), 0.80)

    # Retrieval, multimodal, citation and refusal quality.
    minimum("recall_at_5", "证据 Recall@5", quality.get("recall_at_5"), 0.90)
    minimum("mrr_at_10", "MRR@10", quality.get("mrr_at_10"), 0.78)
    minimum("multihop_chain_at_10", "多跳完整证据链@10", quality.get("multihop_chain_at_10"), 0.80)
    minimum("table_recall_at_10", "表格 Recall@10", quality.get("table_recall_at_10"), 0.85)
    minimum("image_recall_at_10", "图片/OCR Recall@10", quality.get("image_recall_at_10"), 0.85)
    minimum("formula_recall_at_10", "公式 Recall@10", quality.get("formula_recall_at_10"), 0.85)
    minimum("citation_accuracy", "引用正确率", quality.get("citation_accuracy"), 0.90)
    minimum("factual_coverage", "事实覆盖率", quality.get("factual_coverage"), 0.90)
    maximum(
        "fabricated_or_invalid_citations",
        "虚构或失效引用数",
        quality.get("fabricated_or_invalid_citations"),
        0,
    )
    minimum("refusal_f1", "拒答 F1", quality.get("refusal_f1"), 0.88)
    maximum(
        "answerable_false_refusal_rate",
        "可回答问题误拒答率",
        quality.get("answerable_false_refusal_rate"),
        0.08,
    )
    minimum("blind_test_cases", "未参与调优的真实盲测数", quality.get("blind_test_cases"), 100)
    minimum("blind_acceptance_rate", "真实盲测接受率", quality.get("blind_acceptance_rate"), 0.85)

    # ANN fidelity and comparisons against the frozen legacy baseline.
    minimum("hnsw_recall_at_50", "HNSW Recall@50（总体）", ann.get("hnsw_recall_at_50"), 0.98)
    mapping_minimum(
        "hnsw_primary_strata_recall_at_50",
        "HNSW Recall@50（各主要分层）",
        ann.get("primary_strata_recall_at_50"),
        0.95,
    )
    minimum(
        "difficult_core_best_improvement",
        "困难查询至少一项核心指标改善",
        comparison.get("difficult_core_best_improvement"),
        0.05,
    )
    maximum(
        "overall_worst_regression",
        "其他总体指标最大退化",
        comparison.get("overall_worst_regression"),
        0.01,
    )

    # Reranking is optional, but its enabled/disabled state must be explicit.
    rerank_enabled = reranking.get("enabled")
    gates.append(
        {
            "id": "rerank_policy_declared",
            "label": "DeepSeek 重排默认状态已明确记录",
            "passed": isinstance(rerank_enabled, bool),
            "observed": rerank_enabled if isinstance(rerank_enabled, bool) else None,
            "required": "boolean",
        }
    )
    if rerank_enabled is True:
        minimum(
            "rerank_mrr_improvement",
            "DeepSeek 重排触发子集 MRR 改善",
            reranking.get("trigger_subset_mrr_improvement"),
            0.03,
        )
        maximum(
            "rerank_trigger_rate",
            "DeepSeek 重排触发率",
            reranking.get("trigger_rate"),
            0.50,
        )

    # Fixed 50k / 5-concurrency performance contract and cloud cost budget.
    minimum("benchmark_chunks", "性能基准分块数", performance.get("benchmark_chunks"), 50_000)
    minimum("benchmark_concurrency", "性能基准并发数", performance.get("benchmark_concurrency"), 5)
    maximum("hnsw_p95_ms", "HNSW p95（ms）", performance.get("hnsw_p95_ms"), 200)
    maximum(
        "simple_retrieval_p95_ms",
        "普通完整检索 p95（ms）",
        performance.get("simple_retrieval_p95_ms"),
        2_000,
    )
    maximum(
        "complex_retrieval_p95_ms",
        "含规划/重排的复杂检索 p95（ms）",
        performance.get("complex_retrieval_p95_ms"),
        6_000,
    )
    maximum("simple_ttft_p95_ms", "简单查询首字节 p95（ms）", performance.get("simple_ttft_p95_ms"), 6_000)
    maximum("complex_ttft_p95_ms", "复杂查询首字节 p95（ms）", performance.get("complex_ttft_p95_ms"), 10_000)
    maximum(
        "automatic_routing_cost_ratio",
        "自动路由平均查询成本倍数",
        performance.get("automatic_routing_cost_ratio"),
        1.35,
    )

    # 14-day production soak, safety incidents and complete-stack recovery.
    minimum("representative_queries", "14 天代表性真实查询", usage.get("representative_queries"), 500)
    minimum("soak_days", "连续部署运行天数", operations.get("soak_days"), 14)
    minimum("availability", "14 天可用率", operations.get("availability"), 0.995)
    boolean("provider_failure_contract", "云端供应商故障合同测试", operations.get("provider_failure_contract_passed"))
    minimum("rbac_authorization_pass_rate", "RBAC 越权测试通过率", operations.get("rbac_authorization_pass_rate"), 1.0)
    boolean("restore_drill", "完整生产恢复演练", operations.get("restore_drill_passed"))
    boolean("full_stack_rollback", "完整索引+嵌入+路由+重排回滚演练", operations.get("full_stack_rollback_passed"))
    maximum("rollback_rto_minutes", "回滚 RTO（分钟）", operations.get("rollback_rto_minutes"), 10)
    maximum("source_rpo_lost_records", "源数据 RPO 丢失记录数", operations.get("source_rpo_lost_records"), 0)
    boolean(
        "five_xx_rollback_trigger",
        "10 分钟 5xx >5% 自动回滚触发已验证",
        operations.get("five_xx_rollback_trigger_verified"),
    )
    for key, label in (
        ("permission_bypass_incidents", "权限绕过事故数"),
        ("index_pollution_incidents", "索引污染事故数"),
        ("data_loss_incidents", "数据丢失事故数"),
        ("fabricated_citation_incidents", "虚构引用事故数"),
        ("secret_leak_incidents", "密钥泄漏事故数"),
        ("unresolved_sev1", "未解决 Sev-1 数"),
    ):
        maximum(key, label, operations.get(key), 0)

    passed = sum(1 for gate in gates if gate["passed"])
    ready = not errors and passed == len(gates)
    return {
        "target_version": "1.0.0",
        "candidate_version": CANDIDATE_VERSION,
        "ready": ready,
        "status": "ready" if ready else "blocked",
        "passed_gates": passed,
        "total_gates": len(gates),
        "gates": gates,
        "errors": errors,
        "evidence_updated_at": str(evidence.get("updated_at") or ""),
        # An RC readiness report never asserts that v1.0 is already production-ready.
        "production_ready_claim": False,
    }
