# 个人多模态 RAG 知识库问答系统

面向个人知识管理场景的 RAG 问答系统，支持 PDF、Markdown、文本和图片资料上传，完成文档解析、chunk 切分、混合检索、引用回答和轻量评测。

这个项目的目标不是做一个“只会调接口的聊天框”，而是把 RAG 链路中的关键工程问题拆出来：文档解析、切分策略、BM25 召回、向量式召回、混合排序、引用来源和检索质量调试。

## 面试官 10 分钟运行路径

```bash
npm install
cp .env.example .env
npm run dev
```

另开一个终端导入脱敏演示资料：

```bash
npm run demo:bootstrap
```

打开 `http://127.0.0.1:5173`，选择样例资料提问，重点查看答案、引用片段、score、retrieval trace、fallback 和可信度审计。默认配置使用 mock/hash embedding 与 template answer，无需真实 API Key。

快速验收：

```bash
npm run build
npm run test
npm run test:demo
```

## 作品集演示入口

如果你是面试官，建议从这里看项目：

- [作品集一页说明](docs/portfolio-onepager.md)
- [面试演示脚本](docs/demo-script.md)
- [面试讲述手册](docs/interview-playbook.md)
- [项目复盘](docs/project-retrospective.md)
- [架构说明](docs/architecture.md)

一键导入演示资料：

```bash
npm run dev
python3 scripts/bootstrap_portfolio_demo.py
```

演示资料位于：

```text
samples/portfolio-demo/
```

推荐演示路径：

```text
导入资料 -> 提问 -> 查看引用上下文 -> 查看可信度审计 -> 点击负反馈生成评测草稿 -> 运行评测 -> 改写成简历 bullet -> 保存知识卡片
```

推荐提问：

```text
这个 RAG 项目最适合写进简历的技术亮点是什么？
如果面试官追问引用可信度，这个系统怎么降低幻觉？
这份资料有没有提到 Kubernetes 部署？
杭州 AIGC 应用开发岗位更看重哪些能力？
```

## 功能

- 上传 PDF、Markdown、文本、图片文件
- 支持 URL 导入网页资料，并进入同一套解析、切分、索引和质量评分流程
- 上传文件按 SHA-256 去重，避免重复资料生成重复 chunk
- 支持文档索引状态和重建索引，便于 OCR/embedding 配置变化后重新入库
- 支持文档质量评分、自动摘要、建议问题和索引生命周期
- 自动解析文本并按 chunk size + overlap 切分
- 图片文件接入 OCR adapter，安装 tesseract + pytesseract 后可提取图片文字；缺失运行时时会在 metadata 中标记 OCR 状态
- 建立 BM25 关键词索引
- 通过 `BaseEmbeddingProvider` / `MockEmbeddingProvider` 建立轻量 hash embedding 向量索引
- 支持 OpenAI-compatible 真实 embedding provider
- 通过 `BaseVectorStore` 隔离 Memory / Chroma / pgvector 三种向量存储
- 支持 Chroma 启动恢复 chunk metadata，避免重启后索引丢失
- 使用混合检索排序：`0.62 * normalized BM25 + 0.38 * vector similarity`
- 支持 Query Rewrite、Multi-query Retrieval、MMR 去冗余和 No-answer Gate
- 支持本地 keyword rerank，前端展示 rerank_score
- 预留 cross-encoder reranker，可通过 `RERANKER=cross-encoder` 接入 BGE reranker
- 支持 template / Responses 两种答案生成器，可用 Chat/Responses key 做证据约束回答
- 支持问答历史持久化，可回看问题、答案、引用和 trace
- 支持文档详情接口，回看原文、页信息、OCR 状态和 chunk 列表
- 问答结果展示引用来源、页码/片段编号、score、bm25_score、vector_score
- 输出 retrieval trace，方便调试召回链路
- 输出 query intent、document boost、parent-child context 和检索/生成耗时
- 支持答案可信度分级、引用覆盖率、unsupported claims 和引用上下文
- 支持答案改写为简历 bullet、面试回答、学习笔记、FAQ
- 支持知识卡片沉淀和资料缺口分析
- 支持用户反馈生成 eval draft，并在前端运行评测草稿
- 支持系统指标面板，统计质量分、平均置信度、拒答、fallback 和负反馈
- 提供轻量评测接口和脚本，支持 Recall@K、MRR、引用准确率
- 提供检索 profile 对比脚本，可比较 BM25-only、Vector-only、Hybrid、Hybrid+Rerank
- OCR/VLM 与真实 LLM 预留适配层，本地无 API Key 也能跑通核心流程

