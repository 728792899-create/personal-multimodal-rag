# 100 条固定黄金集评测结果

本页记录 2026-07-15 在离线 `mock + memory + template` 配置下的 0.3 固定回归结果。它用于发现代码、chunk、知识库隔离、多模态映射、Graph provenance、排序、拒答或引用退化，不代表开放域或真实模型绝对质量。

![100 条黄金集的基础、多模态与 Graph 指标](assets/evaluation-scorecard.svg)

## 成绩卡

| 指标 | 实际值 | CI 最低值 | 结论 |
| --- | ---: | ---: | --- |
| Recall@5 | 1.0000 | 0.90 | 通过 |
| MRR | 0.9888 | 0.75 | 通过 |
| 首条引用准确率 | 0.9775 | 0.75 | 通过 |
| 拒答准确率 | 1.0000 | 0.80 | 通过 |
| 可回答接受率 | 1.0000 | 0.85 | 通过 |
| Modality Recall@5 | 1.0000 | 0.85 | 通过 |
| 表格单元准确率 | 1.0000 | 0.90 | 通过 |
| Caption 对齐 | 1.0000 | 0.90 | 通过 |
| 公式准确率 | 1.0000 | 0.90 | 通过 |
| Graph path precision | 1.0000 | 0.90 | 通过 |
| Graph evidence coverage | 1.0000 | 0.95 | 通过 |
| 多跳 Recall@5 | 1.0000 | 0.85 | 通过 |

```bash
npm run eval:retrieval
npm run eval:multimodal
npm run eval:graph
```

runner 生成 `eval/reports/latest.{md,json}`、`multimodal.{md,json}` 和 `graph.{md,json}`。CI 始终上传可读报告，任一门槛低于 `eval/thresholds.json` 或专项脚本定义即返回非零退出码。

## 数据集构成

- 总计 100 条：89 answerable / 11 refusal。
- 从 40 条 Durable Local 基线新增 60 条：12 图像、12 表格、8 公式、12 版面/OCR、10 多跳 Graph、6 冲突/拒答。
- 12 张真实 PNG fixture 在 `samples/multimodal-fixtures/images`；确定性 caption/OCR 与结构化证据位于 `samples/demo-documents/07-*` 至 `12-*`。
- DOCX case 仍从 JSON spec 生成 Office ZIP，并经过真实 DOCX parser；Graph case 经 native Graph-lite 建图、路径查找和 evidence element 映射。
- category/source 分布由 runner 从 JSONL 计算，不维护可漂移的人工计数表。

## 新指标如何判定

- Modality Recall@5：图像、表格、公式和版面 case 的目标证据是否进入前五。
- 表格单元、Caption 和公式：召回证据必须包含 case 声明的确定性单元、caption term 或规范化公式。
- Graph path precision：路径必须包含预期 entity 和 relation；没有 provenance 的路径不会进入评测输入。
- Graph evidence coverage：路径返回的 element ID 必须被最终前五 citation 覆盖。
- 多跳 Recall@5：10 个两跳 case 单独统计，避免被简单问题的总 Recall 掩盖。

## 判定边界

MRR 和首条引用没有被修饰成 1.0：少量旧 case 的正确证据在前五但不在第一位。这正是保留真实数值的意义；阈值通过不等于无需 case-level 分析。

局限：

1. fixture 和 template 使结果确定，也让分布远小于真实业务。
2. 新多模态指标验证本项目 IR/检索映射，不代表任意 OCR/VLM 的开放集准确率。
3. hash embedding 不代表生产语义 embedding；外部 Provider 需要独立版本化评测。
4. 仍需用真实业务的扫描件、长表格、多语言和冲突文档做人工标注外部集。

定义和新增流程见[测试与评测](testing-and-evaluation.md)，全量命令证据见[验证基线](validation-baseline.md)。
