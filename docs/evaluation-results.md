# 固定黄金集评测结果

本页记录 2026-07-14 在离线 `mock + memory + template` 配置下的 0.2 固定回归结果。它用于发现代码、chunk、知识库隔离、融合、排序、拒答或引用映射退化，不代表开放域或真实模型绝对质量。

![40 条黄金集的实际值、CI 阈值、类别和来源分布](assets/evaluation-scorecard.svg)

## 成绩卡

| 指标 | 实际值 | CI 最低值 | 余量 | 结论 |
| --- | ---: | ---: | ---: | --- |
| Recall@5 | 1.0000 | 0.90 | +0.10 | 通过 |
| MRR | 0.9844 | 0.75 | +0.2344 | 通过 |
| 首条引用准确率 | 0.9688 | 0.75 | +0.2188 | 通过 |
| 拒答准确率 | 1.0000 | 0.80 | +0.20 | 通过 |
| 回答接受准确率 | 1.0000 | 0.85 | +0.15 | 通过 |

```bash
npm run eval:retrieval
```

runner 生成 `eval/reports/latest.md` 与 `latest.json`；CI 始终上传可读报告，任一指标低于 `eval/thresholds.json` 即返回非零退出码。

## 数据集构成

- 总计 40 条：32 answerable（80%）/ 8 refusal（20%）。
- 6 份脱敏来源，包括运行时从固定 JSON spec 构建并交给真实 DOCX parser 的表格文档。
- 在 0.1 基础上增加 knowledge-base isolation、multi-turn follow-up、DOCX table、provider/index-version 回归。
- category/source 的精确分布由 runner 从 JSONL 计算并写入 latest report，避免人工表格与数据漂移。

## 五个指标为何同时保留

- Recall@5：目标证据是否进入前五。
- MRR：第一个相关证据是否靠前。
- 首条引用准确率：用户首先看到的来源与关键词是否正确。
- 拒答准确率：负样本是否没有被弱匹配强行回答。
- 回答接受准确率：可回答问题是否被过高 evidence gate 错误拒绝。

MRR 和首条引用没有被修饰成 1.0：当前有少量 case 的正确来源不在第一位。这正是保留真实数值的意义；阈值通过不等于无需 case-level 分析。

## 判定与边界

可回答 case 指定 `expected_sources` 和 `expected_keywords`；相关 citation 必须来自允许来源且命中关键字。拒答 case 使用 `should_answer=false`，返回明确拒答或零 citation 才算通过。知识库 case 还校验非选中 KB 不参与候选；DOCX case 必须经过 Office ZIP/paragraph/table parser，而不是直接把 JSON 文本当文档。

局限：

1. 固定资料和模板回答使结果确定，也让分布远小于真实业务。
2. 40 条只能作为回归烟雾报警，不能给出窄置信区间或泛化结论。
3. 首条引用准确率不是回答所有主张的事实正确率；运行时 citation audit 另测 coverage/unsupported claims。
4. hash embedding 不代表生产语义 embedding；外部 Provider 需要单独版本化评测。
5. 仍缺 OCR 噪声、长文冲突、prompt injection、多语言和人工标注线上样本。

下一步应扩展到 100+ 困难 case，按类型/语言/长度/难度报告宏平均与最差类别，并为 citation coverage 建立人工校准集。

定义和新增流程见[测试与评测](testing-and-evaluation.md)，全量命令证据见[验证基线](validation-baseline.md)。
