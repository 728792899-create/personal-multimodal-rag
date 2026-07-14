# 术语表

| 术语 | 在本项目中的含义 |
| --- | --- |
| RAG | Retrieval-Augmented Generation；先检索资料，再在证据约束下回答 |
| Chunk | 从文档切分的最小检索片段，保留文档、页码、标题路径等 metadata |
| BM25 | 基于词项频率的稀疏检索，对专有名词和精确词面有效 |
| Embedding | 把文本映射为向量；默认 hash embedding 只用于离线可复现 |
| Vector store | 保存/搜索向量与 chunk 的 adapter：memory、Chroma 或 pgvector |
| Hybrid retrieval | 合并 BM25 与向量分支的检索方式 |
| Fusion | 对多个召回分支的候选进行权重合并和去重 |
| Candidate K | 进入融合/排序前的候选池规模 |
| Top K | 最终返回给回答阶段的证据条数 |
| MMR | Maximum Marginal Relevance；在相关性和结果多样性间取舍 |
| Rerank | 对已召回候选重新排序；不能补回初始召回遗漏 |
| No-answer gate | 判断证据是否足够；不足时输出拒答而非生成结论 |
| Citation | 指向真实 chunk 的引用，包含来源、片段、页码和分数 |
| Citation audit | 对回答主张、引用覆盖和 grounding 的生成后检查 |
| Retrieval Trace | 从 BM25 到引用审计的阶段化诊断记录 |
| Query rewrite | 生成检索改写；失败时回退原查询并进入 Trace |
| Fallback | 外部 provider 失败时采用的本地替代路径，必须可见且脱敏 |
| Recall@K | 前 K 条结果是否包含目标证据的比例 |
| MRR | 第一个相关结果排名倒数的平均值 |
| Eval draft | 由反馈或人工创建、尚未进入固定黄金集的候选 case |
| Golden set | 固定、脱敏、可重复执行并设有阈值的评测集 |
| Registry | SQLite 中保存的文档、内容、历史、反馈和操作数据 |
| Workspace | 生产多团队隔离单位；当前 Beta 尚未实现完整边界 |
| Trust boundary | 数据或控制权跨越不同信任级别的位置，必须重新校验和授权 |
| State machine | idle、pending、success、error、cancel、retry 等可见且可恢复的前端状态 |
| Social preview | GitHub 分享链接时显示的 1280×640 项目预览图，不是产品截图 |
| Responses provider | 使用 OpenAI-compatible `/v1/responses` 的回答 adapter |
| Offline default | mock embedding + memory vector + template answer 的零 Key 路径 |
