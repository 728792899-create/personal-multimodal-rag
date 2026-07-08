# 面试讲述手册

## 30 秒版本

我做的是一个个人多模态 RAG 知识库工作台，支持文件和 URL 导入，后端完成文档解析、chunk 切分、混合检索、重排和证据约束回答；前端除了展示答案，还展示引用上下文、检索 trace、可信度审计、反馈评测和知识卡片。这个项目重点不是堆功能，而是把 RAG 应用里“检索是否准确、引用是否可信、失败如何定位、反馈如何优化”做成闭环。

## 2 分钟版本

项目分四层：

1. 数据接入层：支持 PDF、Markdown、文本、图片和 URL 导入，保存文档 metadata、质量评分和索引生命周期。
2. 检索层：使用 BM25 + Vector 混合召回，加入 Query Rewrite、MMR、Rerank、No-answer Gate 和文档质量加权。
3. 生成层：答案生成必须基于 citations，证据不足时拒答；回答后做引用覆盖率和 unsupported claims 检查。
4. 产品层：前端分普通模式和专家模式，普通用户看回答和建议，专家可以看 trace、策略对比、指标和评测草稿。

项目里我最重视的是可解释性和可复盘。比如一次回答不好，我能从 trace 判断是 query 没改写好、BM25 没命中、向量召回偏了、rerank 排错了，还是文档本身缺资料。用户点“不准确”后会生成 eval draft，后面可以用同一批问题比较不同检索策略。

## 技术难点怎么讲

### 难点 1：关键词和语义召回各有缺陷

回答：

BM25 对专业名词、字段、精确短语很强，但同义表达容易漏召回；向量检索能找语义相近内容，但会误召回弱相关片段。所以我做了 hybrid retrieval，把 BM25 和 vector score 按权重融合，再用 MMR 控制重复，最后做 rerank。

### 难点 2：如何降低幻觉

回答：

我没有只靠 prompt 限制模型，而是做了多层控制：检索阶段有 no-answer threshold，证据不足直接拒答；生成阶段要求引用；生成后做 citation audit，统计引用覆盖率和 unsupported claims；用户反馈还会进入 eval draft。

### 难点 3：如何证明检索质量

回答：

我做了两类评测：一类是脚本评测，输出 Recall@5、MRR、Citation Precision；另一类是前端评测工作台，用户反馈和手动 case 都可以运行。这样不是凭感觉调参数，而是用 case 集对比策略。

### 难点 4：为什么要有普通模式和专家模式

回答：

普通用户不应该看到一堆 BM25、MMR 参数，所以普通模式只保留上传、问答、引用和建议；专家模式才展示检索参数、trace、策略对比和评测。这样既能面向真实用户，又能在面试中展示工程细节。

## 面试官可能追问

### 如果文档很多，性能怎么办？

可以回答：

当前版本已抽象 vector store，支持 Chroma 和 pgvector；后续可以做分页加载、异步索引、embedding cache、查询 cache、批量 upsert 和 rerank 前候选压缩。前端已有系统指标入口，可以继续扩展耗时和 cache 命中率。

### 如果引用内容不支持答案怎么办？

可以回答：

当前已经做 citation audit，检查答案句子是否带引用，并标出 unsupported claims。下一步可以接 NLI 或 LLM-as-judge 做语义蕴含判断，判断“引用是否真的支持这句话”。

### 为什么不用 LangChain？

可以回答：

这个项目为了展示 RAG 核心链路，我自己拆了 document processor、retriever、reranker、answer generator 和 vector store。这样面试时能讲清楚每个阶段如何工作，而不是把复杂度藏在框架里。后续如果要接生产生态，也可以把这些模块替换为 LangChain/LlamaIndex 的组件。

## 避免表述

- 避免说“完全解决幻觉”，改成“通过拒答、引用审计和评测降低幻觉风险”。
- 避免说“真实多模态理解”，除非演示的是 OCR/VLM 真实语义解析。
- 避免说“数据规模很大”，当前更适合说“面向个人知识库和作品集场景”。
- 避免说“算法很先进”，要具体说 hybrid retrieval、MMR、rerank、parent-child context、eval flywheel。

