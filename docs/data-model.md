# SQLite 数据模型与生产迁移边界

0.3 用 SQLite 保存可恢复的 registry、知识库、会话、索引任务、多模态元素与对象引用，用 vector store 保存 chunk 与向量。每次操作获取独立连接；文件数据库启用 WAL、foreign keys 与 busy timeout，避免 API 和本地 worker 跨线程共享单一连接。

![SQLite 业务表、chunk 向量存储及生产 workspace 迁移边界](assets/data-model.svg)

## 当前 schema（version 5）

`backend/app/services/document_registry.py` 创建 18 张表，其中 `schema_migrations` 记录版本：

| 表 | 作用 | 关键一致性 |
| --- | --- | --- |
| `schema_migrations` | 已应用 schema version | 幂等升级；文件 DB 升级前自动备份 |
| `knowledge_bases` | 本地知识库集合 | `default` 不可删除；列表含文档数 |
| `documents` | 可重建文档 payload | KB、content hash、index version 类型化列 |
| `assets` | 原件、PDF/DOCX 内嵌资源和后续临时查询资源 | 只保存内容寻址 object key；文档删除级联，API 不暴露本地路径 |
| `document_elements` | text/heading/image/table/equation/code 统一 IR | 页码、顺序、bbox、标题路径、资源、结构化表格与置信度 |
| `parser_runs` | 每次解析的 provider/profile、结果与版本快照 | 文档删除级联；与入库 job 可关联 |
| `enrichment_cache` | 上下文感知多模态 enrichment 缓存 | key 包含内容、上下文、provider、模型与 prompt version |
| `graph_nodes` | document、element、entity 节点 | KB 隔离；document/element 删除级联 |
| `graph_edges` | contains、mentions、adjacent 与显式关系 | 每条边必须有 evidence element、span、confidence、version |
| `entity_mentions` | 实体在元素中的可验证出现 | 保存 element、offset、span 与 extraction version |
| `conversations` | 会话标题和 KB 范围 | 最近更新时间排序 |
| `conversation_messages` | user/assistant/system 消息 | conversation 外键级联；streaming/completed/failed/cancelled |
| `index_jobs` | 入库任务事实源 | 唯一幂等键、状态/阶段、租约、尝试、取消和脱敏错误 |
| `history` | 兼容旧 `/api/ask` 的问答快照 | 新写入记录 KB；旧客户端保持可用 |
| `feedback` | 赞/踩与失败类型 | 保留 history snapshot 生成 eval draft |
| `operation_logs` | 产品内轻量审计 | 只写脱敏消息和安全 payload |
| `knowledge_cards` | 人工保存的知识卡片 | JSON payload 保持 Beta 灵活性 |
| `eval_cases` | 人工评测草稿 | 与版本化 `eval/cases.jsonl` 分离 |

迁移自动创建默认知识库，并将旧 documents/history 无损回填到 `default`。旧文档没有受管原件时明确写入 `source_available=false`：仍能用已有 pages 重建 chunk，但重新解析必须重新上传。知识库含文档或终态索引任务时，删除默认返回 `409`；只有 `force=true` 才级联清理。活动任务即使带 `force=true` 也会阻止删除，必须先取消并等待进入终态。成功删除会从会话范围移除该知识库；范围变空时自动回退到 `default`。默认知识库始终保留。

## 元素、对象与精确引用

上传原件先写入 `OBJECT_STORE_PATH/{sha256[:2]}/{sha256}`，扩展名和用户文件名不参与磁盘路径。相同内容复用同一对象，`assets` 维护引用；只有最后一个引用删除后才删除对象。PDF/DOCX 内嵌图片同样物化为 `derived` asset。受控下载 API 根据 registry 定位对象并返回 `nosniff`，不会把 object key 或本地绝对路径发送到浏览器。

chunk 从元素派生并保存 `element_ids`、`modality` 和 `parent_element_id`。因此引用可以先定位 chunk，再跳到精确页/元素；后续 parent-child 与 graph 检索仍以原始元素为 provenance，不允许图谱关系替代证据。

Graph-lite 仍以 SQLite 为事实来源。native extractor 只写结构关系、显式英文/中文关系、表格三元组和通过原文 span 校验的 Provider 关系。LightRAG bridge 返回的 element ID 必须属于调用方选择的本地 KB；没有本地 provenance 的 path 被丢弃。

## 索引版本与向量存储

文档 payload 同时记录 parser、enrichment、graph、chunker、embedding provider/model/dimension 和 index version。0.3 默认 `INDEX_VERSION=multimodal-v1`；启动 hydration 会比较当前配置，旧 `hybrid-v1` 或维度不兼容记录被标记为 `needs_rebuild`，不会与新 chunk/向量混用。

- `memory`：进程内 chunk/向量；启动从兼容 registry 文档重建。
- `chroma`：collection metadata 记录维度、模型和 index version；写入前校验。
- `pgvector`：可选 adapter；生产仍需正式 migration、索引和运维验证。

SQLite 不保存逐 chunk 向量。删除文档时 API 同时删除 retriever/vector store 记录和受控上传源；历史、反馈、卡片仍作为审计快照保留。

## 任务事务边界

API 接受文件时流式写暂存文件、校验签名、写内容寻址对象并创建 `queued` job。worker 用 `BEGIN IMMEDIATE` 原子领取任务，写 `worker_id` 与 `lease_expires_at`；阶段进度在短事务中提交。成功后 document/vector/asset/任务状态按顺序落地；失败保留可重试的原件，取消或去重会释放无引用对象。同步兼容 API 若中途失败会回滚文档、向量、asset 和无引用对象。

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
