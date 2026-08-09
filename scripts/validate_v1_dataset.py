#!/usr/bin/env python3
"""Validate private v1.0 annotations without exposing their contents."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPEC = ROOT / "eval" / "v1" / "distribution.json"


def load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        raise ValueError(f"评测文件不存在：{path}")
    rows: list[dict] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        row = json.loads(raw)
        row_id = str(row.get("id") or "").strip()
        if not row_id or row_id in seen:
            raise ValueError(f"第 {line_number} 行 ID 缺失或重复")
        if not str(row.get("question") or "").strip():
            raise ValueError(f"{row_id} 缺少问题")
        seen.add(row_id)
        rows.append(row)
    return rows


def cohen_kappa(pairs: list[tuple[str, str]]) -> float:
    if not pairs:
        return 0.0
    observed = sum(left == right for left, right in pairs) / len(pairs)
    left_counts = Counter(left for left, _ in pairs)
    right_counts = Counter(right for _, right in pairs)
    expected = sum(
        left_counts[label] / len(pairs) * right_counts[label] / len(pairs)
        for label in set(left_counts) | set(right_counts)
    )
    return 1.0 if expected == 1.0 and observed == 1.0 else (observed - expected) / max(1 - expected, 1e-12)


def evidence_f1(left: list[str], right: list[str]) -> float:
    left_set, right_set = set(map(str, left)), set(map(str, right))
    if not left_set and not right_set:
        return 1.0
    precision = len(left_set & right_set) / max(len(left_set), 1)
    recall = len(left_set & right_set) / max(len(right_set), 1)
    return 2 * precision * recall / max(precision + recall, 1e-12)


def validate_annotations(rows: list[dict], spec: dict) -> dict:
    errors: list[str] = []
    if len(rows) != int(spec["total_annotations"]):
        errors.append(f"人工标注应为 {spec['total_annotations']} 条，实际 {len(rows)} 条")
    categories = Counter(str(row.get("category") or "") for row in rows)
    splits = Counter(str(row.get("split") or "") for row in rows)
    if categories != Counter({key: int(value) for key, value in spec["categories"].items()}):
        errors.append(f"类别分布不符：{dict(categories)}")
    if splits != Counter({key: int(value) for key, value in spec["splits"].items()}):
        errors.append(f"数据分割不符：{dict(splits)}")

    cross_counts = Counter()
    for row in rows:
        modalities = set(map(str, row.get("modalities") or []))
        if "table" in modalities:
            cross_counts["table"] += 1
        if modalities & {"image", "ocr", "caption"}:
            cross_counts["image_or_ocr"] += 1
        if "formula" in modalities:
            cross_counts["formula"] += 1
        if row.get("cross_document") is True:
            cross_counts["cross_document"] += 1
        if row.get("version_conflict") is True:
            cross_counts["version_conflict"] += 1
        if not isinstance(row.get("expected_evidence_groups"), list):
            errors.append(f"{row['id']} 缺少 expected_evidence_groups")
        reviewer = row.get("reviewer_1") if isinstance(row.get("reviewer_1"), dict) else {}
        if reviewer.get("attestation") != "human-reviewed":
            errors.append(f"{row['id']} 缺少主审人工声明")

    for label, minimum in spec["cross_labels_minimum"].items():
        if cross_counts[label] < int(minimum):
            errors.append(f"{label} 至少 {minimum} 条，实际 {cross_counts[label]} 条")

    double_rows = [row for row in rows if isinstance(row.get("reviewer_2"), dict)]
    if len(double_rows) != int(spec["double_reviewed"]):
        errors.append(f"双审应为 {spec['double_reviewed']} 条，实际 {len(double_rows)} 条")
    pairs: list[tuple[str, str]] = []
    evidence_scores: list[float] = []
    for row in double_rows:
        first, second = row["reviewer_1"], row["reviewer_2"]
        if second.get("attestation") != "human-reviewed":
            errors.append(f"{row['id']} 缺少复审人工声明")
        pairs.append((str(first.get("category") or ""), str(second.get("category") or "")))
        evidence_scores.append(evidence_f1(first.get("evidence_ids") or [], second.get("evidence_ids") or []))
    kappa = cohen_kappa(pairs)
    mean_f1 = sum(evidence_scores) / max(len(evidence_scores), 1)
    if kappa < float(spec["minimum_category_kappa"]):
        errors.append(f"类别 Cohen κ {kappa:.4f} 未达到 {spec['minimum_category_kappa']}")
    if mean_f1 < float(spec["minimum_evidence_f1"]):
        errors.append(f"证据一致性 F1 {mean_f1:.4f} 未达到 {spec['minimum_evidence_f1']}")
    return {
        "valid": not errors,
        "annotations": len(rows),
        "categories": dict(categories),
        "splits": dict(splits),
        "cross_labels": dict(cross_counts),
        "double_reviewed": len(double_rows),
        "category_kappa": round(kappa, 4),
        "evidence_f1": round(mean_f1, 4),
        "errors": errors,
    }


def validate_blind(rows: list[dict], spec: dict, annotation_ids: set[str]) -> dict:
    errors: list[str] = []
    required = int(spec["blind_questions"])
    if len(rows) < required:
        errors.append(f"真实盲测至少 {required} 条，实际 {len(rows)} 条")
    for row in rows:
        if row["id"] in annotation_ids:
            errors.append(f"盲测 ID 与调优/回归集重叠：{row['id']}")
        if row.get("human_originated") is not True:
            errors.append(f"{row['id']} 未声明为真实人工问题")
        if row.get("configuration_frozen") is not True:
            errors.append(f"{row['id']} 不是在配置冻结后采集")
        if not isinstance(row.get("accepted"), bool):
            errors.append(f"{row['id']} 缺少业务验收结果")
    return {"valid": not errors, "blind_questions": len(rows), "errors": errors}


def contract_rows(spec: dict) -> tuple[list[dict], list[dict]]:
    rows: list[dict] = []
    category_index = 0
    for category, count in spec["categories"].items():
        for _ in range(int(count)):
            index = len(rows)
            modalities = ["text"]
            if index < 30:
                modalities.append("table")
            if index < 20:
                modalities.append("image")
            if index < 10:
                modalities.append("formula")
            primary = {"id": "a", "category": category, "evidence_ids": [f"e-{index}"], "attestation": "human-reviewed"}
            rows.append({
                "id": f"contract-{index}", "question": "contract only", "category": category,
                "split": "tune" if index < int(spec["splits"]["tune"]) else "regression",
                "expected_evidence_groups": [[f"e-{index}"]], "modalities": modalities,
                "cross_document": index < 30, "version_conflict": index < 20,
                "reviewer_1": primary, "reviewer_2": dict(primary) if index < int(spec["double_reviewed"]) else None,
            })
        category_index += 1
    blind = [{
        "id": f"blind-contract-{index}", "question": "contract only", "human_originated": True,
        "configuration_frozen": True, "accepted": True,
    } for index in range(int(spec["blind_questions"]))]
    return rows, blind


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 v1.0 私有人工评测集")
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--annotations", type=Path, default=ROOT / "data" / "validation" / "v1-annotations.jsonl")
    parser.add_argument("--blind", type=Path, default=ROOT / "data" / "validation" / "v1-blind.jsonl")
    parser.add_argument("--contract-only", action="store_true")
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    annotations, blind = contract_rows(spec) if args.contract_only else (load_jsonl(args.annotations), load_jsonl(args.blind))
    annotation_result = validate_annotations(annotations, spec)
    blind_result = validate_blind(blind, spec, {row["id"] for row in annotations})
    result = {"valid": annotation_result["valid"] and blind_result["valid"], "annotations": annotation_result, "blind": blind_result, "contract_only": args.contract_only}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
