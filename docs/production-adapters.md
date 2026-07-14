# 生产适配方案

本文件区分“Beta 已实现的边界”和“需要外部基础设施后才能完成的部署工作”。没有外部服务时，默认本地 Demo 始终可运行。

## 能力矩阵

| 关注点 | 本地 Beta | 生产建议 | 状态 |
| --- | --- | --- | --- |
| 身份 | 可选 Bearer token | OIDC/OAuth2 网关 + 短期会话 | 网关未部署 |
| 工作区 | 多 KB 数据范围；无授权租户 | `workspace_id` 贯穿 KB/document/chunk/conversation/job/eval，服务端强制过滤 | 需 schema/认证迁移 |
| 索引任务 | SQLite 事实源 + 单实例 worker + lease/retry/cancel | 外部队列 + 幂等 worker + retry/DLQ | 本地已实现；外部队列未部署 |
| 向量 | memory / 可选 Chroma/pgvector adapter | pgvector + 维度/模型版本分区 | adapter 已有，外部库未验收 |
| 文件 | 本地 `data/uploads` | S3-compatible object store + presigned upload + AV scan | 未部署对象存储 |
| 限流 | 单进程滑动窗口 | Redis/网关按 user/workspace 限流 | 未部署 Redis |
| 可观测性 | request ID、操作日志、metrics API | OpenTelemetry + Sentry + metrics backend | Sentry hook 可选，项目未连接 |

## 认证与工作区边界

推荐让身份网关验证用户，并向后端传递经过签名/可信网络保护的 `sub` 与 workspace claims。不要接受浏览器自行声明 `workspace_id`。

最小生产 schema：

```text
workspaces(id, name, created_at)
memberships(workspace_id, user_id, role)
knowledge_bases(id, workspace_id, ...)
documents(id, workspace_id, knowledge_base_id, object_key, content_hash, status, ...)
chunks(id, workspace_id, document_id, embedding_model, ...)
conversations/messages(id, workspace_id, user_id, ...)
index_jobs(id, workspace_id, idempotency_key, lease, ...)
eval_cases(id, workspace_id, ...)
```

每个 repository/service 方法都必须接收服务端解析出的 workspace context；数据库查询和对象 key 同时限定 workspace。PostgreSQL 可再加 RLS 作为纵深防御。

内置 `API_AUTH_TOKEN` 适合单用户 API 或由可信反向代理注入的共享边界，不解决用户身份、角色、撤销和审计问题，也不应通过 `VITE_*` 打进浏览器 bundle。

## 后台索引任务

生产上传应分为：

```mermaid
flowchart LR
  U["Upload"] --> O["Object Store"]
  O --> D["Document row: queued"]
  D --> Q["Queue"]
  Q --> W["Idempotent worker"]
  W --> P["Parse / OCR / Chunk"]
  P --> V["pgvector upsert"]
  V --> S["status=indexed"]
  W -->|"retry exhausted"| DLQ["DLQ + alert"]
```

0.2 已使用 `knowledge_base + content/url hash + embedding/index/chunker version` 生成本地幂等键，并公开稳定任务状态机。迁出时在键中增加服务端 workspace；删除流程先把文档标为 deleting，再异步删除向量和对象，最终写审计事件；worker 必须能安全处理重复投递。

## pgvector

1. 安装 `backend/requirements-optional.txt` 中的 `psycopg`/`pgvector`。
2. 创建独立数据库用户与受限 schema，不使用超级用户连接应用。
3. 配置 `VECTOR_STORE=pgvector`、`PGVECTOR_DSN`、表名与 embedding dimension。
4. 为 `workspace_id`、`document_id` 和向量索引建立迁移；当前 Beta adapter 创建的是单表基础结构，真正多 workspace 前必须迁移。
5. embedding 模型或维度变化时写入新版本/新表，完成回填后切换，不原地混用维度。

## 对象存储

- 原始文件使用不可预测 object key，不把用户文件名当 key。
- 上传设置 MIME/大小限制、校验 hash、病毒扫描和生命周期策略。
- 数据库只保存 object key 与安全 metadata；下载用短期签名 URL。
- 删除与备份恢复必须覆盖原始对象、派生 OCR、chunk 和向量。

## 可观测性

已提供 request ID、脱敏日志、操作事件、`/metrics` 业务摘要和可选 Sentry 初始化。生产还应补：

- HTTP/索引任务 latency、error、retry、queue depth；
- 检索 zero-hit、fallback、refusal、citation coverage 分布；
- embedding/rerank provider cost 与限额；
- workspace 级别配额，但日志不记录原文、Key、完整 URL query；
- Sentry scrubber 与低采样 tracing，验证事件不带 document text。

## 人工部署步骤

由于仓库没有云账号、域名、OIDC tenant、Postgres/S3/Redis/Sentry 凭据，以下必须由部署负责人完成：创建服务、写入 secret manager、运行迁移、配置 TLS/域名、验证备份恢复、执行容量测试、设置告警和回滚策略。
