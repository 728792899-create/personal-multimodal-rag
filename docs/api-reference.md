# API 使用指南

FastAPI 默认提供交互式 OpenAPI 页面：

- Swagger UI：`http://127.0.0.1:8010/docs`
- OpenAPI JSON：`http://127.0.0.1:8010/openapi.json`
- 通过前端 Nginx 访问业务 API：`http://127.0.0.1:5173/api/*`

当前 API 服务于单用户/小团队 Beta，字段会随 Beta 迭代。外部集成应固定版本或在升级前比较 OpenAPI schema。

## 认证、请求 ID 与限流

默认 `API_AUTH_TOKEN` 为空，不要求认证。配置 token 后，除 `/health`、`/ready` 与文档端点外，请求必须携带：

```http
Authorization: Bearer <token>
```

服务端为每个请求生成或透传请求 ID，错误排查时应记录该 ID，但不要复制 Authorization、完整 URL query 或资料原文到公共 issue。

进程内限流超过阈值时返回 `429` 和 `Retry-After`。这是本地 Beta 防护，不等价于分布式网关限流。

## 健康与就绪

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 进程健康；用于 liveness |
| GET | `/ready` | schema、队列深度和脱敏 Provider 状态；未配置外部 Provider 时为 `degraded` |
| GET | `/api/providers/status` | 只读能力、配置完整性与运行模式；不返回 Key/带凭据 URL |
| GET | `/docs` | Swagger UI |

```bash
curl --fail http://127.0.0.1:8010/ready
```

## 文档 API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/documents` | 文档、索引状态与质量摘要 |
| GET | `/api/documents/{document_id}` | 文档页、chunk 与 metadata |
| GET | `/api/documents/{document_id}/elements` | 按原始顺序返回类型化文档元素 |
| GET | `/api/documents/{document_id}/source` | 受控下载原件；无受管原件时 `404` |
| GET | `/api/assets/{asset_id}` | 受控读取文档资源；不暴露 object key/本地路径 |
| POST | `/api/documents` | `multipart/form-data` 上传并索引 |
| POST | `/api/imports/url` | 导入公开 HTTP(S) 页面 |
| DELETE | `/api/documents/{document_id}` | 删除 registry、索引和受管上传文件 |
| POST | `/api/documents/{document_id}/rebuild` | 重建单文档索引 |
| POST | `/api/documents/{document_id}/reindex` | 0.3 语义别名；行为与 rebuild 兼容 |
| POST | `/api/documents/rebuild-all` | 重建全部文档索引 |
| GET | `/api/parsers/status` | 内置/高级解析 profile 的可用性；不触发模型下载 |

同步上传/URL API为 0.1 客户端保留。0.2 前端默认使用后面的异步任务接口。

上传示例：

```bash
curl --fail-with-body \
  -F 'file=@samples/demo-documents/01-system-overview.md' \
  http://127.0.0.1:8010/api/documents
```

URL 导入示例：

```bash
curl --fail-with-body \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com","title":"Example public page"}' \
  http://127.0.0.1:8010/api/imports/url
```

URL 导入只允许公开 HTTP(S) 地址。回环、内网、链路本地、嵌入凭据、危险重定向、二进制类型、超大响应和超时都会被拒绝。

## 知识库与异步入库

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET / POST | `/api/knowledge-bases` | 列表 / 创建知识库 |
| PATCH | `/api/knowledge-bases/{id}` | 改名或更新描述 |
| GET | `/api/knowledge-bases/{id}/graph?limit=500` | provenance-backed Graph-lite 快照；只返回所选 KB |
| DELETE | `/api/knowledge-bases/{id}?force=false` | 有文档/终态任务时需 `force=true`；活动任务始终 `409`；默认库不可删除 |
| POST | `/api/ingestions/file` | multipart 文件入队，返回 `202` + `IndexJob` |
| POST | `/api/ingestions/url` | URL 入队，返回 `202` + `IndexJob` |
| GET | `/api/index-jobs`、`/api/index-jobs/{id}` | 任务中心与单任务状态 |
| POST | `/api/index-jobs/{id}/retry` | 仅 failed/cancelled 可重试 |
| DELETE | `/api/index-jobs/{id}` | 请求取消；running 先进入 cancelling |

