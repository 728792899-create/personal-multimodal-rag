# 配置指南

所有配置都来自环境变量。项目根目录与 `backend/.env` 会按顺序读取，已存在的系统环境变量不会被覆盖。不要提交真实 `.env`、API 密钥、数据库 DSN 或监控 DSN。`demo` 继续提供零密钥离线体验；`1.0.0-rc.1` 的生产目标是全云模型，不使用本地生成、嵌入或重排。

## 推荐起点

### 零密钥离线演示

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

特性：确定性、无网络成本、适合测试和作品集演示。限制：哈希嵌入不代表生产语义质量，内存向量库重启后需要从 SQLite 注册表补建。

### 持久化本地工作台

```env
EMBEDDING_PROVIDER=mock
VECTOR_STORE=chroma
CHROMA_PATH=./data/chroma
CHROMA_COLLECTION=personal_knowledge
ANSWER_PROVIDER=template
```

需要安装可选依赖。切换嵌入模型或维度时必须使用新集合并重建，不能把不同维度混写。

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

建议先只替换回答模型提供方，确认 SSE、引用审计和失败语义，再单独迁移嵌入模型。真实模型提供方会产生网络请求与费用；测试脚本会显式清空密钥并强制离线模式。

### 真实嵌入

```env
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_DIMENSION=1536
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY_FILE=/run/secrets/openai_api_key
VECTOR_STORE=chroma
CHROMA_PATH=./data/chroma-openai
CHROMA_COLLECTION=personal_knowledge_openai_large_1536
```

更换模型、维度、分块器或清洗规则都应视为索引版本变化，使用新路径/表回填并评测后再切换。

### v1 RC 生产配置

仓库的 `compose.production.yml` 已固定下列边界；不要把这段复制成含明文密钥的 `.env`：

```env
RAG_RUNTIME_MODE=production
APP_ENVIRONMENT=production
PROVIDER_FALLBACK_ALLOWED=0

METADATA_BACKEND=postgres
METADATA_DSN_FILE=/run/secrets/metadata_dsn
VECTOR_STORE=pgvector
PGVECTOR_DSN_FILE=/run/secrets/metadata_dsn
PGVECTOR_TABLE=rag_chunks_v2_initial

EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_DIMENSION=1536
OPENAI_API_KEY_FILE=/run/secrets/openai_api_key

ANSWER_PROVIDER=openai_compatible_chat
ANSWER_BASE_URL=https://api.deepseek.com
ANSWER_MODEL=deepseek-v4-flash
ANSWER_API_KEY_FILE=/run/secrets/deepseek_api_key
RERANKER=deepseek
RETRIEVAL_AUX_PROVIDER=deepseek
RETRIEVAL_AUX_BASE_URL=https://api.deepseek.com
RETRIEVAL_AUX_MODEL=deepseek-v4-flash
RETRIEVAL_AUX_API_KEY_FILE=/run/secrets/deepseek_api_key
QUERY_REWRITE_PROVIDER=deepseek

AUTH_MODE=session
ADMIN_PASSWORD_HASH_FILE=/run/secrets/admin_password_hash
SESSION_SECRET_FILE=/run/secrets/session_secret
SESSION_COOKIE_SECURE=1
CHUNKER_VERSION=structure-v2
INDEX_VERSION=retrieval-v2-initial
```

