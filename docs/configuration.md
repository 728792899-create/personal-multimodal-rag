# 配置指南

所有配置都来自环境变量。项目根目录与 `backend/.env` 会按顺序读取，已存在的系统环境变量不会被覆盖。不要提交真实 `.env`、API Key、数据库 DSN 或监控 DSN。

## 推荐起点

### 零 Key 离线演示

```env
APP_ENVIRONMENT=local
PROVIDER_FALLBACK_ALLOWED=1
EMBEDDING_PROVIDER=mock
EMBEDDING_MODEL=hash-mock
EMBEDDING_DIMENSION=256
VECTOR_STORE=memory
ANSWER_PROVIDER=template
QUERY_REWRITE_PROVIDER=none
```

特性：确定性、无网络成本、适合测试和作品集演示。限制：hash embedding 不代表生产语义质量，memory store 重启后需要从 SQLite registry 补建。

### 持久化本地工作台

```env
EMBEDDING_PROVIDER=mock
VECTOR_STORE=chroma
CHROMA_PATH=./data/chroma
CHROMA_COLLECTION=personal_knowledge
ANSWER_PROVIDER=template
```

需要安装可选依赖。切换 embedding 模型或维度时必须使用新 collection 并重建，不能把不同维度混写。

### OpenAI Responses 回答

```env
EMBEDDING_PROVIDER=mock
VECTOR_STORE=chroma
ANSWER_PROVIDER=openai_responses
ANSWER_MODEL=gpt-5.6
ANSWER_BASE_URL=https://api.openai.com/v1
ANSWER_API_KEY=<from-secret-manager>
QUERY_REWRITE_PROVIDER=none
```

建议先只替换 answer provider，确认 SSE、引用审计和失败语义，再单独迁移 embedding。真实 provider 会产生网络请求与费用；测试脚本会显式清空 Key 并强制离线模式。

### 真实 embedding

```env
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSION=1536
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=<from-secret-manager>
VECTOR_STORE=chroma
CHROMA_PATH=./data/chroma-openai
CHROMA_COLLECTION=personal_knowledge_openai_v1
```

更换模型、dimension、chunker 或清洗规则都应视为索引版本变化，使用新路径/表回填并评测后再切换。

## 配置矩阵

### Embedding

| 变量 | 默认/示例 | 说明 |
| --- | --- | --- |
| `EMBEDDING_PROVIDER` | `mock` | `mock`、`openai`、`sentence_transformers`（`huggingface` 别名）或 `ollama` |
| `EMBEDDING_MODEL` | `hash-mock` | provider 模型名 |
| `EMBEDDING_DIMENSION` | `256` | mock 默认 256；OpenAI 未设置时解析为 1536 |
| `OPENAI_API_KEY` | 空 | embedding provider 凭据 |
| `OPENAI_BASE_URL` | 空 | OpenAI-compatible API 根路径 |

### Vector store

| 变量 | 默认/示例 | 说明 |
| --- | --- | --- |
| `VECTOR_STORE` | `memory` | `memory`、`chroma` 或 `pgvector` |
| `CHROMA_PATH` | `./data/chroma` | 本地持久路径 |
| `CHROMA_COLLECTION` | `personal_knowledge` | collection 名 |
| `PGVECTOR_DSN` | 空/本地示例 | 应来自 secret manager |
| `PGVECTOR_TABLE` | `rag_chunks` | Beta adapter 表名 |

### Retrieval

| 变量 | 默认 | 说明 |
| --- | ---: | --- |
| `RERANKER` | `keyword` | 离线 keyword 或可选模型实现 |
| `RERANKER_MODEL` | `BAAI/bge-reranker-base` | 模型 reranker 名称 |
| `INITIAL_RETRIEVAL_K` | 24 | 初始候选池 |
| `BM25_WEIGHT` | 0.62 | Hybrid 词法权重 |
| `VECTOR_WEIGHT` | 0.38 | Hybrid 向量权重 |
| `NO_ANSWER_THRESHOLD` | 0.05 | 全局拒答门槛 |
| `GROUNDING_MIN_CONFIDENCE` | 0.15 | grounding 最低置信度 |
| `CITATION_OVERLAP_THRESHOLD` | 0.34 | 引用文本重合阈值 |
| `MMR_LAMBDA` | 0.78 | MMR 相关性权重 |
| `GRAPH_WEIGHT` | 0.25 | `hybrid_graph` 加权 RRF 的图谱权重 |
| `GRAPH_MAX_HOPS` | 2 | 图路径最大跳数，API 仍限制为 1–4 |

