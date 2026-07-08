from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_json(command: list[str]) -> dict:
    output = subprocess.check_output(command, cwd=ROOT, text=True)
    return json.loads(output)


def main() -> None:
    retrieval = run_json(["python3", "scripts/run_retrieval_eval.py"])
    profiles = run_json(["python3", "scripts/compare_retrieval_profiles.py"])
    out_dir = ROOT / "eval" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"retrieval-report-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"

    lines = [
        "# RAG Retrieval Evaluation Report",
        "",
        f"- Generated at: {datetime.now().isoformat(timespec='seconds')}",
        f"- Cases: {retrieval['cases']}",
        f"- Recall@5: {retrieval['recall_at_5']}",
        f"- MRR: {retrieval['mrr']}",
        f"- Citation Precision: {retrieval['citation_precision']}",
        "",
        "## Profile Comparison",
        "",
        "| Profile | Recall@5 | MRR | Citation Precision | No-answer Accuracy |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in profiles["profiles"]:
        lines.append(
            f"| {row['profile']} | {row['recall_at_5']} | {row['mrr']} | "
            f"{row['citation_precision']} | {row['no_answer_accuracy']} |"
        )

    lines.extend(["", "## Case Details", ""])
    for row in retrieval["rows"]:
        sources = ", ".join(row["top_sources"]) if row["top_sources"] else "-"
        lines.extend(
            [
                f"### {row['question']}",
                "",
                f"- Hit: {row['hit']}",
                f"- First relevant rank: {row['first_relevant_rank']}",
                f"- Citation precision: {row['citation_precision']}",
                f"- Top sources: {sources}",
                "",
            ]
        )

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(str(out_path))


if __name__ == "__main__":
    main()
