# 固定黄金集评测结果

本页记录 2026-07-14 在离线 `mock + memory + template` 配置下的固定回归结果。评测目标是发现代码、chunk、融合、排序、拒答或引用映射退化；它不测开放域知识，也不代表真实模型上的绝对质量。

![30 条黄金集的实际值、CI 阈值、类别和来源分布](assets/evaluation-scorecard.svg)

## 成绩卡

| 指标 | 实际值 | CI 最低值 | 余量 | 结论 |
| --- | ---: | ---: | ---: | --- |
| Recall@5 | 1.0000 | 0.90 | +0.10 | 通过 |
| MRR | 1.0000 | 0.75 | +0.25 | 通过 |
| 首条引用准确率 | 1.0000 | 0.75 | +0.25 | 通过 |
| 拒答准确率 | 1.0000 | 0.80 | +0.20 | 通过 |

命令：

```bash
npm run eval:retrieval
```

runner 会生成 `eval/reports/latest.md` 与 `latest.json`，CI 始终上传报告 artifact；任一指标低于 `eval/thresholds.json` 即返回非零退出码。

## 数据集构成

- 总计：30 条。
- 可回答：24 条（80%）。
- 应拒答：6 条（20%）。
- 固定来源文档：5 份脱敏资料。

类别分布：evaluation 7、refusal 6、retrieval 3；aigc、deployment、known-gap、local-demo、trust 各 2；architecture、backend、frontend、observability 各 1。

可回答 case 的期望来源分布：evaluation 7、technical 6、system 5、workflow 5、deployment 4。一个 case 可以接受多个期望来源，因此来源计数不必等于可回答 case 数。

## 四个指标为何同时保留

- Recall@5 检查目标证据是否进入前五，保护召回覆盖。
- MRR 检查第一个相关证据的位置，保护排序质量。
- 首条引用准确率检查第一条引用的来源与关键词，保护展示给用户的首要证据。
- 拒答准确率检查负样本没有被强行回答，防止通过降低门槛虚增 Recall。

单独优化任何一个指标都可能制造退化。例如无限增大 Top K 可能提高 Recall，却让首条引用变差；关闭 evidence gate 可能减少误拒答，却破坏负样本安全性。

## Case 判定

可回答 case 提供 `expected_sources` 和 `expected_keywords`。相关 citation 必须来自允许来源且命中至少一个关键字。拒答 case 使用 `should_answer=false`，返回明确拒答原因或零 citation 才算通过。

详细定义、JSONL 示例和新增 case 流程见[测试与评测](testing-and-evaluation.md)。

## 可解释限制

1. 固定资料和 template answer 让结果具有确定性，也使数据分布远小于真实业务。
2. 30 条 case 足以构成回归烟雾报警，不足以给出窄置信区间或类别级泛化结论。
3. 首条引用准确率不是所有答案主张的事实正确率；运行时 citation audit 另测覆盖和 unsupported claims。
4. hash embedding 只用于离线复现，不能用成绩推断真实语义 embedding 表现。
5. 当前没有对抗性 prompt injection、OCR 噪声、多语言长文档或跨文档矛盾的统计集。
6. 报告没有替代人工错误分析；指标通过时仍应抽查 case-level rows。

## 下一轮评测扩展

- 按 ingestion type、语言、文档长度和问题难度分层，报告宏平均与最差类别。
- 增加 chunk 边界、重复资料、冲突来源、OCR 噪声和 prompt injection case。
- 为 citation coverage、unsupported claims 和 answer acceptance 设置独立阈值。
- 接入真实 provider 时建立隔离的非确定性评测，不替换离线 CI 集；记录模型、prompt、embedding、维度和数据版本。
- 对线上负反馈采样、脱敏、人工标注，再进入版本化黄金集。

当前全量测试证据见[验证基线](validation-baseline.md)，生产质量边界见[已知限制](known-limitations.md)。
