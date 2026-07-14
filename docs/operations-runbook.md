# 运维手册

本手册面向本地 Beta 和小团队试运行。它描述“出问题时先做什么”，不假设已经部署 Kubernetes、外部数据库或统一可观测平台。

![从本地演示到小团队 Beta](assets/deployment-modes.svg)

## 服务边界

| 组件 | 默认端口 | 健康检查 | 持久数据 |
| --- | ---: | --- | --- |
| FastAPI backend | 8010 | `/health`、`/ready` | `data/registry.sqlite3`、`data/uploads` |
| Local index worker | backend lifespan | `/api/index-jobs` + queue metrics | SQLite job state、`data/ingestions` 暂存 |
| Nginx frontend | 5173 → 8080 | `/healthz` | 无 |
| Memory vector store | 进程内 | `/ready` provider 摘要 | 无；启动时补建 |
| Chroma / pgvector | 可选 | provider 相关 | 外部或挂载路径 |

## 启动前检查

```bash
git status --short
docker compose config
docker compose build
docker compose up --wait -d
docker compose ps
curl --fail http://127.0.0.1:8010/ready
curl --fail http://127.0.0.1:5173/healthz
curl --fail http://127.0.0.1:5173/api/documents
```

`/health` 只说明进程响应；`/ready` 同时暴露实际 provider 配置。看到 `mock / memory / template` 代表离线模式，不是配置失败。

## 日常观察

### 建议指标

- HTTP 请求量、错误率、p50/p95 延迟与 429；
- 队列深度、任务阶段耗时、失败/重试/取消、过期租约恢复；
- 检索 zero-hit、fallback、refusal 与候选数分布；
- 引用数量、覆盖率和 unsupported claim 分布；
- provider 超时、配额、费用和降级次数；
- 首 token 延迟、stream cancel、Provider error、index version mismatch；
- 文档、chunk、反馈与 eval draft 数量。

内置 `/api/metrics` 是 Beta 业务摘要，不是 Prometheus endpoint。生产环境应通过 OpenTelemetry/metrics backend 输出聚合指标，避免把原始问题或文档正文作为 label。

### 安全日志原则

- 使用 request ID 关联前后端错误。
- 不记录 Authorization、API Key、password、secret。
- URL 日志去掉 credentials、query 与 fragment。
- 不把完整问题、回答、文档正文发送到公共日志或 Sentry。
- 操作事件记录类型、状态、文件安全名与统计，不记录原始隐私内容。

## 备份与恢复

### 本地 Beta

停写后备份整个 `data/` 目录：

```bash
docker compose down
tar -czf personal-rag-data-backup.tgz data/
```

不要把备份提交到 Git。备份可能包含上传文件和问答历史，应加密、限权并设置保留期。

恢复流程：

1. 在隔离目录验证归档完整性。
2. 停止服务并备份当前 `data/`。
3. 恢复 registry 与 uploads。
4. 启动服务，memory store 会补建缺失索引。
5. 检查文档数、chunk 数、代表性问答和引用。
6. 对 Chroma/pgvector 使用各自一致性快照，不要只恢复 SQLite。

### 生产 Beta

备份必须覆盖数据库、对象存储、向量索引版本、迁移版本和 secret 配置引用。至少每季度演练一次恢复，并记录 RPO/RTO 的真实结果。

## 常见事件

### 前端 502/504

1. `curl http://127.0.0.1:8010/ready`。
2. `docker compose ps` 检查 backend 是否 healthy。
3. `docker compose logs --since=10m backend`，按请求 ID 定位。
4. 服务恢复后使用 UI 原操作的“重试”；不要重复上传未知状态的大文件。

### 文档存在但搜索为空

1. 查看文档 `index_status` 和 `/api/operations`。
2. 确认 `DOCUMENT_REGISTRY_PATH` 指向当前数据卷。
3. 检查选中的 knowledge base；KB 隔离发生在文档过滤和 BM25/vector 之前。
4. memory 模式重启后等待启动补建。
5. 使用单文档 rebuild；确认后再 rebuild-all。
6. 若显示 `needs_rebuild` 或 dimension mismatch，创建匹配版本 collection/table 并重建，不要清空唯一副本。

### 索引任务停滞或失败

1. `curl http://127.0.0.1:8010/api/index-jobs`，记录 job ID、status、stage、attempts 和 request ID；响应不会暴露暂存路径或原始 URL payload。
2. `running` 在租约过期后会重新排队；不要同时启动多个进程共享一个 SQLite worker。
3. `failed`/`cancelled` 使用 `POST /api/index-jobs/{id}/retry`；其他状态返回 `409`。
4. `DELETE /api/index-jobs/{id}` 请求协作取消；解析不可中断时会在下一阶段边界清理。
5. 三次自动尝试后仍失败，先修复 parser/provider/磁盘原因再人工 retry；不要无限重试损坏文件。
6. 数据库升级或恢复流程见[Durable Local 0.2](durable-local-0.2.md)。

### URL 导入异常增多

1. 按拒绝原因区分超时、内容类型、大小、DNS 和私网地址。
2. 不要为了恢复成功率全局打开 `RAG_ALLOW_PRIVATE_URLS`。
3. 高风险生产环境把抓取迁移到隔离 egress 服务，并固定解析结果与连接目标。
4. 检查目标站点 robots/使用条款和访问频率。

### 拒答率突然变化

1. 检查是否更换 embedding、维度、reranker 或阈值。
2. 比较最近黄金集报告和 case 明细。
3. 按 category 分析，而不是只看总平均。
4. 抽样检查资料范围和索引状态。
5. 需要回滚时同时回滚索引版本和配置。

### Provider 不可用

1. 从 `/api/providers/status`、`/ready` 和 Trace 确认实际 provider；production 的 `degraded`/`503` 不会静默伪装为模板成功。
2. 检查超时、配额和 endpoint，不在日志粘贴 Key。
3. 在隔离维护窗口显式切换 `ANSWER_PROVIDER=template` 验证核心检索；不要把这当 production 自动 fallback。
4. Embedding provider 故障期间停止写入新索引，避免混合版本。
5. 服务恢复后对失败文档执行幂等重建。

## 删除与数据生命周期

当前删除会移除 registry 记录、向量 chunk 和由应用管理的上传文件。生产异步架构应使用 `deleting` 状态，确保对象、派生 OCR、chunk、向量、缓存和备份保留策略一致。

对于合规删除：

- 保存不含原文的审计事件；
- 明确备份中过期数据何时真正消失；
- 验证检索、历史、知识卡片和评测草稿没有残留非预期快照；
- 不接受客户端自行声明 workspace 作为授权依据。

## 发布与回滚

发布前执行 [Release Checklist](release-checklist.md)。最小流程：

```bash
npm run verify
docker compose up --build --wait -d
curl --fail http://127.0.0.1:5173/api/documents
```

生产镜像使用不可变 tag/digest。数据库迁移采用向前兼容顺序：先部署兼容 schema，再部署应用，再清理旧字段。索引版本升级先回填、评测、切换，保留旧索引直至观察窗口结束。

## 升级到小团队 Beta 前

- OIDC/OAuth2 身份网关与服务端 workspace context；
- PostgreSQL schema、行级授权和迁移；
- S3-compatible 对象存储、AV 扫描和生命周期；
- 队列、幂等 worker、retry/DLQ；
- Redis 或网关分布式限流；
- Sentry scrubber、metrics、trace 和告警；
- 容量、故障注入、备份恢复与删除演练。

详细目标结构见[生产适配方案](production-adapters.md)。
