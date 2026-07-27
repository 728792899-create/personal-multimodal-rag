# 运维手册

本手册面向本地候选版和小团队试运行。它描述“出问题时先做什么”，不假设已经部署 Kubernetes、外部数据库或统一可观测平台。

![从本地演示到小团队候选版](assets/deployment-modes.svg)

## 服务边界

| 组件 | 默认端口 | 健康检查 | 持久数据 |
| --- | ---: | --- | --- |
| FastAPI 后端 | 8010 | `/health`、`/ready` | `data/registry.sqlite3`、`data/uploads` |
| 本地索引工作进程 | 后端生命周期 | `/api/index-jobs` + 队列指标 | SQLite 任务状态、`data/ingestions` 暂存 |
| Nginx 前端 | 5173 → 8080 | `/healthz` | 无 |
| 内存向量库 | 进程内 | `/ready` 模型提供方摘要 | 无；启动时补建 |
| Chroma / pgvector | 可选 | 模型提供方相关 | 外部或挂载路径 |

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

`/health` 只说明进程响应；`/ready` 同时暴露实际模型提供方配置。看到 `mock / memory / template` 代表离线模式，不是配置失败。

## 日常观察

### 建议指标

- HTTP 请求量、错误率、p50/p95 延迟与 429；
- 队列深度、任务阶段耗时、失败/重试/取消、过期租约恢复；
- 检索零命中、回退、拒答与候选数分布；
- 引用数量、覆盖率和无依据声明分布；
- 模型提供方超时、配额、费用和降级次数；
- 首个令牌延迟、流式取消、模型提供方错误、索引版本不匹配；
- 文档、分块、反馈与评测草稿数量。

`/api/metrics` 是产品内质量摘要；根路径 `/metrics` 是 Prometheus 指标暴露端点。可选可观测性配置提供 Prometheus、OTLP Collector 与预配置 Grafana。路径标签会把资源 ID 规范化为 `:id`，且不包含查询参数；问题、正文、Cookie、密钥和私有 URL 参数不得成为标签或追踪属性。

### 安全日志原则

- 使用请求 ID 关联前后端错误。
- 不记录 Authorization、API Key、密码、密钥。
- URL 日志去掉凭据、查询参数与片段。
- 不把完整问题、回答、文档正文发送到公共日志或 Sentry。
- 操作事件记录类型、状态、文件安全名与统计，不记录原始隐私内容。

## 备份与恢复

### 本地候选版

停写后备份整个 `data/` 目录：

```bash
docker compose down
tar -czf personal-rag-data-backup.tgz data/
```

不要把备份提交到 Git。备份可能包含上传文件和问答历史，应加密、限权并设置保留期。

恢复流程：

1. 在隔离目录验证归档完整性。
2. 停止服务并备份当前 `data/`。
3. 恢复注册表与上传文件。
4. 启动服务，内存向量库会补建缺失索引。
5. 检查文档数、分块数、代表性问答和引用。
6. 对 Chroma/pgvector 使用各自一致性快照，不要只恢复 SQLite。

解包备份后、切换服务前，先在隔离临时目录运行可重复检查：

```bash
python3 scripts/verify_local_restore.py \
  --database /path/to/restored/data/registry.sqlite3 \
  --objects /path/to/restored/data/objects \
  --expected-schema 7
```

命令使用 SQLite Backup API 再创建一次临时一致快照，并用 `PRAGMA query_only=ON` 禁止对输入数据库执行 SQL 写入；它验证 `integrity_check`、外键、架构，并只复制数据库引用的对象，核对安全路径、字节数和 SHA-256。输出不包含原始文件名、对象键、问题或正文。任何失败都应阻止切换，先修复或选择另一份备份。该命令不验证 Chroma/pgvector，也不能代替旧应用版本的抽样问答。

### 生产候选版

备份必须覆盖数据库、对象存储、向量索引版本、迁移版本和密钥配置引用。Redis 不是事实来源，恢复后由 PostgreSQL 发件箱重建待投递任务。

```bash
RAG_BACKUP_OUTPUT=/secure/backups/$(date +%F) npm run backup:production
RAG_BACKUP_BUNDLE=/secure/backups/2026-07-23 npm run restore:production -- --verify-only
RAG_BACKUP_BUNDLE=/secure/backups/2026-07-23 npm run restore:production -- --confirm RESTORE
```

