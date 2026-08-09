#!/usr/bin/env python3
"""当生产 Compose 契约破坏安全边界时让 CI 失败。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def main() -> int:
    compose_file = Path("compose.production.yml")
    result = subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "config", "--format", "json"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    config = json.loads(result.stdout)
    services = config["services"]
    required = {"postgres", "redis", "minio", "clamav", "fetch-worker", "backend", "worker", "frontend"}
    missing = sorted(required - set(services))
    if missing:
        raise SystemExit(f"生产 Compose 缺少服务：{', '.join(missing)}")
    for name in ("fetch-worker", "backend", "worker", "frontend"):
        service = services[name]
        if not service.get("read_only"):
            raise SystemExit(f"{name} 必须使用只读根文件系统")
        if "ALL" not in service.get("cap_drop", []):
            raise SystemExit(f"{name} 必须移除所有 Linux capabilities")
        if "no-new-privileges:true" not in service.get("security_opt", []):
            raise SystemExit(f"{name} 必须设置 no-new-privileges")
    worker_healthcheck = json.dumps(services["worker"].get("healthcheck", {}))
    if "worker-heartbeat" not in worker_healthcheck:
        raise SystemExit("worker healthcheck 必须验证 ingestion-loop 心跳")
    environment = services["backend"].get("environment", {})
    expected = {
        "RAG_RUNTIME_MODE": "production",
        "APP_ENVIRONMENT": "production",
        "PROVIDER_FALLBACK_ALLOWED": "0",
        "AUTH_MODE": "session",
        "METADATA_BACKEND": "postgres",
        "OBJECT_STORE_BACKEND": "s3",
        "JOB_QUEUE_BACKEND": "redis",
        "FETCH_WORKER_URL": "http://fetch-worker:8091",
        "VECTOR_STORE": "pgvector",
        "EMBEDDING_PROVIDER": "openai",
        "EMBEDDING_MODEL": "text-embedding-3-large",
        "EMBEDDING_DIMENSION": "1536",
        "OPENAI_API_KEY_FILE": "/run/secrets/openai_api_key",
        "ANSWER_PROVIDER": "openai_compatible_chat",
        "ANSWER_BASE_URL": "https://api.deepseek.com",
        "ANSWER_API_KEY_FILE": "/run/secrets/deepseek_api_key",
        "RERANKER": "deepseek",
        "RETRIEVAL_AUX_PROVIDER": "deepseek",
        "RETRIEVAL_AUX_API_KEY_FILE": "/run/secrets/deepseek_api_key",
        "QUERY_REWRITE_PROVIDER": "deepseek",
    }
    for key, value in expected.items():
        if str(environment.get(key)) != value:
            raise SystemExit(f"backend 生产契约要求 {key}={value}")
    forbidden_direct_secrets = {
        "OPENAI_API_KEY",
        "ANSWER_API_KEY",
        "RETRIEVAL_AUX_API_KEY",
        "QUERY_REWRITE_API_KEY",
        "ENRICHMENT_API_KEY",
    }
    exposed = sorted(
        key for key in forbidden_direct_secrets if environment.get(key)
    )
    if exposed:
        raise SystemExit(
            "backend 生产环境禁止直接注入模型密钥：" + ", ".join(exposed)
        )
    postgres_image = str(services["postgres"].get("image") or "")
    if not postgres_image.startswith("pgvector/pgvector:0.8."):
        raise SystemExit("postgres 必须使用 pgvector >= 0.8 的固定版本镜像")
    for name, service in services.items():
        image = str(service.get("image") or "")
        if image.endswith(":latest"):
            raise SystemExit(f"{name} 使用了可变的 latest tag")
    postgres_mounts = services["postgres"].get("volumes", [])
    if not any(
        str(mount.get("target") or "")
        == "/docker-entrypoint-initdb.d/001-pgvector.sql"
        and bool(mount.get("read_only"))
        for mount in postgres_mounts
        if isinstance(mount, dict)
    ):
        raise SystemExit("postgres 必须通过只读脚本初始化 vector extension")
    nginx = Path("frontend/nginx.conf").read_text(encoding="utf-8")
    if "location = /ready" not in nginx or "$backend_upstream/ready" not in nginx:
        raise SystemExit("frontend 必须将公开 readiness endpoint 代理到 backend")
    if (
        "resolver 127.0.0.11" not in nginx
        or "set $backend_upstream backend:8010;" not in nginx
        or "proxy_pass http://$backend_upstream" not in nginx
    ):
        raise SystemExit(
            "容器恢复后，frontend 必须在请求时动态解析 backend"
        )
    print("Production Compose 契约检查通过：配置 fail-closed、镜像版本固定、应用容器只读。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
