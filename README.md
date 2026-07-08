# 个人多模态 RAG 知识库问答系统

面向个人和小团队知识管理的 RAG 问答系统，支持 PDF、Markdown、文本和图片资料上传，提供文档解析、chunk 切分、混合检索、引用回答、retrieval trace、可信度审计和轻量评测。

项目重点不是做一个普通聊天框，而是把 RAG 链路里的关键工程问题拆开：文档解析、切分策略、BM25 召回、向量召回、混合排序、引用来源、拒答策略和检索质量调试。

## 快速运行

```bash
npm install
cp .env.example .env
npm run dev
```

另开一个终端导入脱敏演示资料：

```bash
npm run demo:bootstrap
```

打开 `http://127.0.0.1:5173`，选择样例资料提问，查看答案、引用片段、score、retrieval trace、fallback 和可信度审计。默认配置使用 mock/hash embedding 与 template answer，无需真实 API Key。

快速验收：

```bash
npm run build
npm run test
npm run test:demo
```

## 演示资料

演示资料位于：

```text
samples/demo-documents/
```

推荐体验路径：

```text
导入资料 -> 提问 -> 查看引用上下文 -> 查看可信度审计 -> 点击负反馈生成评测草稿 -> 运行评测 -> 保存知识卡片
```

推荐提问：

```text
这个 RAG 系统的核心工程亮点是什么？
这个系统如何通过引用和拒答机制降低幻觉？
这份资料有没有提到 Kubernetes 部署？
AIGC 工作流资料里提到了哪些工程能力？
```

## 功能

- 上传 PDF、Markdown、文本、图片文件。
- 支持 URL 导入网页资料，并进入同一套解析、切分、索引和质量评分流程。
- 上传文件按 SHA-256 去重，避免重复资料生成重复 chunk。
- 支持文档索引状态和重建索引，便于 OCR 或 embedding 配置变化后重新入库。
- 自动解析文本并按 chunk size + overlap 切分。
- 图片文件接入 OCR adapter，安装 tesseract + pytesseract 后可提取图片文字。
- 建立 BM25 关键词索引。
- 通过 `BaseEmbeddingProvider` / `MockEmbeddingProvider` 建立轻量 hash embedding 向量索引。
- 支持 OpenAI-compatible embedding provider。
- 通过 `BaseVectorStore` 隔离 Memory / Chroma / pgvector 三种向量存储。
- 使用混合检索排序：`0.62 * normalized BM25 + 0.38 * vector similarity`。
- 支持 Query Rewrite、Multi-query Retrieval、MMR 去冗余和 No-answer Gate。
- 支持本地 keyword rerank，前端展示 rerank_score。
- 预留 cross-encoder reranker，可通过 `RERANKER=cross-encoder` 接入 BGE reranker。
- 支持 template / Responses 两种答案生成器。
- 问答结果展示引用来源、页码或片段编号、score、bm25_score、vector_score。
- 输出 retrieval trace，方便调试召回链路。
- 输出 query intent、document boost、parent-child context 和检索/生成耗时。
- 支持答案可信度分级、引用覆盖率、unsupported claims 和引用上下文。
- 支持答案改写为项目说明、要点列表、学习笔记和 FAQ。
- 支持知识卡片沉淀和资料缺口分析。
- 支持用户反馈生成 eval draft，并在前端运行评测草稿。
- 支持系统指标面板，统计质量分、平均置信度、拒答、fallback 和负反馈。
- 提供轻量评测接口和脚本，支持 Recall@K、MRR、引用准确率。
- 提供检索 profile 对比脚本，可比较 BM25-only、Vector-only、Hybrid、Hybrid+Rerank。

## 搜索与调试

工作台支持两种运行模式：

- `问答`：检索证据后进入证据约束回答生成。
- `搜索`：只返回证据片段和完整 retrieval trace，便于调试召回质量。

检索策略支持在前端直接调整：

- 搜索模式：`hybrid`、`keyword`、`semantic`
- 检索 profile：`balanced`、`precision`、`recall`
- 文档范围：全部文档或指定文档集合
- Top K、candidate K、BM25/Vector 权重、MMR lambda、最低分阈值
- Query Rewrite 开关

后端会在 trace 中返回每次检索的阶段数据：`raw_candidates`、`deduped_candidates`、`mmr_selected`、`returned`、`matched_terms`、`score_breakdown`、`fallbacks`、`rewrite_status`、`vector_status` 和 `rerank_status`。

## 普通模式与专家模式

- 普通模式：默认入口，隐藏 BM25、Vector、MMR、candidate_k 等工程参数，只保留上传、选择资料、提问、查看答案和引用。
- 专家模式：保留完整检索参数、策略对比、Trace、Fallback 和文档调试能力，适合检索调参和问题定位。

当系统发现证据不足、范围过窄或检索链路降级时，会返回 diagnostics，并在前端展示可执行修复动作，例如切换全部资料、降低严格度、扩大搜索范围、切换混合检索、查看检索过程或重建索引。

## 技术栈

- 前端：Vue 3、TypeScript、Vite
- 后端：FastAPI、Python、PyMuPDF、pytest
- 检索：BM25、Hash Embedding、OpenAI-compatible Embedding、Local Sentence Transformers、Cross-Encoder Rerank
- 存储：Memory、Chroma、pgvector
- 生成：Template Answer、OpenAI Responses-compatible adapter

## 目录结构

```text
personal-multimodal-rag/
  backend/
    app/
      api/routes.py
      core/store.py
      models/
      services/
    tests/
  frontend/
    src/
  samples/demo-documents/
  scripts/bootstrap_demo_documents.py
  scripts/run_eval.py
  docs/
```

## 环境变量

复制 `.env.example`：

```bash
cp .env.example .env
```

默认不需要真实模型 Key。需要接入真实模型时，再按 `.env.example` 配置 OpenAI-compatible embedding、answer provider、Chroma 或 pgvector。

## 已知边界

- 默认 hash/mock embedding 只用于本地演示，不代表生产向量质量。
- 图片 OCR 依赖本机 tesseract，可选启用。
- 大规模索引、权限隔离、多租户和严格评测集仍需进一步建设。
- 真实 LLM、Chroma、pgvector 是增强能力，不是默认演示依赖。

更多说明见：

- [架构说明](docs/architecture.md)
- [演示脚本](docs/demo-script.md)
- [已知边界](docs/known-limitations.md)
- [项目复盘](docs/project-retrospective.md)