不要只因为一条演示问题失败就修改全局阈值。先把问题加入 eval draft，判断是召回、排序、切分、引用还是拒答门，再用固定集比较改动前后。

### Answer 与 query rewrite

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `ANSWER_PROVIDER` | `template` | `template`、`openai_responses`、`openai_compatible_chat` 或 `ollama` |
| `ANSWER_MODEL` | `gpt-5.6` | Responses-compatible 模型名，可由环境变量覆盖 |
| `ANSWER_BASE_URL` | 空 | 未设置时回退 `OPENAI_BASE_URL` |
| `ANSWER_API_KEY` | 空 | 未设置时回退 `OPENAI_API_KEY` |
| `ANSWER_TIMEOUT_SECONDS` | 45 | 生成网络超时 |
| `QUERY_REWRITE_PROVIDER` | `none` | `none` 或 `responses` |
| `QUERY_REWRITE_MODEL` | answer 模型 | 改写模型 |
| `QUERY_REWRITE_BASE_URL` | answer URL | 改写端点 |
| `QUERY_REWRITE_API_KEY` | answer Key | 改写凭据 |
| `QUERY_REWRITE_COUNT` | 2 | 候选改写数量 |

`responses`/`openai-responses` 旧别名继续可用。Responses 请求设置 `store:false`，流式消费官方 typed events；会话状态保存在本地 SQLite。

`APP_ENVIRONMENT=local/test/development` 默认允许显式模板 fallback；production 默认不允许。外部 Provider 未配置/不可用时返回脱敏 `503`，避免生产流量静默变成模板回答。`/api/providers/status` 只返回能力、配置完整性和模式，不返回 Key 或带凭据 URL。

### Multimodal enrichment

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `ENRICHMENT_PROVIDER` | `template` | `template`、`openai_responses`、`openai_compatible_vision` 或 `ollama_vision` |
| `ENRICHMENT_MODEL` | `gpt-5.6` | 视觉/结构化输出模型名；可覆盖 |
| `ENRICHMENT_BASE_URL` | 空 | Responses 未设置时使用官方端点；compatible provider 必填 |
| `ENRICHMENT_API_KEY` | 空 | 未设置时回退 `OPENAI_API_KEY`；永不返回浏览器 |
| `ENRICHMENT_PROMPT_VERSION` | `multimodal-v1` | enrichment cache 与可审计提取版本 |
| `ENRICHMENT_IMAGE_DETAIL` | `auto` | Responses 支持 `low/high/original/auto`；兼容端点按能力降级 |
| `ENRICHMENT_CONTEXT_CHARS` | 8000 | 相邻页/元素上下文硬上限 |

默认 template 从 OCR、表格矩阵、公式和相邻文本生成确定性描述，不调用网络。外部 provider 使用严格 JSON schema；关系只有在 `evidence_span` 确实出现在原元素时才写入图谱。local/test 可显式允许 template fallback，production fail closed。

### Ollama

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | 本机 Ollama；Compose 需要 host 可达地址 |
| `OLLAMA_CHAT_MODEL` | `qwen3:8b` | chat model |
| `OLLAMA_EMBEDDING_MODEL` | `nomic-embed-text` | embedding model |

本仓库只有 mock HTTP 契约测试，没有下载模型或伪造在线验证结果。启用前由部署者拉取模型、检查许可、容量与延迟，并用领域评测集重建索引。

### 文件与 URL

