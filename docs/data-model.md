# SQLite 数据模型与生产迁移边界

0.4 候选版的演示与本地生产配置用 SQLite 保存可恢复注册表；生产配置使用同一仓储契约的 PostgreSQL 适配器。向量库保存分块与向量，对象层使用本地内容寻址目录或 S3/MinIO。SQLite 每次操作获取独立连接并启用 WAL、外键与忙碌超时，避免 API 和本地工作进程跨线程共享单一连接。

![SQLite 业务表、分块向量存储及生产工作区迁移边界](assets/data-model.svg)

## 当前结构定义（版本 7）

`backend/app/services/document_registry.py` 创建 27 张业务/控制表，其中 `schema_migrations` 记录幂等版本：

| 表 | 作用 | 关键一致性 |
| --- | --- | --- |
| `schema_migrations` | 已应用结构定义版本 | 幂等升级；文件数据库升级前自动备份 |
| `knowledge_bases` | 本地知识库集合 | `default` 不可删除；列表含文档数 |
| `documents` | 可重建文档负载 | 知识库、内容哈希、索引版本类型化列 |
| `assets` | 原件、PDF/DOCX 内嵌资源和后续临时查询资源 | 只保存内容寻址对象键；文档删除级联，API 不暴露本地路径 |
| `document_elements` | text/heading/image/table/equation/code 统一 IR | 页码、顺序、bbox、标题路径、资源、结构化表格与置信度 |
| `parser_runs` | 每次解析的模型提供方/配置、结果与版本快照 | 文档删除级联；与入库任务可关联 |
| `enrichment_cache` | 上下文感知多模态增强缓存 | 键包含内容、上下文、模型提供方、模型与提示词版本 |
| `graph_nodes` | document、element、entity 节点 | KB 隔离；document/element 删除级联 |
| `graph_edges` | contains、mentions、adjacent 与显式关系 | 每条边必须有 evidence element、span、confidence、version |
| `entity_mentions` | 实体在元素中的可验证出现 | 保存元素、偏移、文本范围与提取版本 |
| `conversations` | 会话标题和 KB 范围 | 最近更新时间排序 |
| `conversation_messages` | 用户/助手/系统消息 | 会话外键级联；流式/已完成/失败/已取消 |
| `index_jobs` | 入库任务事实源 | 唯一幂等键、状态/阶段、租约、尝试、取消和脱敏错误 |
| `history` | 兼容旧 `/api/ask` 的问答快照 | 新写入记录 KB；旧客户端保持可用 |
| `feedback` | 赞/踩与失败类型 | 保留历史快照生成评测草稿 |
| `operation_logs` | 产品内轻量审计 | 只写脱敏消息和安全负载 |
| `knowledge_cards` | 人工保存的知识卡片 | JSON 负载保持候选版灵活性 |
| `eval_cases` | 人工评测草稿 | 与版本化 `eval/cases.jsonl` 分离 |
| `workspaces`、`users`、`memberships` | 默认工作区、所有者与成员边界 | API 工作区从服务端会话解析 |
| `sessions` | 管理员登录会话 | 只保存令牌哈希、过期和撤销状态 |
| `outbox_events` | 元数据事务内的可靠任务事件 | Redis 发布成功后标记；重复发布仍由幂等键收敛 |
| `dead_letter_jobs` | 超过重试上限的生产任务 | 保留脱敏错误、重放次数和人工处理状态 |
| `sources` | 目录、URL 列表、RSS/Atom 订阅 | 绑定 workspace/KB；配置不接受任意服务器路径 |
| `source_items` | 稳定外部 ID、哈希、缓存头和索引文档 | `(source_id, external_id)` 唯一；维护缺失计数 |
| `sync_runs` | 一次增量发现事实 | 记录更新、未变化、失败、空结果、部分结果和删除候选 |

迁移自动创建默认知识库，并将旧 documents/history 无损回填到 `default`。旧文档没有受管原件时明确写入 `source_available=false`：仍能用已有页面重建分块，但重新解析必须重新上传。知识库含文档或终态索引任务时，删除默认返回 `409`；只有 `force=true` 才级联清理。活动任务即使带 `force=true` 也会阻止删除，必须先取消并等待进入终态。成功删除会从会话范围移除该知识库；范围变空时自动回退到 `default`。默认知识库始终保留。

