# 评测与反馈闭环说明

系统支持把用户负反馈转换成 eval draft，再通过脚本运行检索评测。评测关注 Recall@K、MRR、引用准确率和拒答行为，目的是发现检索策略是否稳定，而不是只观察单次回答是否顺眼。

## 反馈类型

- no_evidence：问题没有可用证据。
- retrieval_miss：资料里有答案但没有召回。
- wrong_citation：引用片段无法支撑答案。
- unsupported_claim：答案里出现无证据推断。
- bad_answer：表达或组织方式不符合需求。

## 迭代方式

先收集真实问题和失败样本，再对比 keyword、semantic、hybrid、hybrid + rerank 等 profile。每次调整后用同一批样本回归，避免只对某一个问题做局部优化。
