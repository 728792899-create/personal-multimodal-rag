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

Example DSNs:

```text
postgresql://rag:<password>@postgres:5432/personal_rag
redis://:<password>@redis:6379/0
```

Generate the administrator hash with:

```bash
python scripts/hash_admin_password.py > secrets/admin_password_hash
```

Never commit generated values.