备份命令先读取就绪状态，再短暂停止前端/后端/工作进程，避免 PostgreSQL 导出与 S3 对象归档期间继续写入；数据库、Redis、MinIO 保持运行，完成或失败后都会尝试恢复应用服务。对象通过 boto3 逐个流入 tar，不依赖 MinIO Server 镜像中并不存在的 `tar` 命令。清单记录 PostgreSQL 导出、MinIO 归档和解析后 Compose 配置的字节数与 SHA-256。恢复默认只允许 `--verify-only`；替换目标数据必须输入字面确认。恢复后重新检查 `/ready`、对象哈希、表计数、向量维度、索引版本和随机引用跳转。至少每季度演练一次，并记录 RPO/RTO 的真实结果。

## 常见事件

### 前端 502/504

1. `curl http://127.0.0.1:8010/ready`。
2. `docker compose ps` 检查后端是否健康。
3. `docker compose logs --since=10m backend`，按请求 ID 定位。
4. 服务恢复后使用界面原操作的“重试”；不要重复上传未知状态的大文件。

### 文档存在但搜索为空

1. 查看文档 `index_status` 和 `/api/operations`。
2. 确认 `DOCUMENT_REGISTRY_PATH` 指向当前数据卷。
3. 检查选中的知识库；知识库隔离发生在文档过滤和 BM25/向量检索之前。
4. 内存模式重启后等待启动补建。
5. 使用单文档重建；确认后再全量重建。
6. 若显示 `needs_rebuild` 或维度不匹配，创建匹配版本的集合/表并重建，不要清空唯一副本。

### 索引任务停滞或失败

1. `curl http://127.0.0.1:8010/api/index-jobs`，记录任务 ID、状态、阶段、尝试次数和请求 ID；响应不会暴露暂存路径或原始 URL 负载。
2. `running` 在租约过期后会重新排队；不要同时启动多个进程共享一个 SQLite 工作进程。
3. `failed`/`cancelled` 使用 `POST /api/index-jobs/{id}/retry`；其他状态返回 `409`。
4. `DELETE /api/index-jobs/{id}` 请求协作取消；解析不可中断时会在下一阶段边界清理。
5. 三次自动尝试后仍失败，先修复解析器/模型提供方/磁盘原因再人工重试；不要无限重试损坏文件。
6. 数据库升级或恢复流程见[持久本地版 0.2](durable-local-0.2.md)。

### URL 导入异常增多

1. 按拒绝原因区分超时、内容类型、大小、DNS 和私网地址。
2. 不要为了恢复成功率全局打开 `RAG_ALLOW_PRIVATE_URLS`。
3. 生产配置已强制使用隔离 `fetch-worker`；检查其健康、DNS 固定/跳转重校验和响应大小限制，不要让 API 容器直接抓取。
4. 检查目标站点 robots/使用条款和访问频率。

### 拒答率突然变化

1. 检查是否更换嵌入模型、维度、重排器或阈值。
2. 比较最近黄金集报告和案例明细。
3. 按类别分析，而不是只看总平均。
4. 抽样检查资料范围和索引状态。
5. 需要回滚时同时回滚索引版本和配置。

### 模型提供方不可用

1. 从 `/api/providers/status`、`/ready` 和检索追踪确认实际模型提供方；生产模式的 `degraded`/`503` 不会静默伪装为模板成功。
2. 检查超时、配额和端点，不在日志粘贴密钥。
3. 在隔离维护窗口显式切换 `ANSWER_PROVIDER=template` 验证核心检索；不要把这当生产模式自动回退。
4. 嵌入模型提供方故障期间停止写入新索引，避免混合版本。
5. 服务恢复后对失败文档执行幂等重建。

## 删除与数据生命周期

当前删除会移除注册表记录、向量分块和由应用管理的上传文件。生产异步架构应使用 `deleting` 状态，确保对象、派生 OCR、分块、向量、缓存和备份保留策略一致。

对于合规删除：

- 保存不含原文的审计事件；
- 明确备份中过期数据何时真正消失；
- 验证检索、历史、知识卡片和评测草稿没有残留非预期快照；
- 不接受客户端自行声明工作区作为授权依据。

## 发布与回滚

发布前执行[发布检查清单](release-checklist.md)。最小流程：

```bash
npm run verify
docker compose up --build --wait -d
curl --fail http://127.0.0.1:5173/api/documents
```

生产镜像使用不可变标签/摘要。数据库迁移采用向前兼容顺序：先部署兼容架构，再部署应用，再清理旧字段。索引版本升级先回填、评测、切换，保留旧索引直至观察窗口结束。

## 升级到 1.0 / 小团队版本前

- OIDC/OAuth2 身份网关与服务端工作区上下文；
- 运行真实语料基准、14 天稳定性运行和完整恢复/故障注入；
- Redis 或网关分布式限流；
- 容量、故障注入、备份恢复与删除演练。

详细目标结构见[生产适配方案](production-adapters.md)。
