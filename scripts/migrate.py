"""Apply SQL migrations in db/migrations/ in lexical order."""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = ROOT / "db" / "migrations"

sys.path.insert(0, str(ROOT))

from app.db import database_url as app_database_url  # noqa: E402


def main() -> int:
    try:
        database_url = app_database_url()
    except RuntimeError:
        print("DATABASE_URL is required", file=sys.stderr)
        return 1

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        print(f"No migrations in {MIGRATIONS_DIR}", file=sys.stderr)
        return 1

    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        for path in files:
            applied = conn.execute(
                "SELECT 1 FROM schema_migrations WHERE filename = %s",
                (path.name,),
            ).fetchone()
            if applied:
                print(f"skip {path.name}")
                continue
            sql = path.read_text(encoding="utf-8")
            with conn.transaction():
                conn.execute(sql)
                conn.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (%s)",
                    (path.name,),
                )
            print(f"applied {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
