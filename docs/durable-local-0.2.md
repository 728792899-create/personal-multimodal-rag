# Durable Local 0.2：迁移、恢复与回滚

0.2 面向单用户/小团队的**单实例**运行：SQLite 同时保存业务数据、知识库、会话和索引任务；本地 worker 负责可恢复入库；检索向量仍由 memory、Chroma 或 pgvector adapter 管理。它提升了本地耐久性，但不构成多租户或多节点队列。

## 升级时发生什么

`DocumentRegistry` 启动时按 `schema_migrations` 顺序执行幂等迁移，当前 schema version 为 3：

1. 建立原有 documents/history/feedback/operation/cards/eval 数据结构。
2. 建立 `knowledge_bases`、默认知识库并无损回填现有文档。
3. 建立 `conversations`、`conversation_messages`、`index_jobs`，补齐文档的 content hash、chunker/embedding/index metadata。

文件数据库升级前会在同目录生成时间戳备份；`:memory:` 测试数据库不备份。迁移失败时初始化失败，写服务不会在半迁移 schema 上继续运行。

## 索引兼容规则

文档记录携带：

- `chunker_version`
- `embedding_provider`、`embedding_model`、`embedding_dimension`
- `index_version`

启动 hydration 会比较当前配置。模型、维度或索引版本不兼容时，文档状态改为 `needs_rebuild`，不会把旧向量装入当前检索器。Chroma collection 也保存维度/版本 metadata，并在写入前校验向量维度。

推荐升级流程：

```bash
cp data/registry.sqlite3 data/registry.manual-backup.sqlite3
docker compose up --build --wait -d
curl --fail http://127.0.0.1:8010/ready
curl --fail http://127.0.0.1:8010/api/documents
npm run eval:retrieval
```

如果出现 `needs_rebuild`，先在 UI 或 API 发起重建，等任务成功后再切换日常使用。不要通过修改数据库 metadata 强行兼容不同维度。

## 本地任务语义

任务的正常路径是 `queued → running → succeeded`；失败/取消分支是 `failed`、`cancelling`、`cancelled`。阶段为校验、解析/OCR、分块、嵌入、写入、质量分析和完成。

- SQLite 是任务事实来源，前端轮询只是视图。
- worker claim 时写入租约；进程中断后，过期租约任务可重新领取。
- 自动尝试最多三次；之后保留脱敏错误，用户可显式 retry。
- 幂等键由知识库、内容/URL hash、chunker、embedding 和 index version 组成。
- 取消是阶段间协作式取消；不可中断的 parser 返回后会丢弃结果并清理暂存文件。
- 同一 SQLite 文件只应由一个 0.2 worker 实例消费；多实例必须迁移到带原子 claim 的外部任务系统并重新验证。

## 回滚

代码回滚和数据回滚必须一起规划：

1. 停止前后端，确认没有 `running`/`cancelling` 任务。
2. 复制当前数据库和 `data/uploads` 作为事故快照。
3. 恢复升级前自动备份或人工备份；不要让旧代码打开已经迁移并继续写入的数据库。
4. 恢复匹配版本的 vector store；memory 模式会从恢复后的 registry 重建。
5. 启动旧版本并执行 `/ready`、文档数核对、抽样问答与删除检查。

迁移是 additive 的，但旧版本不了解知识库、会话和任务表；仅回滚 Git commit 而保留新数据库会丢失新功能语义。

## 从本地 worker 迁出

生产多实例推荐保留公开 `IndexJob` 状态机和幂等键，替换执行层：API 写任务 → 外部队列 → 独立 worker → Postgres 状态/租约 → 对象存储 → versioned pgvector。迁移验收至少核对任务数、文档 hash、chunk 数、向量维度、删除级联和 40 条固定回归集。

更完整的 workspace、对象存储和权限边界见[生产适配方案](production-adapters.md)，故障操作见[运维手册](operations-runbook.md)。
