# 个人多模态 RAG 知识库问答系统深度优化方案

## 1. 方案定位

如果我是这个项目的深度使用用户，我最关心的不是“能不能问答一次”，而是：

- 文档多了以后还能不能稳定检索到正确证据。
- 答案是否严格基于引用片段，能不能解释为什么这么答。
- 上传、更新、删除资料后索引是否一致，不会出现脏数据。
- 前端是否能像一个真实知识库产品，而不是一个接口调试页。
- 面试时能否讲清楚 RAG 工程链路，而不是只说“接了模型 API”。

所以后续优化目标应该从“功能堆叠”转向“可验证、可调试、可复用、可展示”的产品型 RAG 系统。

## 2. 当前项目判断

当前项目已经具备比较好的骨架：

- 后端使用 FastAPI，模块拆分为文档解析、embedding provider、vector store、retriever、reranker、rag engine。
- 前端使用 Vue 3 + TypeScript，已经能展示文档列表、问答、引用证据和检索分数。
- 检索链路已经有 BM25、向量检索、混合排序、keyword rerank 和 retrieval trace。
- 已经预留 Chroma / pgvector / OpenAI-compatible provider 的接口。
- 已有 pytest 和基础 eval 脚本，说明不是纯 UI demo。

但深度使用时会暴露这些问题：

- 当前中转站 key 支持 Responses/Chat，不支持 embeddings；不能把它包装成“真实 OpenAI embedding”。
- `ChromaVectorStore` 当前只把 Chroma 作为落盘容器，重启后没有从 Chroma metadata 反向恢复 `chunks` 映射，持久化不完整。
- 图片解析目前是 placeholder，不能真正称为“多模态理解”。
- 回答生成目前是规则拼接，不是真正 LLM 基于证据生成。
- 文档上传是同步流程，文档稍大时容易卡住前端等待。
- 缺少知识库、标签、会话历史、索引状态、失败重试、批量导入等真实产品能力。
- 评测只做关键词命中，不能完整反映 RAG 质量。

## 3. 总体升级路线

建议把项目升级为四层架构：

```text
数据接入层
PDF / Markdown / TXT / 图片 / 网页 / 文件夹批量导入
        ↓
索引构建层
解析清洗 / chunk 切分 / metadata / embedding / Chroma 持久化 / 索引任务状态
        ↓
检索排序层
BM25 / 向量召回 / Query Rewrite / Multi-query / Rerank / MMR / Trace
        ↓
问答应用层
证据约束回答 / 引用定位 / 会话历史 / 知识库管理 / 评测面板 / 录屏演示
```

核心原则：

- 当前可用的中转站 key 用在 `Responses Answer Generator` 和 `Query Rewrite`，不要用在 embedding。
- embedding 层单独接入真正支持 `/embeddings` 的 provider，或先接本地 embedding 模型。
- Chroma 必须做成真正可重启恢复的持久化向量库。
- 前端要从“演示页”升级为“知识库工作台”。

## 4. 优先级一：把当前 key 用在答案生成层

当前 key 的价值不在 embedding，而在 Responses/Chat。建议新增 `AnswerGenerator` 模块：

```text
backend/app/services/answer_generator.py
```

接口设计：

```python
class BaseAnswerGenerator:
    def generate(self, question: str, citations: list[dict], trace: dict) -> dict:
        ...
```

实现两个 provider：

- `TemplateAnswerGenerator`：默认离线模式，继续使用当前规则拼接。
- `OpenAIResponsesAnswerGenerator`：使用当前中转站 key 调用 `/responses`，模型为 `gpt-5.5`。

环境变量建议：

```env
ANSWER_PROVIDER=responses
ANSWER_MODEL=gpt-5.5
ANSWER_BASE_URL=https://api.apikey.fun
ANSWER_API_KEY=...
```

提示词要求：

- 只能基于传入的 citations 回答。
- 每个结论必须带引用编号。
- 证据不足时必须回答“无法确定”。
- 不允许使用模型自身知识补充事实。
- 输出结构固定为：答案、依据、不确定性、后续建议。

这一步可以直接把项目从“检索 demo”升级为“证据约束型 RAG 问答系统”。面试时也更好讲：当前 key 不做 embedding，但负责最终答案生成和查询改写，架构上实现了 provider 解耦。

## 5. 优先级二：补一个真正可用的 embedding 方案

由于当前中转站不支持 embeddings，建议两条路线并行保留：

### 路线 A：本地 embedding

优点是稳定、无成本、适合公开演示。

可选实现：

- `sentence-transformers`
- `BAAI/bge-small-zh-v1.5`
- `BAAI/bge-m3`

新增 provider：

```text
LocalSentenceTransformerEmbeddingProvider
```

环境变量：

```env
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
EMBEDDING_DIMENSION=512
```

