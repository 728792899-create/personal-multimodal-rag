# 本地生产候选版 0.4 运行手册

`0.4.0-rc.1` 提供三个互不混淆的运行配置。`demo` 用于零密钥验证产品链路；`local-production` 用于一台可信主机上的个人知识库；`production` 用于把元数据、向量、对象和任务队列交给独立持久服务。候选版尚未宣称已可生产使用。

## 选择模式

| 模式 | 适用场景 | 必需依赖 | 失败行为 |
| --- | --- | --- | --- |
| 演示 | 评审、开发、离线测试 | Docker，或 Python + Node | 允许确定性模板回答 |
| 本地生产 | 单用户长期私有使用 | Ollama、持久磁盘 | Ollama/Chroma 异常时就绪检查失败 |
| 生产 | 独立工作进程与外部数据服务 | PostgreSQL/pgvector、Redis、S3/MinIO、ClamAV、Ollama 或 OpenAI 兼容接口 | 任一关键依赖异常时 HTTP 503，不降级为模板回答 |

`GET /api/system/readiness-report` 返回配置状态、组件健康状态、schema 版本和逐项 1.0 发布门槛。证据文件缺失时 1.0 状态明确为 `blocked`。`GET /ready` 只在必要组件可用时返回 200；降级状态返回 503，供 Compose 和反向代理摘除实例。

## 本地生产

先安装并启动 Ollama，然后拉取所需模型：

```bash
ollama pull qwen3:8b
ollama pull nomic-embed-text
docker compose -f docker-compose.yml -f compose.local-production.yml up --build --wait -d
```

默认使用 SQLite、本地内容寻址对象存储、Chroma、交叉编码器重排和独立持久卷，不连接任何付费 API。首次启动会把交叉编码器权重下载到该持久卷；之后可离线复用。若启用 `AUTH_MODE=session`，必须同时设置稳定的 `ADMIN_PASSWORD_HASH` 与至少 32 字符的 `SESSION_SECRET`；否则配置验证会拒绝启动。

## 生产密钥

复制 [secrets/README.md](../secrets/README.md) 中列出的文件名并设置 `0600`。管理员密码哈希通过交互命令生成：

```bash
python scripts/hash_admin_password.py > secrets/admin_password_hash
```

至少需要：

- PostgreSQL 密码和元数据 DSN；
- Redis 密码和带密码 URL；
- MinIO/S3 访问密钥与密钥；
- Argon2id 管理员密码哈希；
- 随机、稳定、至少 32 字符的会话密钥。
- 启用可观测性配置时的 Grafana 管理员用户名与密码。

启动：

```bash
docker compose -f compose.production.yml config --quiet
docker compose -f compose.production.yml up --build --wait -d
curl --fail http://127.0.0.1:5173/healthz
curl --fail http://127.0.0.1:5173/api/system/readiness-report
```

容器以非 root/只读配置运行；上传对象先经过 ClamAV，再以 SHA-256 内容地址写入 S3。索引任务先与 PostgreSQL 事务发件箱原子提交，再投递到 Redis Streams 消费组；重复消息仍由数据库幂等键保护，终态失败进入死信队列。URL/订阅源抓取由独立 `fetch-worker` 完成：该容器没有应用密钥或数据卷，每一跳都重新校验地址并将连接固定到已验证的公网 IP。

可选启动 Prometheus、OpenTelemetry Collector 与预配置 Grafana：

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318/v1/traces \
docker compose -f compose.production.yml --profile observability up --build --wait -d
docker compose -f compose.production.yml exec -T backend \
  python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8010/metrics').status)"
```

Grafana 默认监听 `http://127.0.0.1:3000`，凭据从密钥文件读取。指标标签只包含方法、规范化路径、状态、模型提供方和任务类型；不得加入问题、正文、Cookie、密钥或 URL 查询参数。

## 生产验证命令

```bash
npm run verify:production
npm run benchmark:real        # 需要 RAG_REAL_BENCHMARK_MANIFEST
npm run chaos:compose         # 默认只输出演练模式计划
RAG_BACKUP_OUTPUT=/secure/backups/$(date +%F) npm run backup:production
RAG_BACKUP_BUNDLE=/secure/backups/2026-07-23 npm run restore:production -- --verify-only
```

真实故障注入还要求 `RAG_CHAOS_CONFIRM=I_UNDERSTAND` 与 `--execute`。真实恢复替换数据，必须显式传入 `--confirm RESTORE`。

## SQLite → PostgreSQL

先停止写流量并做演练模式迁移：

```bash
python scripts/migrate_registry_to_postgres.py \
  --sqlite data/registry.sqlite3 \
  --postgres-dsn "$METADATA_DSN" \
  --dry-run
```

正式执行会先复制一份带时间戳的 SQLite 备份，然后在一个 PostgreSQL 事务中按依赖顺序写入或更新。每张表会按主键重新读取并比较 SHA-256 校验和；任一复制或校验失败都会回滚本次导入。

对象文件不由元数据命令行工具自动上传。切换前必须把 `data/objects/` 按原有内容地址同步到目标存储桶，并对照 `assets.object_key`、`assets.sha256` 和 `assets.size_bytes` 校验。完成后再切换元数据 DSN。

## 回滚

1. 停止 API 与工作进程。
2. 保留 PostgreSQL、Redis 与对象存储桶，不立即删除。
3. 恢复迁移命令产生的 `.pre-postgres-*.bak`。
4. 把运行配置切回 `demo` 或 `local-production`，确认 `GET /ready` 为 200。
5. 抽查文档数量、对象 SHA-256、向量维度/索引版本和引用跳转。

## 当前 RC 边界

- 生产 Compose 只提供单实例拓扑，没有 Kubernetes、高可用、OIDC 或团队 RBAC。
- OpenAI 兼容接口、真实 Ollama、外部 S3 和 Sentry 需要部署方在自己的环境执行在线验收；CI 不使用付费 API。
- 1.0 仍要求至少 14 天真实部署、200 份非固定样例文档、100 次真实问题和一次无数据丢失的完整恢复演练。
- 机器可读门槛和当前阻断原因见[1.0 发布证据](release-evidence-1.0.md)。