文件表单字段是 `file`、`knowledge_base_id`、可选 `parser_profile`、`enrich_modalities` 和 `build_graph`。默认是 `builtin/true/true`；`mineru/docling/paddleocr/auto` 需要隔离 parser worker。任务状态为 `queued/running/succeeded/failed/cancelling/cancelled`；阶段包含 `receive/validate/parse/extract_elements/enrich_modalities/chunk/embed/graph_extract/graph_write/quality/complete`。重复幂等请求会返回已有任务，不重复创建文档。

强制删除知识库会级联清理其文档与终态任务，并从持久会话范围移除该库；若会话不再选择任何库，则回退到默认库。为避免 worker 写回已删除空间，仍处于 queued/running/cancelling 的任务必须先取消并等待终态。

```bash
curl --fail-with-body -F knowledge_base_id=default \
  -F 'file=@samples/demo-documents/01-system-overview.md' \
  http://127.0.0.1:8010/api/ingestions/file
```

## 检索与问答 API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/search?q=...` | 简单检索，支持 `top_k`、`search_mode` |
| POST | `/api/search` | 完整检索选项 |
| POST | `/api/search/compare` | 对照搜索配置 |
| POST | `/api/ask` | 检索、拒答/生成、引用审计和缺口分析 |
| GET | `/api/chunks/{chunk_id}/context` | 引用相邻上下文，`window=0..3` |
| GET | `/api/history?limit=30` | 问答历史 |
| DELETE | `/api/history` | 清空问答历史 |

离线问答示例：

```bash
curl --fail-with-body \
  -H 'Content-Type: application/json' \
  -d '{
    "question":"默认演示是否需要真实 API Key？",
    "search_mode":"hybrid",
    "search_profile":"balanced",
    "top_k":5,
    "candidate_k":24,
    "document_ids":[],
    "query_rewrite":true,
    "rerank_enabled":true
  }' \
  http://127.0.0.1:8010/api/ask
```

`POST /api/search` 使用相同检索字段，只需把 `question` 改为 `query`。

### 检索参数

| 字段 | 类型/范围 | 默认 | 说明 |
| --- | --- | ---: | --- |
| `top_k` | 1–12 | 5 | 返回给回答阶段的证据数 |
| `candidate_k` | 1–80 或 null | provider 默认 | 初始候选池 |
| `search_mode` | hybrid / keyword / semantic | hybrid | 召回分支 |
| `search_profile` | balanced / precision / recall | balanced | 目标导向预设 |
| `strategy` | hybrid / hybrid_graph / auto | hybrid | 图谱显式启用或按多跳/多实体门控 |
| `document_ids` | string[] | [] | 空数组代表全库 |
| `knowledge_base_ids` | string[] | [] | 缺省使用默认库；先隔离 KB 再应用文档筛选 |
| `bm25_weight` | 0–1 或 null | 环境默认 | 融合词法权重 |
| `vector_weight` | 0–1 或 null | 环境默认 | 融合向量权重 |
| `mmr_lambda` | 0–1 或 null | 环境默认 | 相关性/多样性权衡 |
| `min_score` | 0–1 或 null | 环境默认 | 请求级最低分 |
| `query_rewrite` | boolean | true | 是否允许查询改写 adapter |
| `rerank_enabled` | boolean | true | 是否运行 reranker |
| `graph_weight` | 0–1 | 0.25 | Graph evidence 在加权 RRF 中的权重 |
| `graph_max_hops` | 1–4 | 2 | provenance-backed path 最大跳数 |
| `modality_filters` | element type[] | [] | 只召回指定 text/image/table/equation 等 chunk |
| `parent_window` | 0–3 | 1 | 引用 parent-child 相邻 chunk 窗口 |

`hybrid_graph` 不把图边直接当答案：图只返回 element ID，再映射到现有 chunk 参与 RRF。`auto` 只有在至少两个 entity seed 或明确多跳意图、且存在可验证路径时启用；图谱后仍运行 MMR、rerank、拒答与引用审计。

### 问答响应结构