| 变量 | 默认 | 说明 |
| --- | ---: | --- |
| `DOCUMENT_REGISTRY_PATH` | `./data/registry.sqlite3` | SQLite registry |
| `OBJECT_STORE_PATH` | `./data/objects` | 内容寻址的原件与派生资源目录；不要直接作为静态目录公开 |
| `CHUNKER_VERSION` | `paragraph-v1` | 写入文档和幂等键的 chunker 版本 |
| `INDEX_VERSION` | `multimodal-v1` | parser/enrichment/chunk/graph 总兼容门；变化后需要 rebuild |
| `PARSER_VERSION` | `builtin-elements-v1` | 内置 IR 提取版本，写入文档 metadata |
| `INGESTION_POLL_SECONDS` | `0.10` | 本地 worker 空闲轮询间隔 |
| `INGESTION_LEASE_SECONDS` | `120` | 任务 claim 租约 |
| `PARSER_PROVIDER` | `builtin` | `builtin` 不下载模型；`mineru/docling/paddleocr` 通过隔离 worker |
| `PARSER_WORKER_URL` | `http://parser-worker:8090` | 仅后端访问的解析 worker 地址 |
| `PARSER_TIMEOUT_SECONDS` | `300` | 单次高级解析的硬超时 |
| `PARSER_FALLBACK_ALLOWED` | 环境推导 | 本地允许回退内置解析；production 默认 fail closed |
| `MAX_UPLOAD_BYTES` | 20 MiB | 上传硬上限 |
| `UPLOAD_PROCESSING_TIMEOUT_SECONDS` | 90 | 预留的处理超时配置 |
| `URL_IMPORT_TIMEOUT_SECONDS` | 12 | URL 网络超时 |
| `URL_IMPORT_MAX_BYTES` | 2,000,000 | URL 最大响应 |
| `RAG_ALLOW_PRIVATE_URLS` | `0` | 是否允许私网 URL；默认禁止 |

除非服务运行在隔离网络且目标清单受控，不要开启 `RAG_ALLOW_PRIVATE_URLS=1`。

### API 边界与可观测性

| 变量 | 默认 | 说明 |
| --- | ---: | --- |
| `API_AUTH_TOKEN` | 空 | 可选共享 Bearer token |
| `RATE_LIMIT_REQUESTS` | 120 | 时间窗内请求数 |
| `RATE_LIMIT_WINDOW_SECONDS` | 60 | 进程内限流窗口 |
| `SENTRY_DSN` | 空 | 安装可选依赖后启用 |
| `SENTRY_ENVIRONMENT` | `local` | 环境标签 |
| `SENTRY_TRACES_SAMPLE_RATE` | 0.05 | tracing 采样率 |
| `APP_ENVIRONMENT` | `local` | local/test/development 可选择离线 fallback；production fail closed |
| `PROVIDER_FALLBACK_ALLOWED` | 环境推导 | 显式控制回答 Provider 失败时是否使用 template |

`API_AUTH_TOKEN` 适合 curl、受信反向代理或单用户 API。当前前端不会把 secret 编译进浏览器 bundle；如果启用 token，应由同源网关在服务端注入认证，或实现正式登录流程。

Sentry 默认 `send_default_pii=False` 且不发送 request body。生产上线前仍需通过测试事件确认文档原文、URL query 和 token 没有进入事件。

## Docker 配置

Compose 为离线演示提供安全默认值，因此不创建 `.env` 也能启动。环境变量通过 `${NAME:-default}` 传入后端；SQLite 与上传文件位于 `./data:/app/data`。

```bash
docker compose config
docker compose up --build --wait -d
curl --fail http://127.0.0.1:8010/ready
```

高级解析器不进入默认镜像，也不会在普通启动时下载模型。只有明确需要 MinerU、Docling 或 PaddleOCR 时才运行：

```bash
docker compose --profile advanced-parser up --build --wait -d
PARSER_PROVIDER=mineru docker compose --profile advanced-parser up --build --wait -d
```

`parser-worker` 以非 root、只读根文件系统、丢弃 Linux capabilities、独立临时目录和资源上限运行。它只接收后端上传的本地文件，不处理 URL、浏览器凭据或 Provider Key。首次构建会下载大型依赖，耗时和磁盘占用必须在真实部署环境人工验收。

生产环境不要直接暴露示例端口和默认 DSN。应使用 TLS ingress、secret manager、受限网络、持久卷与备份策略。

## 配置变更检查表

1. 保存当前模型、维度、chunker、collection/table 与阈值版本。
2. 如果 embedding 或维度变化，创建新索引位置。
3. 在隔离环境重建索引。
4. 运行 `npm run eval:retrieval` 和代表性人工问题。
5. 检查拒答率、首条引用、延迟和 fallback。
6. 切换流量并保留回滚路径。
7. 确认日志、Sentry 和报告中没有敏感内容。
8. 检查 `/api/providers/status` 和 `needs_rebuild` 文档数为预期值。
