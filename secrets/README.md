# 生产密钥

`compose.production.yml` 从此目录中的文件读取密钥。仅提交此 README。
请在本地创建以下权限为 `0600` 的文件：

- `postgres_password`
- `metadata_dsn`
- `redis_password`
- `redis_url`
- `s3_access_key`
- `s3_secret_key`
- `admin_password_hash`
- `session_secret`
- `grafana_admin_user`
- `grafana_admin_password`

DSN 示例：

```text
postgresql://rag:<password>@postgres:5432/personal_rag
redis://:<password>@redis:6379/0
```

使用以下命令生成管理员哈希：

```bash
python scripts/hash_admin_password.py > secrets/admin_password_hash
printf '%s' 'admin' > secrets/grafana_admin_user
python -c 'import secrets; print(secrets.token_urlsafe(32), end="")' > secrets/grafana_admin_password
chmod 0600 secrets/*
```

为 PostgreSQL、Redis、S3、会话密钥和 Grafana 使用不同的随机值。绝不提交生成的值，也不要将其粘贴到公开议题或 CI 日志中。
