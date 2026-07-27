#!/usr/bin/env python3
"""Fail CI when the production Compose contract loses its security boundary."""

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
        raise SystemExit(f"production compose is missing services: {', '.join(missing)}")
    for name in ("fetch-worker", "backend", "worker", "frontend"):
        service = services[name]
        if not service.get("read_only"):
            raise SystemExit(f"{name} must use a read-only root filesystem")
        if "ALL" not in service.get("cap_drop", []):
            raise SystemExit(f"{name} must drop all Linux capabilities")
        if "no-new-privileges:true" not in service.get("security_opt", []):
            raise SystemExit(f"{name} must set no-new-privileges")
    worker_healthcheck = json.dumps(services["worker"].get("healthcheck", {}))
    if "worker-heartbeat" not in worker_healthcheck:
        raise SystemExit("worker healthcheck must validate its ingestion-loop heartbeat")
    environment = services["backend"].get("environment", {})
    expected = {
        "RAG_RUNTIME_MODE": "production",
        "PROVIDER_FALLBACK_ALLOWED": "0",
        "AUTH_MODE": "session",
        "METADATA_BACKEND": "postgres",
        "OBJECT_STORE_BACKEND": "s3",
        "JOB_QUEUE_BACKEND": "redis",
        "FETCH_WORKER_URL": "http://fetch-worker:8091",
    }
    for key, value in expected.items():
        if str(environment.get(key)) != value:
            raise SystemExit(f"backend production contract requires {key}={value}")
    for name, service in services.items():
        image = str(service.get("image") or "")
        if image.endswith(":latest"):
            raise SystemExit(f"{name} uses a mutable latest tag")
    postgres_mounts = services["postgres"].get("volumes", [])
    if not any(
        str(mount.get("target") or "")
        == "/docker-entrypoint-initdb.d/001-pgvector.sql"
        and bool(mount.get("read_only"))
        for mount in postgres_mounts
        if isinstance(mount, dict)
    ):
        raise SystemExit("postgres must initialize the vector extension from a read-only script")
    nginx = Path("frontend/nginx.conf").read_text(encoding="utf-8")
    if "location = /ready" not in nginx or "$backend_upstream/ready" not in nginx:
        raise SystemExit("frontend must proxy the public readiness endpoint to backend")
    if (
        "resolver 127.0.0.11" not in nginx
        or "set $backend_upstream backend:8010;" not in nginx
        or "proxy_pass http://$backend_upstream" not in nginx
    ):
        raise SystemExit(
            "frontend must resolve the backend at request time after container recovery"
        )
    print("Production Compose contract passed: fail-closed config, pinned images, read-only app containers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
