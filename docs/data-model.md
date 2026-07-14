# SQLite 数据模型与生产迁移边界

0.2 用 SQLite 保存可恢复的 registry、知识库、会话和索引任务，用 vector store 保存 chunk 与向量。每次操作获取独立连接；文件数据库启用 WAL、foreign keys 与 busy timeout，避免 API 和本地 worker 跨线程共享单一连接。

![SQLite 业务表、chunk 向量存储及生产 workspace 迁移边界](assets/data-model.svg)

## 当前 schema（version 3）

`backend/app/services/document_registry.py` 创建 11 张表，其中 `schema_migrations` 记录版本：

| 表 | 作用 | 关键一致性 |
| --- | --- | --- |
| `schema_migrations` | 已应用 schema version | 幂等升级；文件 DB 升级前自动备份 |
| `knowledge_bases` | 本地知识库集合 | `default` 不可删除；列表含文档数 |
| `documents` | 可重建文档 payload | KB、content hash、index version 类型化列 |
| `conversations` | 会话标题和 KB 范围 | 最近更新时间排序 |
| `conversation_messages` | user/assistant/system 消息 | conversation 外键级联；streaming/completed/failed/cancelled |
| `index_jobs` | 入库任务事实源 | 唯一幂等键、状态/阶段、租约、尝试、取消和脱敏错误 |
| `history` | 兼容旧 `/api/ask` 的问答快照 | 新写入记录 KB；旧客户端保持可用 |
| `feedback` | 赞/踩与失败类型 | 保留 history snapshot 生成 eval draft |
| `operation_logs` | 产品内轻量审计 | 只写脱敏消息和安全 payload |
| `knowledge_cards` | 人工保存的知识卡片 | JSON payload 保持 Beta 灵活性 |
| `eval_cases` | 人工评测草稿 | 与版本化 `eval/cases.jsonl` 分离 |

迁移自动创建默认知识库，并将旧 documents/history 无损回填到 `default`。知识库含文档或终态索引任务时，删除默认返回 `409`；只有 `force=true` 才级联清理。活动任务即使带 `force=true` 也会阻止删除，必须先取消并等待进入终态。成功删除会从会话范围移除该知识库；范围变空时自动回退到 `default`。默认知识库始终保留。

## 索引版本与向量存储

文档 payload 同时记录 chunker、embedding provider/model/dimension 和 index version。启动 hydration 会比较当前配置：不兼容记录被标记为 `needs_rebuild`，不会与当前维度混用。

- `memory`：进程内 chunk/向量；启动从兼容 registry 文档重建。
- `chroma`：collection metadata 记录维度、模型和 index version；写入前校验。
- `pgvector`：可选 adapter；生产仍需正式 migration、索引和运维验证。

SQLite 不保存逐 chunk 向量。删除文档时 API 同时删除 retriever/vector store 记录和受控上传源；历史、反馈、卡片仍作为审计快照保留。

## 任务事务边界

API 接受文件时流式写暂存文件、校验签名并创建 `queued` job。worker 用 `BEGIN IMMEDIATE` 原子领取任务，写 `worker_id` 与 `lease_expires_at`；阶段进度在短事务中提交。成功后 document/vector/任务状态按顺序落地；失败保持可读状态，暂存文件被清理。

当前 worker 是单实例执行器，不应让多个应用实例共享同一 SQLite 文件消费任务。多节点需要外部队列/Postgres 原子 claim，并针对重复投递重新验证幂等。

## 会话边界

新 SSE 会话事实保存在 `conversations` 与 `conversation_messages`。上下文默认最多最近六轮、约 12,000 字符；只有明确指代型追问才将最近问题用于检索改写，独立新问题不会继承旧主题词。流式开始先写空 assistant message，完成后原位更新为最终响应；客户端断开则标记 `cancelled`，异常标记 `failed`。旧 `history` API 保留兼容，不作为新会话上下文来源。

## 生产迁移顺序

1. 建立 `workspaces`、`users`、`memberships` 与服务端授权模型。
2. 为 KB、documents、conversations/messages、jobs、feedback/cards/eval/operations 增加不可为空的 `workspace_id`。
3. 把高频过滤字段从 JSON 提升为类型化列，保留 versioned metadata JSON 处理长尾。
4. 将源文件迁移到私有对象存储，记录 object key、etag、size、content type 与保留状态。
5. 用独立 worker 和外部队列承载解析、索引、删除；保持当前 job 状态机与幂等键作为公开契约。
6. 在 versioned pgvector 表写 chunk、模型、维度、hash 和 index version；新旧索引双跑评测后切读。
7. 核对 KB/文档/任务/消息数、hash、chunk 数、向量维度、删除结果和固定回归，再停止 SQLite 写入。

升级和回滚细节见[Durable Local 0.2](durable-local-0.2.md)，生产职责见[生产适配方案](production-adapters.md)。
