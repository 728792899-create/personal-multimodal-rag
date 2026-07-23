# Production secrets

`compose.production.yml` reads secrets from files in this directory. Only this
README is committed. Create the following files locally with mode `0600`:

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

Example DSNs:

```text
postgresql://rag:<password>@postgres:5432/personal_rag
redis://:<password>@redis:6379/0
```

Generate the administrator hash with:

```bash
python scripts/hash_admin_password.py > secrets/admin_password_hash
printf '%s' 'admin' > secrets/grafana_admin_user
python -c 'import secrets; print(secrets.token_urlsafe(32), end="")' > secrets/grafana_admin_password
chmod 0600 secrets/*
```

Use distinct random values for PostgreSQL, Redis, S3, the session secret and
Grafana. Never commit generated values or paste them into issue/CI logs.