生产启动时会校验 OpenAI `text-embedding-3-large` / 1536 维、pgvector、DeepSeek 回答/辅助客户端、会话认证和文件型 secrets。任一必需项错误时失败关闭。版本化候选表与活动指针的创建、验证和切换见 [v1.0 升级手册](rag-v1-upgrade.md#6-影子索引运行手册)。

## 配置矩阵

### 嵌入

| 变量 | 默认/示例 | 说明 |
| --- | --- | --- |
| `EMBEDDING_PROVIDER` | `mock` | `mock`、`openai`、`sentence_transformers`（`huggingface` 别名）或 `ollama` |
| `EMBEDDING_MODEL` | `hash-mock` | 模型提供方模型名 |
| `EMBEDDING_DIMENSION` | `256` | 模拟嵌入默认 256；OpenAI 未设置时解析为 1536 |
| `OPENAI_API_KEY` | 空 | 本地/开发嵌入凭据；生产禁止直接设置 |
| `OPENAI_API_KEY_FILE` | 空 | 生产嵌入凭据文件；`compose.production.yml` 使用 `/run/secrets/openai_api_key` |
| `OPENAI_BASE_URL` | 空 | 本地/开发可用兼容根路径；production 只接受空值（SDK 默认）或官方 `https://api.openai.com[/v1]` |

### 向量库

| 变量 | 默认/示例 | 说明 |
| --- | --- | --- |
| `VECTOR_STORE` | `memory` | `memory`、`chroma` 或 `pgvector` |
| `CHROMA_PATH` | `./data/chroma` | 本地持久路径 |
| `CHROMA_COLLECTION` | `personal_knowledge` | 集合名 |
| `PGVECTOR_DSN` | 空/本地示例 | 本地连接串；生产改用 `PGVECTOR_DSN_FILE` |
| `PGVECTOR_DSN_FILE` | 空 | 生产 pgvector 连接串文件 |
| `PGVECTOR_TABLE` | `rag_chunks` | 版本化存储的物理 staging 表名；v1 生产 Compose 为 `rag_chunks_v2_initial`，未验证时不会自动成为服务索引 |

### 检索

| 变量 | 默认 | 说明 |
| --- | ---: | --- |
| `RERANKER` | `keyword` | `keyword`、`cross-encoder`、`deepseek` 或 `none`；v1 生产为 `deepseek` |
| `RERANKER_MODEL` | `BAAI/bge-reranker-base` | 模型重排器名称 |
| `RETRIEVAL_AUX_PROVIDER` | `none` | `none` 或 `deepseek`；为自动规划和选择性重排提供严格 JSON 客户端 |
| `RETRIEVAL_AUX_MODEL` | 回答模型/`deepseek-v4-flash` | 辅助模型 ID，保持可配置 |
| `RETRIEVAL_AUX_BASE_URL` | 回答 URL | v1 生产使用 `https://api.deepseek.com` |
| `RETRIEVAL_AUX_API_KEY_FILE` | 空 | 生产辅助模型密钥文件 |
| `RETRIEVAL_AUX_TIMEOUT_SECONDS` | 3 | 规划/重排网络超时；失败后执行受控降级 |
| `RETRIEVAL_AUX_MAX_TOKENS` | 2048 | 严格 JSON 辅助响应上限 |
| `INITIAL_RETRIEVAL_K` | 24 | 初始候选池 |
| `BM25_WEIGHT` | 0.62 | 混合检索词法权重 |
| `VECTOR_WEIGHT` | 0.38 | 混合检索向量权重 |
| `NO_ANSWER_THRESHOLD` | 0.05 | 全局拒答门槛 |
| `GROUNDING_MIN_CONFIDENCE` | 0.15 | 依据度最低置信度 |
| `CITATION_OVERLAP_THRESHOLD` | 0.34 | 引用文本重合阈值 |
| `QUERY_ASSET_MAX_BYTES` | 10485760 | 单张查询图片字节上限 |
| `QUERY_ASSET_MAX_COUNT` | 4 | 单次问题最大图片数 |
| `QUERY_ASSET_TTL_HOURS` | 24 | 临时图片保留时间（上限 24） |
| `QUERY_ASSET_MAX_PIXELS` | 40000000 | 解码后像素上限 |
| `MMR_LAMBDA` | 0.78 | MMR 相关性权重 |
| `GRAPH_WEIGHT` | 0.25 | 旧手动 `hybrid_graph` 权重；自动路由会把有效图贡献限制在 15% 以内 |
| `GRAPH_MAX_HOPS` | 2 | 图路径最大跳数，API 仍限制为 1–4 |

不要只因为一条演示问题失败就修改全局阈值。先把问题加入评测草稿，判断是召回、排序、切分、引用还是拒答门，再用固定集比较改动前后。

### 回答与查询改写

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `ANSWER_PROVIDER` | `template` | `template`、`openai_responses`、`openai_compatible_chat` 或 `ollama` |
| `ANSWER_MODEL` | `gpt-5.6` | Responses-compatible 模型名，可由环境变量覆盖 |
| `ANSWER_THINKING_MODE` | 空 | OpenAI-compatible 思考模式；支持 `enabled` / `disabled`，留空则不发送 |
| `ANSWER_MAX_TOKENS` | `0` | 回答输出上限；`0` 表示由提供方默认值决定 |
| `ANSWER_BASE_URL` | 空 | 未设置时回退 `OPENAI_BASE_URL` |
| `ANSWER_API_KEY` | 空 | 本地/开发凭据；生产禁止直接设置 |
| `ANSWER_API_KEY_FILE` | 空 | 生产回答模型密钥文件 |
| `ANSWER_TIMEOUT_SECONDS` | 45 | 生成网络超时 |
| `QUERY_REWRITE_PROVIDER` | `none` | `none`、`responses` 或 `deepseek` |
| `QUERY_REWRITE_MODEL` | 回答模型 | 改写模型 |
| `QUERY_REWRITE_BASE_URL` | 回答 URL | 改写端点 |
| `QUERY_REWRITE_API_KEY` | 回答密钥 | 本地/开发改写凭据；生产禁止直接设置 |
| `QUERY_REWRITE_API_KEY_FILE` | 空 | 生产改写凭据文件；未单独设置时可沿用回答密钥文件 |
| `QUERY_REWRITE_COUNT` | 2 | 候选改写数量 |

`responses`/`openai-responses` 旧别名继续可用。Responses 请求设置 `store:false`，流式消费官方 typed events；会话状态保存在本地 SQLite。

`APP_ENVIRONMENT=local/test/development` 默认允许显式模板回退；production 默认不允许。外部模型提供方未配置/不可用时返回脱敏 `503`，避免生产流量静默变成模板回答。`/api/providers/status` 只返回能力、配置完整性和模式，不返回密钥或带凭据 URL。

### DeepSeek V4 Flash

服务启动配置使用 OpenAI 兼容适配器：

```env
ANSWER_PROVIDER=openai_compatible_chat
ANSWER_BASE_URL=https://api.deepseek.com
ANSWER_MODEL=deepseek-v4-flash
ANSWER_THINKING_MODE=disabled
ANSWER_MAX_TOKENS=512
PROVIDER_FALLBACK_ALLOWED=0
```

密钥应通过 `ANSWER_API_KEY_FILE` 和 `RETRIEVAL_AUX_API_KEY_FILE` 注入；仓库的生产/DeepSeek Compose 默认把 `./secrets/deepseek_api_key` 挂载为 `/run/secrets/deepseek_api_key`。该文件必须被 Git 忽略并限制为当前用户可读。

已登录的管理员只可在本地/开发环境通过首页“模型连接”面板临时连接 DeepSeek。后端只允许官方地址和 `deepseek-v4-flash`，通过认证后的 `GET /models` 检查凭据及模型可用性，成功后才原子替换回答生成器。浏览器先把密钥交给当前服务端，服务端再将其作为 Bearer 凭据发送到 DeepSeek；连接生效后的问题和检索证据片段同样会发送给 DeepSeek 生成答案，面板必须在用户显式确认这一数据流后才能提交。密钥不写入浏览器存储、元数据仓库或响应，日志与可观测事件执行密钥字段脱敏；临时覆盖只作用于当前单实例后端进程，清除或重启即恢复启动配置。生产 UI 只显示状态，`POST` / `DELETE /api/providers/deepseek/runtime` 返回 `403`。疑似泄漏时必须在提供方控制台轮换。

### 多模态增强

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `ENRICHMENT_PROVIDER` | `template` | `template`、`openai_responses`、`openai_compatible_vision` 或 `ollama_vision` |
| `ENRICHMENT_MODEL` | `gpt-5.6` | 视觉/结构化输出模型名；可覆盖 |
| `ENRICHMENT_BASE_URL` | 空 | Responses 未设置时使用官方端点；compatible provider 必填 |
| `ENRICHMENT_API_KEY` | 空 | 未设置时回退 `OPENAI_API_KEY`；永不返回浏览器 |
| `ENRICHMENT_PROMPT_VERSION` | `multimodal-v1` | 增强缓存与可审计提取版本 |
| `ENRICHMENT_IMAGE_DETAIL` | `auto` | Responses 支持 `low/high/original/auto`；兼容端点按能力降级 |
| `ENRICHMENT_CONTEXT_CHARS` | 8000 | 相邻页/元素上下文硬上限 |

默认模板从 OCR、表格矩阵、公式和相邻文本生成确定性描述，不调用网络。外部模型提供方使用严格 JSON 结构定义；关系只有在 `evidence_span` 确实出现在原元素时才写入图谱。本地/测试可显式允许模板回退，生产配置失败即关闭。

### Ollama

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | 本机 Ollama；Compose 需要 host 可达地址 |
| `OLLAMA_CHAT_MODEL` | `qwen3:8b` | 聊天模型 |
| `OLLAMA_NUM_CTX` | `4096` | Ollama 回答上下文窗口；受限硬件应保持保守值 |
| `OLLAMA_NUM_PREDICT` | `256` | Ollama 单次回答的最大生成 token 数 |
| `OLLAMA_EMBEDDING_MODEL` | `nomic-embed-text` | 嵌入模型 |

本仓库只有模拟 HTTP 契约测试，没有下载模型或伪造在线验证结果。启用前由部署者拉取模型、检查许可、容量与延迟，并用领域评测集重建索引。

### 文件与 URL

| 变量 | 默认 | 说明 |
| --- | ---: | --- |
| `DOCUMENT_REGISTRY_PATH` | `./data/registry.sqlite3` | SQLite 注册表 |
| `OBJECT_STORE_PATH` | `./data/objects` | 内容寻址的原件与派生资源目录；不要直接作为静态目录公开 |
| `CHUNKER_VERSION` | `paragraph-v1` | 写入文档和幂等键的分块器版本 |
| `INDEX_VERSION` | `multimodal-v1` | 解析器/增强/分块/图谱总兼容门；变化后需要重建 |
| `PARSER_VERSION` | `builtin-elements-v1` | 内置中间表示提取版本，写入文档元数据 |
| `INGESTION_POLL_SECONDS` | `0.10` | 本地工作进程空闲轮询间隔 |
| `INGESTION_LEASE_SECONDS` | `120` | 任务认领租约 |
| `PARSER_PROVIDER` | `builtin` | `builtin` 不下载模型；`mineru/docling/paddleocr` 通过隔离工作进程 |
| `PARSER_WORKER_URL` | `http://parser-worker:8090` | 仅后端访问的解析工作进程地址 |
| `PARSER_TIMEOUT_SECONDS` | `300` | 单次高级解析的硬超时 |
| `PARSER_FALLBACK_ALLOWED` | 环境推导 | 本地允许回退内置解析；生产配置默认失败即关闭 |
| `MAX_UPLOAD_BYTES` | 20 MiB | 上传硬上限 |
| `UPLOAD_PROCESSING_TIMEOUT_SECONDS` | 90 | 预留的处理超时配置 |
| `URL_IMPORT_TIMEOUT_SECONDS` | 12 | URL 网络超时 |
| `URL_IMPORT_MAX_BYTES` | 2,000,000 | URL 最大响应 |
| `RAG_ALLOW_PRIVATE_URLS` | `0` | 是否允许私网 URL；默认禁止 |

除非服务运行在隔离网络且目标清单受控，不要开启 `RAG_ALLOW_PRIVATE_URLS=1`。

### API 边界与可观测性

| 变量 | 默认 | 说明 |
| --- | ---: | --- |
| `API_AUTH_TOKEN` | 空 | 仅兼容本地受控脚本；v1 生产拒绝共享 Bearer token |
| `AUTH_MODE` | `disabled` | `session` 启用本地成员账号；生产必需 |
| `ADMIN_PASSWORD_HASH_FILE` | 空 | 首次启动兼容引导管理员的 Argon2id 哈希文件 |
| `SESSION_SECRET_FILE` | 空 | 会话签名 secret 文件；生产必需 |
| `SESSION_TTL_SECONDS` | 43200 | 会话有效期；禁用、改角色、改密或重置后立即失效 |
| `SESSION_COOKIE_SECURE` | 环境推导 | production 默认为 `1`，要求 HTTPS |
| `RATE_LIMIT_REQUESTS` | 120 | 时间窗内请求数 |
| `RATE_LIMIT_WINDOW_SECONDS` | 60 | 进程内限流窗口 |
| `SENTRY_DSN` | 空 | 安装可选依赖后启用 |
| `SENTRY_ENVIRONMENT` | `local` | 环境标签 |
| `SENTRY_TRACES_SAMPLE_RATE` | 0.05 | 追踪采样率 |
| `APP_ENVIRONMENT` | `local` | local/test/development 可选择离线回退；production 失败即关闭 |
| `PROVIDER_FALLBACK_ALLOWED` | 环境推导 | 显式控制回答模型提供方失败时是否使用模板 |

生产成员账号是唯一受支持的浏览器认证路径。用户名唯一、密码至少 12 位、临时密码首次登录强制修改；没有公开注册。`admin` 管理成员和高影响控制面，`editor` 负责写入与同步，`viewer` 只能查询、查看引用和使用自己的会话/反馈。当前前端不会把密钥编译进浏览器资源包。

`APP_ENVIRONMENT=production` 时，`OPENAI_API_KEY`、`ANSWER_API_KEY`、`QUERY_REWRITE_API_KEY`、`RETRIEVAL_AUX_API_KEY` 和 `ENRICHMENT_API_KEY` 均禁止明文环境值，必须使用对应的 `*_API_KEY_FILE`。数据连接和会话 secrets 同样应使用 `*_FILE`。`GET /api/providers/status` 只返回脱敏状态，不返回密钥或带凭据 URL。

Sentry 默认 `send_default_pii=False` 且不发送请求正文。生产上线前仍需通过测试事件确认文档原文、URL 查询参数和令牌没有进入事件。

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

`parser-worker` 以非 root、只读根文件系统、丢弃 Linux 能力、独立临时目录和资源上限运行。它只接收后端上传的本地文件，不处理 URL、浏览器凭据或模型提供方密钥。首次构建会下载大型依赖，耗时和磁盘占用必须在真实部署环境人工验收。

GitHub Actions 的高级解析器冒烟检查仅支持手动触发：默认在 GitHub 托管运行器构建镜像并检查健康/能力契约；勾选 `run_local_model` 后，真实解析只会派发到带 `rag-parser` 标签、已准备本地模型缓存的自托管运行器。普通 PR 不下载大型模型，也不会把契约测试冒充为 MinerU、Docling 或 PaddleOCR 在线验收。

高级镜像为 apt/pip 启用了缓存与下载重试，但首次构建仍需要获取 LibreOffice 和 RAG-Anything 依赖。若镜像站下载停滞，应保留默认栈运行，改在网络稳定或已有缓存的运行器重试；不要把未完成构建记录为高级解析器通过。

生产环境不要直接暴露示例端口和默认 DSN。应使用 TLS ingress、secret manager、受限网络、持久卷与备份策略。

## 配置变更检查表

1. 保存当前模型、维度、分块器、集合/表与阈值版本。
2. 如果嵌入模型或维度变化，创建新索引位置。
3. 在隔离环境重建索引。
4. 运行 `npm run eval:retrieval` 和代表性人工问题。
5. 检查拒答率、首条引用、延迟和回退。
6. 切换流量并保留回滚路径。
7. 确认日志、Sentry 和报告中没有敏感内容。
8. 检查 `/api/providers/status` 和 `needs_rebuild` 文档数为预期值。
