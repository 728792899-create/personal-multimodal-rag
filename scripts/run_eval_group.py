from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from run_retrieval_eval import ROOT, build_offline_engine, evaluate_cases, load_jsonl, summarize_rows


GROUPS = {
    "multimodal": {
        "categories": {"image", "table", "formula", "layout-ocr"},
        "metrics": {
            "modality_recall_at_5": 0.85,
            "table_cell_accuracy": 0.90,
            "caption_alignment": 0.90,
            "formula_accuracy": 0.90,
        },
    },
    "graph": {
        "categories": {"multihop-graph"},
        "metrics": {
            "multihop_recall_at_5": 0.85,
            "graph_path_precision": 0.90,
            "graph_evidence_coverage": 0.95,
        },
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description="运行聚焦且确定性的 0.3 分组评测")
    parser.add_argument("group", choices=sorted(GROUPS))
    args = parser.parse_args()
    spec = GROUPS[args.group]
    cases = [
        case for case in load_jsonl(ROOT / "eval" / "cases.jsonl")
        if case.get("category") in spec["categories"]
    ]
    rows = evaluate_cases(cases, build_offline_engine(ROOT / "samples" / "demo-documents"))
    summary = summarize_rows(rows)
    checks = [
        {"metric": metric, "actual": float(summary[metric]), "minimum": minimum, "passed": float(summary[metric]) >= minimum}
        for metric, minimum in spec["metrics"].items()
    ]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "group": args.group,
        "case_count": len(cases),
        "summary": summary,
        "checks": checks,
        "passed": all(item["passed"] for item in checks),
    }
    report_dir = ROOT / "eval" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / f"{args.group}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        f"# {args.group.title()} 回归报告",
        "",
        f"Case：{len(cases)}",
        "",
        "| 指标 | 实际 | 阈值 | 结果 |",
        "| --- | ---: | ---: | :---: |",
        *[
            f"| {item['metric']} | {item['actual']:.4f} | {item['minimum']:.4f} | {'通过' if item['passed'] else '失败'} |"
            for item in checks
        ],
        "",
    ]
    (report_dir / f"{args.group}.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
