# 作品集一页说明

## 项目名称

个人多模态 RAG 知识库检索工作台

## 一句话定位

面向个人知识管理、项目复盘和求职准备场景的 RAG 工作台，重点解决普通 RAG Demo 中“检索不可解释、引用不可信、失败不可追踪、反馈不能沉淀”的问题。

## 适合投递方向

- AIGC 应用开发
- Vue 前端工程师
- Web 交互 / AI 工具产品开发
- RAG / LLM 应用工程实习或校招岗位

## 核心能力

- 多来源资料导入：PDF、Markdown、文本、图片、URL。
- 文档生命周期：上传、解析、切分、索引、质量评分、重建索引。
- 混合检索：BM25 + Vector + MMR + Rerank + No-answer Gate。
- 可解释 Trace：query rewrite、candidate_k、score breakdown、fallback、耗时指标。
- 引用可信度：证据等级、引用覆盖率、unsupported claims、引用上下文。
- 反馈评测闭环：负反馈生成 eval draft，支持前端运行评测草稿。
- 知识沉淀：答案改写、简历 bullet、面试回答、学习笔记、知识卡片。
- 系统指标：质量分、置信度、拒答数、fallback、负反馈、低质量文档。

## 面试官应该看到什么

1. 这不是“上传文件问答”的接口 Demo，而是一个具备产品闭环的 RAG 工作台。
2. 前端不只是展示答案，而是展示检索证据、引用上下文、质量诊断和修复动作。
3. 后端不是把 top_k 直接塞给模型，而是有混合召回、重排、拒答、评测和可观测。
4. 项目能解释失败：搜不到、证据弱、引用不支持、文档质量差，都能被定位。

## 简历表述

设计并实现个人多模态 RAG 知识库检索工作台，支持文件/URL 资料导入、文档解析与质量评分、BM25 + Vector 混合检索、MMR 去冗余、Rerank、引用审计、No-answer Gate、反馈评测和知识卡片沉淀；前端使用 Vue 3 + TypeScript 构建普通/专家双模式工作台，后端使用 FastAPI 抽象 embedding provider、vector store、reranker 与 answer generator，支持 Chroma/pgvector 和 Responses provider 切换。

## 最强展示点

- **可信回答**：展示证据等级、引用覆盖率和 unsupported claims。
- **可解释检索**：展示 BM25、Vector、Rerank、document boost、query intent 和耗时。
- **反馈飞轮**：不准确的回答会生成评测草稿，进入后续优化。
- **产品化工作台**：普通用户能问答，专家能调参、对比策略、看 trace。

## 不要这样说

- 不要说“完全多模态理解”，除非演示的是 OCR/VLM 已真实跑通的图片语义理解。
- 不要说“100% 防幻觉”，应说“通过引用审计、拒答阈值和反馈评测降低幻觉风险”。
- 不要说“接入 OpenAI 就完成 RAG”，应强调 provider 解耦和检索链路设计。
- 不要把中转站 Chat/Responses Key 说成 embedding key，embedding provider 要单独说明。