## 元素、对象与精确引用

上传原件先写入 `OBJECT_STORE_PATH/{sha256[:2]}/{sha256}`，扩展名和用户文件名不参与磁盘路径。相同内容复用同一对象，`assets` 维护引用；只有最后一个引用删除后才删除对象。PDF/DOCX 内嵌图片物化为 `derived`，图片提问使用 `query` 并在 24 小时后清理；两者都继承 KB 边界。受控资产 API 根据 registry 定位对象并返回 `nosniff`，不会把 object key 或本地绝对路径发送到浏览器。

分块从元素派生并保存 `element_ids`、`modality` 和 `parent_element_id`。因此引用可以先定位分块，再跳到精确页/元素；后续父子与图谱检索仍以原始元素为来源依据，不允许图谱关系替代证据。

轻量图谱仍以 SQLite 为事实来源。原生提取器只写结构关系、显式英文/中文关系、表格三元组和通过原文文本范围校验的模型提供方关系。LightRAG 桥接返回的元素 ID 必须属于调用方选择的本地知识库；没有本地来源依据的路径被丢弃。

## 索引版本与向量存储

文档负载同时记录解析器、增强、图谱、分块器、嵌入模型提供方/模型/维度和索引版本。0.3 默认 `INDEX_VERSION=multimodal-v1`；启动加载会比较当前配置，旧 `hybrid-v1` 或维度不兼容记录被标记为 `needs_rebuild`，不会与新分块/向量混用。

- `memory`：进程内分块/向量；启动从兼容注册表文档重建。
- `chroma`：集合元数据记录维度、模型和索引版本；写入前校验。
- `pgvector`：可选适配器；生产仍需正式迁移、索引和运维验证。

SQLite 不保存逐分块向量。删除文档时 API 同时删除检索器/向量库记录和受控上传源；历史、反馈、卡片仍作为审计快照保留。

## 任务事务边界

API 接受文件时流式写暂存文件、校验签名、写内容寻址对象并创建 `queued` 任务。工作进程用 `BEGIN IMMEDIATE` 原子领取任务，写 `worker_id` 与 `lease_expires_at`；阶段进度在短事务中提交。成功后文档/向量/资源/任务状态按顺序落地；失败保留可重试的原件，取消或去重会释放无引用对象。同步兼容 API 若中途失败会回滚文档、向量、资源和无引用对象。

当前工作进程是单实例执行器，不应让多个应用实例共享同一 SQLite 文件消费任务。多节点需要外部队列/Postgres 原子认领，并针对重复投递重新验证幂等。

## 会话边界

新 SSE 会话事实保存在 `conversations` 与 `conversation_messages`。上下文默认最多最近六轮、约 12,000 字符；只有明确指代型追问才将最近问题用于检索改写，独立新问题不会继承旧主题词。流式开始先写空助手消息，完成后原位更新为最终响应；客户端断开则标记 `cancelled`，异常标记 `failed`。旧 `history` API 保留兼容，不作为新会话上下文来源。

## 生产数据平面与迁移顺序

1. `scripts/migrate_sqlite_to_postgres.py --dry-run` 读取一致性快照，校验目标结构定义和对象清单。
2. 正式迁移在单个 PostgreSQL 事务中保留 ID、时间戳和关联关系；失败回滚，不修改源 SQLite。
3. 按表比对行数和规范化 SHA-256，再校验对象大小/哈希、知识库边界与随机引用跳转。
4. S3 对象使用内容哈希键，只有暂存对象通过 ClamAV 后才进入 `available`；删除级联原件、派生资源、元素、分块、向量和图谱。
5. 事务发件箱调度器将任务投递到 Redis Streams 消费组；工作进程用幂等提交、租约、指数退避和死信队列处理重复投递与崩溃恢复。
6. pgvector 集合/表校验嵌入模型、维度与索引版本；不兼容索引必须重建，不能混读。
7. 切换前执行 `verify:production`、备份恢复和计数/哈希对账；保留 SQLite 只读备份直到回滚窗口结束。

升级和回滚细节见[本地生产候选版运行手册](production-local.md)和[耐久本地版 0.2](durable-local-0.2.md)，生产职责见[生产适配方案](production-adapters.md)。