## 搜索与交互升级

当前工作台支持两种运行模式：

- `问答`：检索证据后进入证据约束回答生成。
- `搜索`：只返回证据片段和完整 retrieval trace，便于调试召回质量。

检索策略支持在前端直接调整：

- 搜索模式：`hybrid`、`keyword`、`semantic`
- 检索 profile：`balanced`、`precision`、`recall`
- 文档范围：全部文档或指定文档集合
- Top K、candidate K、BM25/Vector 权重、MMR lambda、最低分阈值
- Query Rewrite 开关

后端会在 trace 中返回每次检索的阶段数据：

- `raw_candidates`
- `deduped_candidates`
- `mmr_selected`
- `returned`
- `matched_terms`
- `score_breakdown`
- `fallbacks`
- `rewrite_status`
- `vector_status`
- `rerank_status`

这部分适合在面试中讲成“可解释 RAG 检索调试台”：不是只把 top_k 结果塞给模型，而是把召回、去重、多样性、重排、拒答阈值和引用证据都暴露出来，能定位问题发生在 query、召回、排序还是生成阶段。

已实现的兜底机制：

- Query Rewrite 失败时退回原始问题
- 向量检索失败时退回 BM25 关键词检索
- Rerank 失败时退回基础排序
- Answer Provider 失败时退回模板回答
- Reranker / Answer / Query Rewrite 初始化失败时不阻断后端启动
- Chroma embedding 维度不匹配时返回可读的修复建议
- 搜索和问答结果返回 diagnostics，提示阈值过高、文档范围过窄、证据不足等问题

已实现的策略对比接口：

```text
POST /api/search/compare
```

该接口会对同一个问题同时运行：

- 关键词 BM25
- 语义向量
- 混合检索
- 混合检索 + Rerank

前端工作台提供“策略对比”按钮，适合录屏展示不同检索策略的差异。

## 普通模式与专家模式

工作台已拆分为两种使用层级：

- 普通模式：默认入口，隐藏 BM25、Vector、MMR、candidate_k 等工程参数，只保留上传、选择资料、提问、查看答案和引用。
- 专家模式：保留完整检索参数、策略对比、Trace、Fallback 和文档调试能力，适合面试展示和检索调参。

当系统发现证据不足、范围过窄或检索链路降级时，会返回 diagnostics，并在前端展示可执行修复动作，例如：

- 切换全部资料再试
- 降低严格度再试
- 扩大搜索范围再试
- 切换混合检索
- 查看检索过程
- 重建全部索引

这部分用于把工作台从“工程调试台”推进到“普通用户可用、问题可自修复、专家可调试”的产品形态。

## 技术栈

前端：

- Vue 3
- TypeScript
- Vite

后端：

- FastAPI
- Python
- PyMuPDF
- BM25
- Hash Embedding
- OpenAI-compatible Embedding
- Local Sentence Transformers Embedding
- Cross-Encoder Rerank
- Hybrid Search
- Chroma / pgvector
- Responses API
- pytest

## 目录结构

```text
personal-multimodal-rag/
  backend/
    app/
      api/routes.py
      core/store.py
      models/domain.py
      models/schemas.py
      services/document_processor.py
      services/answer_generator.py
      services/document_registry.py
      services/embeddings.py
      services/ocr.py
      services/query_rewriter.py
      services/reranker.py
      services/retriever.py
      services/responses_client.py
      services/rag_engine.py
      services/vectorstore.py
    tests/
      test_api.py
      test_document_processor.py
      test_retriever.py
  scripts/
    compare_retrieval_profiles.py
    demo_chroma_openai.py
    demo_responses_rag.py
    ingest_file.py
    record_chroma_openai_demo.sh
    run_retrieval_eval.py
    run_eval.py
  eval/cases.jsonl
  frontend/
    src/App.vue
    src/api.ts
    src/styles.css
  docs/resume-story.md
  samples/rag-notes.md
```

## 启动

安装前端依赖：

```bash
npm install
npm --prefix frontend install
```

安装后端依赖：

```bash
python3 -m pip install -r backend/requirements.txt
```

如果要启用 OpenAI-compatible embedding、Chroma 或 pgvector，再安装可选依赖：

```bash
python3 -m pip install -r backend/requirements-optional.txt
```

同时启动前后端：

```bash
npm run dev
```

也可以分开启动：

```bash
cd backend
python3 -m uvicorn app.main:app --reload --port 8010
```

```bash
cd frontend
npm run dev
```

前端地址：

```text
http://localhost:5173
```

后端健康检查：

```text
http://localhost:8010/health
```

