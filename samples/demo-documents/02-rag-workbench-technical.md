# 可解释 RAG 工作台技术说明

项目把 RAG 链路拆成文档处理、索引、检索、排序、引用审计和答案生成几个模块。这样做的好处是每个阶段都可以单独观察和替换，而不是把所有逻辑包在一个黑盒调用里。

## 检索策略

- BM25 负责关键词命中，适合专有名词、配置项和错误码。
- Hash embedding 负责本地演示，不代表生产向量质量。
- OpenAI-compatible embedding、Chroma 和 pgvector 是可选增强。
- Hybrid profile 会综合 BM25 和向量分数。
- MMR 用于减少重复片段，提高上下文覆盖度。

## 可信度设计

答案返回引用片段、页码或 chunk 编号、score breakdown、retrieval trace 和 citation audit。证据不足时系统会拒答或提示资料缺口，避免把无依据内容包装成确定结论。

## 可观测性

前端可以查看 raw candidates、deduped candidates、MMR selected、returned、matched terms、fallbacks、rewrite status、vector status 和 rerank status。这些信息用于定位问题发生在 query、召回、排序还是生成阶段。
