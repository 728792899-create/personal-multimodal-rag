# API 使用指南

FastAPI 默认提供交互式 OpenAPI 页面：

- Swagger UI：`http://127.0.0.1:8010/docs`
- OpenAPI JSON：`http://127.0.0.1:8010/openapi.json`
- 通过前端 Nginx 访问业务 API：`http://127.0.0.1:5173/api/*`

当前 API 对应 `1.0.0-rc.1`：服务于单工作区、5–10 人内部团队，字段仍可能随候选版迭代。外部集成应固定版本或在升级前比较 OpenAPI 结构定义。RC 仍处于发布阻断状态，不代表生产验收已经完成。

## 认证、工作区、请求 ID 与限流

`demo` 默认关闭认证；`local-production` 可启用会话；`production` 强制本地成员账号、Argon2id、HttpOnly/Secure/SameSite Cookie 与 CSRF。没有公开注册；生产不接受共享 Bearer token 作为成员认证替代。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/auth/login` | `{username, password}`；校验成员并创建 HttpOnly 会话；独立限流 |
| POST | `/api/auth/logout` | 撤销当前会话；要求 CSRF |
| GET | `/api/auth/session` | 返回认证状态、成员身份、服务端工作区、角色、强制改密状态和 CSRF 令牌 |
| POST | `/api/auth/password` | `{current_password, new_password}`；新密码至少 12 位，成功后撤销会话并要求重新登录 |
| GET / POST | `/api/auth/members` | 管理员列出/创建成员；创建时提供至少 12 位临时密码 |
| GET / PATCH / DELETE | `/api/auth/members/{user_id}` | 管理员查看、改名/改角色/禁用成员；DELETE 为禁用 |
| POST | `/api/auth/members/{user_id}/reset-password` | 管理员设置临时密码并撤销该成员全部会话 |

会话关键字段如下；首次登录临时密码的成员只能先完成改密流程：

```json
{
  "user_id": "user-id",
  "username": "alice",
  "display_name": "Alice",
  "role": "viewer",
  "workspace_id": "default",
  "must_change_password": true,
  "csrf_token": "...",
  "expires_at": "..."
}
```

`admin` 可管理成员、删除知识库、重建/切换索引和读取全局审计；`editor` 可查询、上传、同步和编辑资料；`viewer` 可查询、查看引用、管理自己的会话并提交自己的反馈。禁用、改角色、重置密码或用户改密会撤销相关会话；最后一个管理员不能被删除、禁用或降级。

工作区永远从服务端会话解析。浏览器请求体、查询参数或请求头中自报的工作区都不构成授权依据。

服务端为每个请求生成或透传请求 ID，错误排查时应记录该 ID，但不要复制 Authorization、完整 URL 查询参数或资料原文到公开问题单。

进程内限流超过阈值时返回 `429` 和 `Retry-After`。这是本地候选版防护，不等价于分布式网关限流。

## 健康与就绪

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 进程健康；用于存活检查 |
| GET | `/ready` | 结构定义、队列深度和脱敏模型提供方状态；未配置外部模型提供方时为 `degraded` |
| GET | `/api/system/readiness-report` | 运行时、元数据/对象/向量/队列/模型提供方的逐项就绪报告 |
| GET | `/api/providers/status` | 只读能力、配置完整性与运行模式；不返回密钥/带凭据 URL |
| POST | `/api/providers/deepseek/runtime` | 仅本地/开发：管理员临时验证并连接 DeepSeek；生产返回 `403` |
| DELETE | `/api/providers/deepseek/runtime` | 仅本地/开发：清除临时连接；生产返回 `403` |
| GET | `/metrics` | Prometheus 文本格式；不包含正文、问题、Cookie、密钥或 URL 查询参数 |
| GET | `/docs` | Swagger UI |

```bash
curl --fail http://127.0.0.1:8010/ready
```

`production` 任一必需依赖不可用时 `/ready` 返回 `503`，不会静默切回模板回答。

## 版本化索引管理

所有索引控制面接口只允许 `admin`。生产浏览器请求需要会话 Cookie 和 CSRF；接口不会接受客户端自报的角色。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/indexes` | 列出候选/稳定/活动/回滚/失败索引与活动指针 |
| GET | `/api/indexes/active` | 返回当前请求应固定使用的活动索引和 generation |
| POST | `/api/indexes/candidates` | 创建 1536 维候选及 `rag_chunks_v2_*` 表 |
| POST | `/api/indexes/{index_id}/rebuild` | 通过现有 durable job 幂等重建并自动验证；返回 `202` |
| PUT | `/api/indexes/{index_id}/validation` | 受控验证器回写 checklist/metrics，不是人工跳过验证的入口 |
| POST | `/api/indexes/{index_id}/promote` | 所有必需 validation 通过后将候选标记为 stable |
| POST | `/api/indexes/{index_id}/activate` | 单事务切换 `active_index_id`，并记录上一稳定版本 |
| POST | `/api/indexes/rollback` | 单事务切回 `previous_index_id` |

