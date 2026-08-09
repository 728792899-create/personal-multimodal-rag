from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.registry_migration import migrate_sqlite_to_postgres


def main() -> int:
    parser = argparse.ArgumentParser(
        description="将本地 SQLite registry 迁移到 PostgreSQL registry。",
    )
    parser.add_argument("--sqlite", required=True)
    parser.add_argument("--postgres-dsn", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = migrate_sqlite_to_postgres(
        args.sqlite,
        args.postgres_dsn,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