## 试用方式

1. 打开前端页面。
2. 上传 `samples/rag-notes.md`。
3. 输入问题：`如何优化 RAG 的召回质量？`
4. 查看回答、引用片段、BM25 分数、向量分数和 retrieval trace。

## 当前中转站 Key 演示模式

如果你的 key 支持 `/responses`，但不支持 `/embeddings`，不要把它配置为 embedding provider。推荐配置为：

```env
EMBEDDING_PROVIDER=mock
EMBEDDING_MODEL=hash-mock
EMBEDDING_DIMENSION=256

VECTOR_STORE=chroma
CHROMA_PATH=./data/chroma-apikeyfun-demo
CHROMA_COLLECTION=personal_knowledge_apikeyfun_demo

ANSWER_PROVIDER=responses
ANSWER_MODEL=gpt-5.5
ANSWER_BASE_URL=https://api.apikey.fun
ANSWER_API_KEY=你的中转站 Key

QUERY_REWRITE_PROVIDER=responses
QUERY_REWRITE_MODEL=gpt-5.5
QUERY_REWRITE_BASE_URL=https://api.apikey.fun
QUERY_REWRITE_API_KEY=你的中转站 Key
```

运行：

```bash
python3 scripts/demo_responses_rag.py
```

这个模式的含义是：本地 embedding + Chroma 完成检索，Responses 模型完成查询改写和证据约束回答。

## 本地 BGE + Chroma 演示模式

如果当前 API Key 只能用于 Responses/Chat，推荐把 embedding 放到本地模型完成。这样录屏时仍然可以展示真实语义向量检索、Chroma 持久化、Query Rewrite 和证据约束回答。

安装本地 embedding 依赖：

```bash
python3 -m pip install -r backend/requirements-bge.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

预热 BGE 模型：

```bash
python3 scripts/prewarm_local_models.py \
  --embedding-model BAAI/bge-small-zh-v1.5 \
  --hf-endpoint https://hf-mirror.com
```

`.env` 推荐配置：

```env
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
EMBEDDING_DIMENSION=512
HF_ENDPOINT=https://hf-mirror.com

VECTOR_STORE=chroma
CHROMA_PATH=./data/chroma-bge-demo
CHROMA_COLLECTION=personal_knowledge_bge_demo
RERANKER=keyword

ANSWER_PROVIDER=responses
ANSWER_MODEL=gpt-5.5
ANSWER_BASE_URL=https://api.apikey.fun
ANSWER_API_KEY=你的中转站 Key

QUERY_REWRITE_PROVIDER=responses
QUERY_REWRITE_MODEL=gpt-5.5
QUERY_REWRITE_BASE_URL=https://api.apikey.fun
QUERY_REWRITE_API_KEY=你的中转站 Key
```

启动后端并重建索引：

```bash
cd backend
python3 -m uvicorn app.main:app --reload --port 8010
```

```bash
curl -X POST http://127.0.0.1:8010/api/documents/rebuild-all
```

切换 embedding 维度时，Chroma collection 不能混用旧向量。例如 mock embedding 默认 256 维，`bge-small-zh-v1.5` 是 512 维，OpenAI `text-embedding-3-small` 通常是 1536 维。每种 embedding 推荐使用独立的 `CHROMA_PATH` 或 `CHROMA_COLLECTION`。

## 真实 Chroma + OpenAI 录屏

先安装真实 provider 依赖：

```bash
python3 -m pip install -r backend/requirements-optional.txt
```

如果默认 PyPI 下载 Chroma 很慢，可以临时使用镜像源：

```bash
python3 -m pip install -r backend/requirements-optional.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

在项目根目录新建 `.env`，不要提交到 GitHub：

```env
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSION=1536
OPENAI_API_KEY=你的真实 OpenAI API Key
OPENAI_BASE_URL=

VECTOR_STORE=chroma
CHROMA_PATH=./data/chroma-openai-demo
CHROMA_COLLECTION=personal_knowledge_demo
RERANKER=keyword
INITIAL_RETRIEVAL_K=24
```

先用 CLI 验证真实链路：

```bash
python3 scripts/demo_chroma_openai.py
```

通过后生成 macOS 录屏：

```bash
./scripts/record_chroma_openai_demo.sh
```

录屏文件会保存到：

```text
demo-recordings/
```

录屏脚本会启动前后端、上传 `samples/rag-notes.md`、打开前端并自动提问。页面会展示 `Embedding: openai / text-embedding-3-small`、`Vector Store: chroma`、`bm25_score`、`vector_score` 和 `rerank_score`，用于证明不是 mock 模式。

