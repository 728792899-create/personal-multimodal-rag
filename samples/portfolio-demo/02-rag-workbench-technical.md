# 个人多模态 RAG 知识库工作台技术说明

## 项目定位

该项目是面向个人知识管理和求职准备场景的 RAG 工作台，目标是解决普通 RAG Demo 中检索不可解释、引用不可信、失败不可追踪和反馈无法沉淀的问题。

## 核心模块

### 文档接入

支持 PDF、Markdown、文本、图片和 URL 导入。系统会记录文档来源、解析器、content hash、索引状态和质量评分。

### 混合检索

检索链路包含 BM25 关键词召回、向量召回、score fusion、MMR 去冗余、rerank 和 no-answer gate。

### 引用可信度

回答结果会展示 citations、confidence、引用覆盖率和 unsupported claims。点击引用可以查看当前 chunk 的上下文。

### 反馈评测

用户点击“不准确”后会生成 eval draft。专家模式可以运行评测草稿，用于比较不同检索策略。

### 知识沉淀

答案可以改写成简历 bullet、面试回答、学习笔记和 FAQ，也可以保存为知识卡片。

## 技术亮点

- Vue 3 + TypeScript 实现普通模式和专家模式。
- FastAPI 后端拆分 document processor、retriever、reranker、answer generator、citation audit。
- 支持 Memory、Chroma 和 pgvector 向量存储。
- 支持 mock、local、OpenAI-compatible embedding provider。
- 支持 query intent、document boost、parent-child context 和 performance trace。

## 面试可讲难点

最大难点不是生成答案，而是让答案可信。项目通过混合检索、拒答阈值、引用审计、上下文跳转和反馈评测降低幻觉风险。