这条路线最适合简历和录屏，因为不依赖付费 API，也不会因为 key 权限影响演示。

### 路线 B：真实 OpenAI-compatible embedding

保留已有 `OpenAICompatibleEmbeddingProvider`，但要求 provider 必须真实支持：

```text
POST /v1/embeddings
model=text-embedding-3-small
```

录屏标题应写成：

```text
真实 Chroma + OpenAI-compatible embedding
```

不要把只支持 Chat/Responses 的 key 说成 embedding key。

## 6. 优先级三：修复 Chroma 持久化能力

当前 Chroma 的风险是：向量写入 Chroma 后，本进程内 `self.chunks` 有数据；但重启服务后，`self.chunks` 为空，检索不到历史数据。

建议优化：

- upsert 时把 chunk 全量 metadata 写入 Chroma，包括 `document_id`、`file_name`、`chunk_index`、`page_number`、`heading_path`、`text`。
- `ChromaVectorStore.__init__` 启动时调用 collection get，恢复 `self.chunks`。
- document registry 也要持久化，可以先用 SQLite。
- 删除文档时同时删除 registry 和 Chroma collection 中对应 chunks。

新增文件建议：

```text
backend/app/services/document_registry.py
backend/app/services/index_state.py
```

验收标准：

- 上传文档后重启后端，文档列表仍存在。
- 不重新上传也能问答。
- 删除文档后重启，文档不会复活。

这是非常适合写进简历的工程亮点：不是“接了 Chroma”，而是“实现可恢复的向量索引与文档元数据一致性”。

## 7. 优先级四：检索质量升级

建议把检索链路升级为：

```text
用户问题
  ↓
Query Normalize
  ↓
LLM Query Rewrite / Multi-query
  ↓
BM25 召回 + 向量召回
  ↓
去重 + MMR 多样性控制
  ↓
Rerank
  ↓
证据压缩
  ↓
答案生成
```

具体功能：

- Query Rewrite：用当前 `gpt-5.5` 把口语问题改写成 2-3 个检索查询。
- Multi-query Retrieval：多个查询分别召回，再合并去重。
- MMR：避免 top chunks 全来自同一段相似内容。
- Dynamic TopK：短问题小 TopK，复杂问题扩大 candidate_k。
- Score Breakdown：前端继续展示 bm25、vector、rerank、final score。
- No-answer Gate：最高分低于阈值时不进入答案生成。

面试讲法：

“我不是简单把 top_k 塞给大模型，而是设计了多阶段召回与拒答阈值。这样可以减少幻觉，并且能通过 trace 定位问题出在 query、召回、排序还是生成阶段。”

## 8. 优先级五：图片与多模态能力落地

当前图片只是 placeholder，不建议继续在简历里强调“多模态理解”。要升级可以分两步：

第一步：OCR 文字提取。

- 接入 `pytesseract` 或 PaddleOCR。
- 图片上传后生成 OCR 文本页。
- metadata 标记 `parser=ocr`、`ocr_confidence`。

第二步：VLM 图片理解。

- 使用当前 Responses/Chat provider，如果服务支持图片输入，再做 image caption。
- 图片会生成两类文本：
  - OCR 原文
  - VLM 语义描述

前端展示：

- 原图预览。
- OCR 文本。
- 图片摘要。
- 引用证据中能显示图片来源。

简历表述应谨慎：

- 没做 OCR 前：写“预留 OCR/VLM 适配层”。
- 做了 OCR 后：写“支持图片 OCR 文本入库”。
- 做了 VLM 后：再写“支持图片语义理解与跨模态检索”。

## 9. 优先级六：前端从 Demo 页升级为工作台

建议前端改成三栏结构：

```text
左侧：知识库 / 文档 / 标签
中间：问答会话
右侧：引用证据 / Retrieval Trace / 调试面板
```

核心页面：

- 知识库列表：不同项目资料分开管理。
- 文档管理：上传、删除、重建索引、查看状态。
- 问答页面：会话式交互，支持历史记录。
- 引用详情：点击引用定位到 chunk、页码、原文。
- Trace 面板：展示 query rewrite、召回数量、各阶段得分。
- Eval 面板：内置测试集，查看命中率和失败案例。

用户体验细节：

- 上传后显示索引状态：解析中、embedding 中、入库完成、失败。
- 问答时分阶段 loading：检索中、重排中、生成中。
- 文档为空时不能直接问答，要提示上传资料。
- 证据不足时展示“为什么无法回答”。

## 10. 优先级七：评测与可观测性

目前 eval 是关键词命中，适合 MVP，但不足以证明系统质量。

建议新增：

- `Recall@K`
- `MRR`
- `Citation Precision`
- `No-answer Accuracy`
- `Answer Groundedness`
- 平均检索耗时
- 平均生成耗时

新增目录：