## Provider 配置

默认配置不需要 API Key：

```env
EMBEDDING_PROVIDER=mock
VECTOR_STORE=memory
RERANKER=keyword
```

启用 OpenAI-compatible embedding：

```env
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSION=1536
OPENAI_API_KEY=你的 API Key
OPENAI_BASE_URL=
```

启用本地 sentence-transformers embedding：

```env
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
EMBEDDING_DIMENSION=512
VECTOR_STORE=chroma
CHROMA_PATH=./data/chroma-bge-demo
CHROMA_COLLECTION=personal_knowledge_bge_demo
```

启用 cross-encoder rerank：

```env
RERANKER=cross-encoder
RERANKER_MODEL=BAAI/bge-reranker-base
```

注意：本地 BGE embedding / reranker 会下载模型和 PyTorch 相关依赖，首次启动较慢。作品集演示前建议提前完成模型下载。

启用 Chroma：

```env
VECTOR_STORE=chroma
CHROMA_PATH=./data/chroma
CHROMA_COLLECTION=personal_knowledge
```

启用 pgvector：

```env
VECTOR_STORE=pgvector
PGVECTOR_DSN=postgresql://postgres:postgres@localhost:5432/personal_rag
PGVECTOR_TABLE=rag_chunks
EMBEDDING_DIMENSION=1536
```

pgvector 模式需要本地 PostgreSQL 已安装 `vector` 扩展；应用启动时会尝试执行 `CREATE EXTENSION IF NOT EXISTS vector`。

## API

```text
GET  /health
GET  /api/documents
GET  /api/documents/{document_id}
POST /api/documents
POST /api/documents/{document_id}/rebuild
GET  /api/search?q=检索问题&top_k=5
POST /api/ask
POST /api/evaluate
DELETE /api/documents/{document_id}
GET  /api/history
DELETE /api/history
```

## 测试

```bash
cd backend
python3 -m pytest
```

测试覆盖：

- Markdown 解析和 heading metadata
- 空文档异常
- 图片 OCR 运行时状态记录
- mock embedding 稳定性
- 混合检索和删除文档
- Chroma 重启恢复 chunk metadata
- 上传、文档详情、问答历史、删除 API 闭环

## 评测

```bash
python3 scripts/run_eval.py
```

评测脚本会加载 `samples/rag-notes.md`，运行一组基础问题，并输出关键词命中和 top source。

运行检索指标评测：

```bash
python3 scripts/run_retrieval_eval.py
```

运行检索策略对比：

```bash
python3 scripts/compare_retrieval_profiles.py
```

当前 `eval/cases.jsonl` 包含 30 条样例，覆盖可回答问题和不可回答问题。输出指标：

- Recall@5
- MRR
- Citation Precision
- 每条 case 的 top sources 和 trace

## Docker / CI

本地 Docker 启动：

```bash
docker compose up --build
```

项目已包含 GitHub Actions CI：

```text
.github/workflows/ci.yml
```

CI 会执行后端 pytest、前端 build 和检索评测脚本。

## OCR

图片 OCR 是可选运行时能力。安装：

```bash
brew install tesseract
python3 -m pip install pytesseract
```

安装前上传图片也不会失败，系统会记录图片 metadata，并在文档详情中展示 `ocr_status=unavailable`。安装后同一条解析链路会自动提取图片文本并进入索引。

## 规范对齐

本项目参考 `个人多模态 RAG 知识库问答系统 - Codex 开发文档`，当前已对齐：

- 本地优先，MVP 无需 API Key。
- Document / Chunk 保留 metadata、页码和 heading_path。
- Embedding provider 和 vector store 通过接口隔离。
- 支持真实 embedding provider、Chroma、pgvector 和 rerank 阶段。
- 支持 Responses answer generator 与 query rewrite，将 Chat/Responses key 放在生成层而不是 embedding 层。
- 支持 Chroma chunk metadata 恢复和 SQLite 文档注册表。
- 支持问答历史、文档详情、OCR 状态和引用详情闭环。
- 支持 SHA-256 文件去重、索引状态和重建索引。
- 支持 Docker Compose 和 GitHub Actions CI。
- 回答必须基于检索证据，无证据时明确无法确定。
- 提供 pytest、Chroma 持久化测试、OCR fallback 测试、基础 eval 和 30 条检索指标评测脚本。

## 后续升级

- 接入 Milvus
- 增加 LLM reranker 或 cross-encoder reranker
- 接入 OCR / VLM 解析图片内容
- 使用 RAGAS 做系统化评测
- 增加多知识库、标签、权限和会话历史
