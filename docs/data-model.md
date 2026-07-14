# SQLite 数据模型与生产迁移边界

当前 Beta 用 SQLite 保存可恢复的 registry 数据，用 vector store 保存 chunk 与向量。这个设计让单实例离线 Demo 易于审查和重启恢复，但它不是多 workspace 的最终 schema。

![六张 SQLite 表、chunk 向量存储及生产 workspace 迁移边界](assets/data-model.svg)

## 当前实际 schema

schema 由 `backend/app/services/document_registry.py` 在启动时创建，共六张表：

| 表 | 主键 | 可查询列 | JSON payload 主要内容 |
| --- | --- | --- | --- |
| `documents` | `document_id` | — | 文件名、页面、metadata、索引/质量状态、生命周期 |
| `history` | `history_id` | question、answer、created_at | citations、retrieval/generation trace、confidence |
| `feedback` | `feedback_id` | history_id、rating、failure_type、created_at | history snapshot、备注、自动 eval case |
| `operation_logs` | `operation_id` | event_type、level、created_at | 脱敏消息与事件 payload |
| `knowledge_cards` | `card_id` | title、created_at | 问题、答案、引用、标签和来源 |
| `eval_cases` | `case_id` | question、created_at | expected keywords/answer、note、draft status |

`feedback.history_id` 是逻辑引用，当前没有 SQLite foreign key 约束。这样允许保留反馈快照，即使历史被清空；代价是应用层必须明确孤立记录语义。

## Chunk 与向量不在 registry 表中

文档内容先被切为 chunk，再写入 vector store adapter：

- `memory`：进程内保存 chunk 和向量；重启后为空。
- `chroma`：可选持久 adapter。
- `pgvector`：可选 Postgres adapter，表结构由 vector store 实现维护。

启动 hydration 先加载 SQLite `documents`，检查 store 已有 chunk，只为缺失文档重建索引。因而 memory 能从 registry 恢复，持久 store 不应重复 embedding 已存在 chunk。

## 写入与删除一致性

### 入库

文件/URL 解析成功后计算内容哈希并去重，再写入检索索引和 registry。文档 payload 包含可用于重建的文本和 metadata；上传文件只有在完整成功后才被保留。

### 删除

删除按顺序移除 retriever 中的文档 chunk、SQLite document 记录，并尝试删除受控 upload 根目录中的源文件。系统不会删除 upload 根目录外的路径。当前删除不级联历史、反馈或知识卡，因为它们承担审计快照角色。

### 历史与反馈

清空 history 不清理 feedback。负反馈保存提交时的 history snapshot，避免后续历史变化让 eval draft 失去上下文。需要提供“彻底删除个人数据”能力时，必须新增明确的保留策略和级联作业。

## 当前边界

- JSON payload 便于 Beta 演进，但不适合复杂跨记录分析或数据库级约束。
- 单 SQLite 文件和进程内连接不提供高并发写入、租户隔离或在线 schema migration。
- 文档去重按全 registry 内容哈希执行；在多 workspace 场景必须改为 workspace 范围。
- operation log 是产品内可见的轻量审计，不是不可篡改合规日志。
- 本地源文件缺少对象版本、生命周期策略和独立备份。

## 生产迁移建议

不要直接把 SQLite 文件替换成一个共享 Postgres DSN。推荐按以下顺序迁移：

1. 建立 `workspaces`、`users`、`memberships` 与服务端授权模型。
2. 为 documents、chunks、history、feedback、cards、eval cases 和 operations 增加不可为空的 `workspace_id`。
3. 把高频过滤字段从 JSON 提升为类型化列，保留 versioned metadata JSON 处理长尾。
4. 使用 Postgres migration 工具管理 schema；为 workspace + created_at、content_hash、source 等建立组合索引。
5. 将 chunk、embedding model、dimensions、content hash 和 document version 写入 pgvector 表；切换模型时使用新版本索引而非原地覆盖。
6. 将源文件放入私有对象存储，记录 object key、etag、size、content type 和保留状态；下载使用短期授权 URL。
7. 用后台任务完成解析/索引/删除，任务必须幂等、可重试、可取消，并有死信与状态审计。
8. 在双写或离线迁移验证后切读，核对文档数、chunk 数、哈希、抽样检索和删除结果，再停止 SQLite 写入。

生产适配的服务职责与验收步骤见[生产适配方案](production-adapters.md)，威胁边界见[安全模型](security-model.md)。