```text
eval/
  cases.jsonl
  expected_sources.json
  reports/
```

新增脚本：

```text
scripts/run_retrieval_eval.py
scripts/run_answer_eval.py
```

前端可以做一个轻量评测页：

- 一键运行测试集。
- 展示通过率。
- 展示失败问题和 top chunks。
- 对比不同配置：mock/local/openai embedding、keyword rerank/none。

这会让项目从“能跑”变成“能证明自己变好”。

## 11. 优先级八：工程化和部署

建议补齐：

- Dockerfile
- docker-compose.yml
- 后端 `.env.example` 分组说明
- 前端环境变量 `VITE_API_BASE_URL`
- API 错误码规范
- 文件大小限制
- 上传文件白名单
- 日志脱敏
- key rotation 说明
- CI：pytest + frontend build

特别注意：

- `.env` 已经在 `.gitignore`，但真实 key 曾经出现在对话里，正式使用前建议更换。
- README 里不要写真实 key，不要写真实中转站 token。
- 录屏时不要打开 `.env`。

## 12. 两周开发排期

### 第 1-2 天：Answer Generator

- 新增 `answer_generator.py`。
- 接入当前 Responses key。
- 支持 template/responses 两种模式。
- 前端展示“生成模型”和“回答是否基于证据”。

### 第 3-4 天：Local Embedding + Chroma 恢复

- 新增 local embedding provider。
- 修复 Chroma 重启后无法恢复 chunks 的问题。
- 增加上传后重启仍可检索的测试。

### 第 5-6 天：知识库与文档状态

- 增加 SQLite document registry。
- 支持文档状态：pending/indexing/indexed/failed。
- 前端文档列表展示状态、重建索引按钮。

### 第 7-8 天：检索增强

- Query Rewrite。
- Multi-query Retrieval。
- MMR 去冗余。
- No-answer 阈值。

### 第 9-10 天：前端工作台

- 三栏布局。
- 会话历史。
- 引用详情。
- Trace 调试面板。

### 第 11-12 天：评测系统

- 增加 eval cases。
- 输出 Recall@K、MRR、Citation Precision。
- 前端展示评测报告。

### 第 13-14 天：作品集收尾

- README 重写为产品型项目介绍。
- 增加架构图。
- 录制两个视频：
  - 本地 embedding + Chroma 稳定演示。
  - Responses 模型基于证据生成回答演示。
- 更新简历项目描述。

## 13. 简历包装方向

推荐项目名称：

```text
个人知识库 RAG 问答系统
```

推荐一句话：

```text
基于 Vue 3 + FastAPI 构建个人知识库 RAG 系统，实现文档解析、混合召回、向量索引、Rerank、证据约束回答和检索质量评测。
```

推荐亮点：

- 设计 RAG 模块化架构，抽象 embedding provider、vector store、reranker 和 answer generator，支持本地模型与 OpenAI-compatible provider 切换。
- 实现 BM25 + 向量召回 + Rerank 的多阶段检索链路，并通过 retrieval trace 暴露 query tokens、candidate_k、各阶段得分，提升可调试性。
- 基于 Chroma 构建可持久化向量索引，维护文档 metadata 与 chunk 引用关系，支持上传、删除、重建索引和引用溯源。
- 接入 Responses 模型进行证据约束回答，强制答案基于引用片段生成，证据不足时拒答，降低幻觉风险。
- 构建轻量评测脚本，使用 Recall@K、MRR、引用准确率评估检索质量，并支持不同检索配置对比。

避免表述：

- 不要说“已经实现完整多模态理解”，除非 OCR/VLM 真正接入。
- 不要说“已接 OpenAI embedding”，除非 key 能真实调用 `/embeddings`。
- 不要说“企业级 RAG 平台”，这个项目更适合定位为个人知识库和 RAG 工程实践。
- 不要只讲“调用大模型 API”，要讲文档解析、索引、召回、重排、证据约束和评测。

## 14. 最小可交付版本

如果只做最划算的一版，建议完成这 5 件事：

1. 当前 key 接入 `AnswerGenerator`，实现真实证据约束回答。
2. 本地 embedding provider + Chroma 持久化恢复。
3. 文档状态和重建索引。
4. Query Rewrite + Rerank + No-answer Gate。
5. 前端三栏工作台和 Trace 面板。

这 5 件做完，项目就可以作为应届生简历中的主项目，定位为：

```text
AI 应用开发 / RAG 工程 / Vue 前端工程化
```

面试时可以讲的核心故事是：

“我一开始也以为 RAG 是上传文件然后调模型，但真正做下来发现关键在检索质量和证据可信度。所以我把项目拆成解析、切分、召回、重排、生成和评测几个阶段。每个阶段都能在前端 trace 里看到指标，出了问题可以定位是召回不到、排序不准，还是生成阶段没有遵守证据。”

