# Production Local 0.4 RC 运行手册

`0.4.0-rc.1` 提供三个互不混淆的运行 profile。`demo` 用于零 Key 验证产品链路；`local-production` 用于一台可信主机上的个人知识库；`production` 用于把 metadata、向量、对象和任务队列交给独立持久服务。RC 尚未宣称 production-ready。

## 选择模式

| 模式 | 适用场景 | 必需依赖 | 失败行为 |
| --- | --- | --- | --- |
| Demo | 评审、开发、离线测试 | Docker，或 Python + Node | 允许 deterministic template |
| Local Production | 单用户长期私有使用 | Ollama、持久磁盘 | Ollama/Chroma 异常时 readiness 失败 |
| Production | 独立 worker 与外部数据服务 | PostgreSQL/pgvector、Redis、S3/MinIO、ClamAV、Ollama 或 OpenAI-compatible | 任一关键依赖异常时 HTTP 503，不降级为 template |

`GET /api/system/readiness-report` 返回配置状态、组件健康状态、schema 版本和仍未完成的 1.0 发布门槛。`GET /ready` 只在必要组件可用时返回 200；降级状态返回 503，供 Compose 和反向代理摘除实例。

## Local Production

先安装并启动 Ollama，然后拉取所需模型：

```bash
ollama pull qwen3:8b
ollama pull nomic-embed-text
docker compose -f docker-compose.yml -f compose.local-production.yml up --build --wait -d
```

默认使用 SQLite、本地内容寻址对象存储、Chroma、cross-encoder rerank 和独立持久 volume，不连接任何付费 API。首次启动会把 cross-encoder 权重下载到该 volume；之后可离线复用。若启用 `AUTH_MODE=session`，必须同时设置稳定的 `ADMIN_PASSWORD_HASH` 与至少 32 字符的 `SESSION_SECRET`；否则配置验证会拒绝启动。

## Production secrets

复制 [secrets/README.md](../secrets/README.md) 中列出的文件名并设置 `0600`。管理员密码 hash 通过交互命令生成：

```bash
python scripts/hash_admin_password.py > secrets/admin_password_hash
```

至少需要：

- PostgreSQL 密码和 metadata DSN；
- Redis 密码和带密码 URL；
- MinIO/S3 access key 与 secret key；
- Argon2id 管理员密码 hash；
- 随机、稳定、至少 32 字符的 session secret。

启动：

```bash
docker compose -f compose.production.yml config --quiet
docker compose -f compose.production.yml up --build --wait -d
curl --fail http://127.0.0.1:5173/healthz
curl --fail http://127.0.0.1:5173/api/system/readiness-report
```

容器以非 root/read-only 配置运行；上传对象先经过 ClamAV，再以 SHA-256 内容地址写入 S3。索引任务先与 PostgreSQL outbox 原子提交，再投递到 Redis Streams consumer group；重复消息仍由数据库幂等键保护，终态失败进入 DLQ。

## SQLite → PostgreSQL

先停止写流量并做 dry run：

```bash
python scripts/migrate_registry_to_postgres.py \
  --sqlite data/registry.sqlite3 \
  --postgres-dsn "$METADATA_DSN" \
  --dry-run
```

正式执行会先复制一份带时间戳的 SQLite 备份，然后在一个 PostgreSQL 事务中按依赖顺序 upsert。每张表会按主键重新读取并比较 SHA-256 checksum；任一复制或校验失败都会回滚本次导入。

对象文件不由 metadata CLI 自动上传。切换前必须把 `data/objects/` 按原有内容地址同步到目标 bucket，并对照 `assets.object_key`、`assets.sha256` 和 `assets.size_bytes` 校验。完成后再切换 metadata DSN。

## 回滚

1. 停止 API 与 worker。
2. 保留 PostgreSQL、Redis 与对象 bucket，不立即删除。
3. 恢复迁移命令产生的 `.pre-postgres-*.bak`。
4. 把 runtime profile 切回 `demo` 或 `local-production`，确认 `GET /ready` 为 200。
5. 抽查文档数量、对象 SHA-256、向量维度/索引版本和引用跳转。

## 当前 RC 边界

- 生产 Compose 只提供单实例拓扑，没有 Kubernetes、高可用、OIDC 或团队 RBAC。
- OpenAI-compatible、真实 Ollama、外部 S3 和 Sentry 需要部署方在自己的环境执行在线验收；CI 不使用付费 API。
- 1.0 仍要求至少 14 天真实部署、200 份非 fixture 文档、100 次真实问题和一次无数据丢失的完整恢复演练。