`POST /api/ask` 的关键字段：

```json
{
  "answer": "...",
  "citations": [],
  "retrieval_trace": {},
  "generation_trace": {},
  "confidence": 0.0,
  "trust": {},
  "citation_audit": {},
  "gap_report": {},
  "history_id": "...",
  "created_at": "..."
}
```

拒答仍返回成功的业务响应，并在 `answer`、`trust`、`retrieval_trace` 和 `gap_report` 中说明证据不足；调用方不应把它当网络错误重试。

## 持久会话与 SSE

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET / POST | `/api/conversations` | 列表 / 创建会话 |
| GET / PATCH / DELETE | `/api/conversations/{id}` | 读取、改名/切换 KB、删除 |
| GET | `/api/conversations/{id}/messages` | 按时间读取消息 |
| POST | `/api/conversations/{id}/messages:stream` | `text/event-stream` 回答 |

每个 SSE data payload 都含 `type`、`request_id`、`conversation_id`、`message_id` 与严格递增 `sequence`。事件 union 固定为：

```text
retrieval.started
retrieval.completed
answer.delta
answer.completed
refusal
error
done
```

无证据时不会调用生成 Provider，而是发送 `refusal` 后 `done`。有证据时 `answer.delta` 只代表待审计正文；引用、confidence 与 citation audit 以 `answer.completed.response` 为准。客户端应按 `sequence` 去重，收到 `done` 后结束；中断连接会把 assistant message 标记为 `cancelled`。

## 质量、反馈与知识工具

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/knowledge/overview` | 文档、chunk 和历史问题概览 |
| POST | `/api/evaluate` | 运行内存中的简易 case 集 |
| POST | `/api/eval/cases` | 保存人工 eval draft |
| GET | `/api/eval/drafts` | 合并人工与反馈生成的草稿 |
| POST | `/api/eval/run-drafts` | 对草稿运行评测 |
| POST | `/api/feedback` | 保存赞/踩、失败类型和历史快照 |
| GET | `/api/feedback` | 反馈列表与统计 |
| POST | `/api/answer/rewrite` | 基于现有答案和引用改写表达 |
| POST | `/api/knowledge/cards` | 从回答与引用生成知识卡片 |
| GET | `/api/knowledge/cards` | 知识卡片列表 |
| DELETE | `/api/knowledge/cards/{card_id}` | 删除卡片 |
| POST | `/api/knowledge/gaps` | 检索并分析资料缺口 |
| GET | `/api/operations` | 安全化操作事件 |
| GET | `/api/metrics` | Beta 业务与质量摘要 |

负反馈示例：

```bash
curl --fail-with-body \
  -H 'Content-Type: application/json' \
  -d '{
    "question":"系统是否支持某个资料外功能？",
    "answer":"现有回答",
    "rating":"down",
    "failure_type":"unsupported_claim",
    "feedback_text":"引用没有支撑这个结论",
    "expected_answer":"证据不足时应拒答",
    "citations":[]
  }' \
  http://127.0.0.1:8010/api/feedback
```

## 错误语义

| 状态码 | 常见原因 | 客户端行为 |
| ---: | --- | --- |
| 400 | 无效文件、URL、字段或解析失败 | 修正输入；不要盲目重试 |
| 401 | Bearer token 缺失或错误 | 重新认证；不记录 token |
| 404 | 文档、chunk 或卡片不存在 | 刷新当前资源列表 |
| 413 | 文件超过 `MAX_UPLOAD_BYTES` | 压缩或调整显式上限 |
| 422 | Pydantic schema 校验失败 | 按字段错误修正 payload |
| 429 | 进程内限流 | 等待 `Retry-After` 后重试 |
| 409 | 有内容的 KB 删除、不可重试任务或索引冲突 | 刷新状态并执行显式操作 |
| 503 | production 外部 Provider 未配置/不可用 | 查看 `/api/providers/status`，不要期待静默模板降级 |
| 500 | 未处理的服务端错误 | 记录请求 ID，查看安全日志 |

前端 client 同时处理 Abort、请求超时和 Nginx 502/504，并保留最近一次成功回答，避免错误页面抹掉可用证据。