创建候选示例：

```json
{
  "index_id": "retrieval-v2-20260809",
  "parser_version": "builtin-elements-v1",
  "chunker_version": "structure-v2",
  "source_index_id": "retrieval-v2-stable",
  "embedding_provider": "openai",
  "embedding_model": "text-embedding-3-large",
  "embedding_dimension": 1536
}
```

重建请求体是 `{"benchmark_samples": 100}`。`promote` 前必须通过文档/分块/内容哈希、模型/维度/解析/分块版本、向量合法性、主键、引用、HNSW Recall 和费用偏差检查。完整冻结、补增量、激活与回滚步骤见 [v1.0 升级手册](rag-v1-upgrade.md#6-影子索引运行手册)。

## 文档 API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/documents` | 文档、索引状态与质量摘要 |
| GET | `/api/documents/{document_id}` | 文档页、分块与元数据 |
| GET | `/api/documents/{document_id}/elements` | 按原始顺序返回类型化文档元素 |
| GET | `/api/documents/{document_id}/source` | 受控下载原件；无受管原件时 `404` |
| GET | `/api/assets/{asset_id}` | 受控读取文档资源；不暴露对象键/本地路径 |
| POST | `/api/documents` | `multipart/form-data` 上传并索引 |
| POST | `/api/imports/url` | 导入公开 HTTP(S) 页面 |
| DELETE | `/api/documents/{document_id}` | 删除注册表、索引和受管上传文件 |
| POST | `/api/documents/{document_id}/rebuild` | 重建单文档索引 |
| POST | `/api/documents/{document_id}/reindex` | 0.3 语义别名；行为与 rebuild 兼容 |
| POST | `/api/documents/rebuild-all` | 重建全部文档索引 |
| GET | `/api/parsers/status` | 内置/高级解析配置的可用性；不触发模型下载 |

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
| GET | `/api/knowledge-bases/{id}/graph?limit=500` | 具有来源依据的轻量图谱快照；只返回所选知识库 |
| DELETE | `/api/knowledge-bases/{id}?force=false` | 有文档/终态任务时需 `force=true`；活动任务始终 `409`；默认库不可删除 |

### 临时查询图片

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/query-assets` | multipart `files` + `knowledge_base_id`；最多 4 张、单张 10 MB |
| GET | `/api/assets/{id}` | 受控预览；过期返回 `410` |
| DELETE | `/api/query-assets/{id}` | 提前删除临时图片 |

只接受实际解码为 PNG、JPEG、WEBP 或非动画 GIF 的资产；扩展名和宣称 MIME 不作为信任依据。资产绑定知识库，24 小时后清理。
| POST | `/api/ingestions/file` | multipart 文件入队，返回 `202` + `IndexJob` |
| POST | `/api/ingestions/url` | URL 入队，返回 `202` + `IndexJob` |
| GET | `/api/index-jobs`、`/api/index-jobs/{id}` | 任务中心与单任务状态 |
| POST | `/api/index-jobs/{id}/retry` | 仅失败/已取消的任务可重试 |
| DELETE | `/api/index-jobs/{id}` | 请求取消；运行中的任务先进入取消中 |

文件表单字段是 `file`、`knowledge_base_id`、可选 `parser_profile`、`enrich_modalities` 和 `build_graph`。默认是 `builtin/true/true`；`mineru/docling/paddleocr/auto` 需要隔离解析工作进程。任务状态为 `queued/running/succeeded/failed/cancelling/cancelled`；阶段包含 `receive/validate/parse/extract_elements/enrich_modalities/chunk/embed/graph_extract/graph_write/quality/complete`。重复幂等请求会返回已有任务，不重复创建文档。

强制删除知识库会级联清理其文档与终态任务，并从持久会话范围移除该库；若会话不再选择任何库，则回退到默认库。为避免工作进程写回已删除空间，仍处于 queued/running/cancelling 的任务必须先取消并等待终态。

```bash
curl --fail-with-body -F knowledge_base_id=default \
  -F 'file=@samples/demo-documents/01-system-overview.md' \
  http://127.0.0.1:8010/api/ingestions/file
```

## 持续数据源、同步与 Markdown 导出

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET / POST | `/api/sources` | 列表 / 创建白名单目录、URL 列表或 RSS/Atom 来源 |
| GET / PATCH / DELETE | `/api/sources/{id}` | 读取、修改、停用或删除订阅配置 |
| POST | `/api/sources/{id}/sync` | 启动增量发现；内容变化进入原有索引任务 |
| POST | `/api/sources/{id}/deletions:confirm` | 人工确认连续两次缺失的删除候选 |
| GET | `/api/sync-runs`、`/api/sync-runs/{id}` | 查看发现、未变化、更新、失败和候选数 |
| POST | `/api/sync-runs/{id}/retry` | 对失败或中断的同步运行做幂等重试 |
| GET | `/api/exports/history/{id}.md` | 导出带引用的单次回答 |
| GET | `/api/exports/conversations/{id}.md` | 导出带引用的持久会话 |
| GET | `/api/exports/knowledge-cards/{id}.md` | 导出知识卡片 |

目录来源只接受 `GET /api/sources` 响应 `capabilities.directory_roots` 返回的不可逆根目录 ID 与相对路径；不能提交任意服务器路径。空结果、304 和部分失败都不会推进删除计数。完整非空同步连续两次未发现某条目后，它只进入候选状态，仍需显式确认。详见[持续数据源与增量同步](source-sync.md)。

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
    ,"attachments":[{"id":"query-asset-id","detail":"auto"}]
  }' \
  http://127.0.0.1:8010/api/ask
```

`POST /api/search` 使用相同检索字段，只需把 `question` 改为 `query`。

### 检索参数

| 字段 | 类型/范围 | 默认 | 说明 |
| --- | --- | ---: | --- |
| `top_k` | 1–12 | 5 | 返回给回答阶段的证据数 |
| `candidate_k` | 1–80 或 null | 模型提供方默认 | 初始候选池 |
| `routing_mode` | auto / manual | manual | 新界面发送 `auto`；旧客户端省略时保持原手动行为 |
| `search_mode` | hybrid / keyword / semantic | hybrid | 召回分支 |
| `search_profile` | balanced / precision / recall | balanced | 目标导向预设 |
| `strategy` | hybrid / hybrid_graph / auto | hybrid | 图谱显式启用或按多跳/多实体门控 |
| `document_ids` | string[] | [] | 空数组代表全库 |
| `knowledge_base_ids` | string[] | [] | 缺省使用默认库；先隔离 KB 再应用文档筛选 |
| `bm25_weight` | 0–1 或 null | 环境默认 | 融合词法权重 |
| `vector_weight` | 0–1 或 null | 环境默认 | 融合向量权重 |
| `mmr_lambda` | 0–1 或 null | 环境默认 | 相关性/多样性权衡 |
| `min_score` | 0–1 或 null | 环境默认 | 请求级最低分 |
| `query_rewrite` | boolean | true | 是否允许查询改写适配器 |
| `rerank_enabled` | boolean | true | 是否运行重排器 |
| `graph_weight` | 0–1 | 0.25 | 图谱证据在加权 RRF 中的权重 |
| `graph_max_hops` | 1–4 | 2 | 具有来源依据路径的最大跳数 |
| `modality_filters` | 元素类型数组 | [] | 只召回指定文本/图片/表格/公式等分块 |
| `parent_window` | 0–3 | 1 | 引用父子相邻分块窗口 |

`hybrid_graph` 不把图边直接当答案：图只返回元素 ID，再映射到现有分块参与 RRF。`auto` 只有在至少两个实体种子或明确多跳意图、且存在可验证路径时启用；图谱后仍运行 MMR、重排、拒答与引用审计。

`routing_mode=auto` 固定为 `exact`、`semantic`、`composite`、`multihop`、`summary` 五路之一。自动规划最多产生 3 个派生查询、每分支 40 个候选、融合池 40、DeepSeek 重排 Top-16；普通回答最多 8 块，复合/多跳最多 10 块。自动规划不得扩大请求中的 `document_ids`、`knowledge_base_ids` 或 `modality_filters`。

`attachments` 为可选图片引用，`detail` 可为 `low/high/original/auto`。离线配置用 OCR/元数据扩展检索；视觉增强模型提供方按细节级别发送图片并返回结构化描述。

### 问答响应结构

`POST /api/ask` 的关键字段：

```json
{
  "answer": "...",
  "citations": [],
  "retrieval_trace": {
    "plan": {
      "route": "semantic",
      "confidence": 0.82,
      "decision_factors": ["semantic_default"],
      "subqueries": [],
      "modifiers": {},
      "source": "structured",
      "index_version": "retrieval-v2-20260809",
      "degraded": false,
      "fallbacks": []
    },
    "pipeline": {
      "retrieval_health": {
        "version": "retrieval-health-v1",
        "status": "insufficient_history",
        "eligible": true,
        "exclude_reason": "",
        "sparse_dense_top10": {},
        "candidate_diversity": {},
        "cross_query": {},
        "alerts": []
      }
    }
  },
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

查询规划失败会按原问执行 balanced hybrid；重排失败保留 RRF 顺序；OpenAI 嵌入失败时只有高置信 `exact` 可以继续 BM25，其他路由明确拒答；DeepSeek 生成失败返回已检索证据、故障状态和重试入口，不生成模板答案。带版本/型号的问题在叶级证据未精确覆盖时会在生成前拒答。单次请求的文档和知识库过滤列表各最多 200 项，每个 ID 最长 160 字符。`retrieval_health` 是有界、进程内的检索退化预警，不会自动改排序或放行答案。trace 只包含结构化决策因素，不包含模型思维过程。

## 持久会话与 SSE

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET / POST | `/api/conversations` | 列表 / 创建会话 |
| GET / PATCH / DELETE | `/api/conversations/{id}` | 读取、改名/切换 KB、删除 |
| GET | `/api/conversations/{id}/messages` | 按时间读取消息 |
| POST | `/api/conversations/{id}/messages:stream` | `text/event-stream` 回答 |

每个 SSE data payload 都含 `type`、`request_id`、`conversation_id`、`message_id` 与严格递增 `sequence`。事件 union 固定为：

```text
query.enrichment.started   # 仅带附件时
query.enrichment.completed # 仅带附件时
retrieval.started
retrieval.completed
answer.delta
answer.completed
refusal
error
done
```

纯文本请求的原有顺序不变。带图片时在 `retrieval.started` 前增加两个查询增强事件；完成负载只返回可见摘要，不暴露对象键。无证据时不会调用生成模型提供方，而是发送 `refusal` 后 `done`。有证据时 `answer.delta` 只代表待审计正文；引用、置信度与引用审计以 `answer.completed.response` 为准。客户端应按 `sequence` 去重，收到 `done` 后结束；中断连接会把助手消息标记为 `cancelled`。

## 质量、反馈与知识工具

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/knowledge/overview` | 文档、分块和历史问题概览 |
| POST | `/api/evaluate` | 运行内存中的简易案例集 |
| POST | `/api/eval/cases` | 保存人工评测草稿 |
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
| GET | `/api/metrics` | 候选版业务与质量摘要 |

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
| 401 | Bearer 令牌缺失或错误 | 重新认证；不记录令牌 |
| 403 | 角色无权、CSRF 无效或生产环境尝试运行时配置密钥 | 不重试越权操作；由管理员或部署配置处理 |
| 404 | 文档、分块或卡片不存在 | 刷新当前资源列表 |
| 413 | 文件超过 `MAX_UPLOAD_BYTES` | 压缩或调整显式上限 |
| 422 | Pydantic 结构定义校验失败 | 按字段错误修正请求负载 |
| 429 | 进程内限流 | 等待 `Retry-After` 后重试 |
| 409 | 有内容的 KB 删除、不可重试任务或索引冲突 | 刷新状态并执行显式操作 |
| 503 | 生产配置外部模型提供方未配置/不可用 | 查看 `/api/providers/status`，不要期待静默模板降级 |
| 500 | 未处理的服务端错误 | 记录请求 ID，查看安全日志 |

前端客户端同时处理中止、请求超时和 Nginx 502/504，并保留最近一次成功回答，避免错误页面抹掉可用证据。
