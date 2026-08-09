# v1.0 私有评测集契约

真实业务问题、答案和证据 ID 不提交到 Git。默认私有文件：

- `data/validation/v1-annotations.jsonl`：200 条人工标注，60 条调优、140 条锁定回归。
- `data/validation/v1-blind.jsonl`：配置冻结后收集的至少 100 条真实业务盲测。

每条标注必须包含：

```json
{
  "id": "stable-id",
  "question": "真实业务问题",
  "category": "exact",
  "split": "tune",
  "should_answer": true,
  "expected_evidence_groups": [["element-id-a"], ["element-id-b", "element-id-c"]],
  "modalities": ["text"],
  "cross_document": false,
  "version_conflict": false,
  "reviewer_1": {"id": "reviewer-a", "category": "exact", "evidence_ids": ["element-id-a"], "attestation": "human-reviewed"},
  "reviewer_2": null
}
```

盲测还必须包含 `human_originated: true`、`configuration_frozen: true` 和业务验收字段 `accepted`。运行：

```bash
python3 scripts/validate_v1_dataset.py
```

校验器严格检查数量、分层、跨模态覆盖、重复 ID、40 条双审、Cohen κ、证据 F1 和盲测隔离；机器生成候选不能计入这些数量。
