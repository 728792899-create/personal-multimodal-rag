# 简历与面试表述

## 简历项目名称

个人多模态 RAG 知识库问答系统

## 技术栈

Vue 3 / TypeScript / FastAPI / Python / BM25 / Hybrid Search / Chroma / SQLite / Responses API / Rerank / RAG Evaluation

## 一句话定位

面向个人知识管理场景的多模态 RAG 问答系统，支持 PDF、Markdown、文本和图片资料上传，完成文档解析、chunk 切分、混合检索、引用回答和轻量评测。

## 可写进简历的描述

- 设计并实现个人知识库 RAG 问答系统，支持 PDF、Markdown、文本和图片资料上传，完成文档解析、OCR 状态记录、chunk 切分、索引构建、混合检索、引用来源展示和证据约束回答。
- 实现 BM25 与向量检索的混合召回策略，加入 Query Rewrite、MMR 去冗余、Keyword Rerank 和 No-answer Gate，并在前端展示 score、bm25_score、vector_score、rerank_score 和 retrieval trace。
- 抽象 embedding provider、vector store、query rewriter、answer generator 等模块，支持 mock/local/OpenAI-compatible embedding、Memory/Chroma/pgvector 和 template/Responses 答案生成切换。
- 基于 Chroma + SQLite 实现向量索引与文档 metadata 持久化，支持服务重启后恢复 chunk 映射，避免知识库索引只存在于内存。
- 实现问答历史、文档详情、原文预览、chunk 列表和引用详情闭环，让系统从接口 demo 升级为可长期使用的知识库工作台。
- 实现文件 SHA-256 去重、索引状态记录和重建索引接口，解决重复上传、配置变化后重建索引等真实使用问题。
- 构建 30 条轻量评测集，输出 Recall@5、MRR、Citation Precision，用于对比不同检索配置的召回质量。
- 增加 Docker Compose 与 GitHub Actions CI，覆盖后端测试、前端构建和检索评测。

## 面试可讲故事

背景问题：AI 问答系统不是只调用模型接口，核心难点在于怎么把知识准确地检索出来，并让答案可追溯。

技术方案：我把系统拆成文档解析、chunk 切分、BM25 召回、向量召回、查询改写、MMR、Rerank、证据约束生成和评测几个模块。前端不仅展示答案，还展示引用片段、检索分数、query rewrite 和生成模型，方便观察召回质量。

踩坑与优化：如果只用关键词检索，语义相近的问题容易搜不到；如果只用向量检索，专业名词和精确字段容易误召回。所以我做了混合检索，并保留 retrieval trace 用于排查。另一个坑是 Chat/Responses key 不一定支持 embeddings，所以我把生成层和 embedding 层拆开，避免把所有模型能力耦合到一个 provider。

后续升级：安装本地 BGE embedding / cross-encoder reranker，接入 VLM 图片语义理解，使用 RAGAS 做自动化评测，并增加多知识库、标签、权限和会话历史。
