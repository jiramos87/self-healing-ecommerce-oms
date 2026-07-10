"""Postgres connection helpers for orders and incidents."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast
from uuid import UUID

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


_pool: ConnectionPool | None = None


def _get_pool() -> ConnectionPool:
    # One pool per warm instance: the database is reached over the public
    # internet, so a connection per query would pay a TLS handshake each time.
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            database_url(),
            min_size=1,
            max_size=5,
            kwargs={"row_factory": cast(Any, dict_row)},
            open=True,
        )
    return _pool


@contextmanager
def connect() -> Iterator[Any]:
    with _get_pool().connection() as conn:
        yield conn


def close_pool() -> None:
    """Close the pool (test teardown; not needed in serverless runtime)."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def create_order(
    *,
    order_number: str,
    store: str,
    status: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute(
            """
            INSERT INTO orders (order_number, store, status, payload)
            VALUES (%s, %s, %s, %s)
            RETURNING id, order_number, store, status, payload, created_at
            """,
            (order_number, store, status, Jsonb(payload)),
        ).fetchone()
        conn.commit()
        assert row is not None
        return dict(row)


def get_order(order_id: UUID) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT id, order_number, store, status, payload, created_at
            FROM orders
            WHERE id = %s
            """,
            (order_id,),
        ).fetchone()
        return dict(row) if row else None


_INCIDENT_COLUMNS = """
    id, created_at, class, status, fingerprint, summary,
    error_body, payload, recurrence_count, last_seen_at,
    duplicate_of, issue_url, pr_url, trace
"""


def list_incidents(
    *,
    limit: int,
    before: tuple[Any, UUID] | None = None,
) -> list[dict[str, Any]]:
    """Newest-first incidents, keyset-paginated on (created_at, id)."""
    with connect() as conn:
        if before is None:
            rows = conn.execute(
                f"""
                SELECT {_INCIDENT_COLUMNS}
                FROM incidents
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
        else:
            created_at, incident_id = before
            rows = conn.execute(
                f"""
                SELECT {_INCIDENT_COLUMNS}
                FROM incidents
                WHERE (created_at, id) < (%s, %s)
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (created_at, incident_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]


def list_orders(*, limit: int) -> list[dict[str, Any]]:
    """Most recent orders first."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, order_number, store, status, payload, created_at
            FROM orders
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def create_incident(
    *,
    class_: str,
    status: str,
    fingerprint: str,
    summary: str | None = None,
    error_body: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute(
            """
            INSERT INTO incidents (
                class, status, fingerprint, summary, error_body, payload
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING
                id, created_at, class, status, fingerprint, summary,
                error_body, payload, recurrence_count, last_seen_at,
                duplicate_of, issue_url, pr_url, trace
            """,
            (
                class_,
                status,
                fingerprint,
                summary,
                Jsonb(error_body) if error_body is not None else None,
                Jsonb(payload) if payload is not None else None,
            ),
        ).fetchone()
        conn.commit()
        assert row is not None
        return dict(row)


def get_incident(incident_id: UUID) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT
                id, created_at, class, status, fingerprint, summary,
                error_body, payload, recurrence_count, last_seen_at,
                duplicate_of, issue_url, pr_url, trace
            FROM incidents
            WHERE id = %s
            """,
            (incident_id,),
        ).fetchone()
        return dict(row) if row else None


def find_order_by_store_and_number(
    store: str,
    order_number: str,
) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT id, order_number, store, status, payload, created_at
            FROM orders
            WHERE store = %s AND order_number = %s
            """,
            (store, order_number),
        ).fetchone()
        return dict(row) if row else None


def find_incident_by_fingerprint(fingerprint: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT
                id, created_at, class, status, fingerprint, summary,
                error_body, payload, recurrence_count, last_seen_at,
                duplicate_of, issue_url, pr_url, trace
            FROM incidents
            WHERE fingerprint = %s
            """,
            (fingerprint,),
        ).fetchone()
        return dict(row) if row else None


def record_recurrence(incident_id: UUID) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute(
            """
            UPDATE incidents
            SET recurrence_count = recurrence_count + 1,
                last_seen_at = now()
            WHERE id = %s
            RETURNING
                id, created_at, class, status, fingerprint, summary,
                error_body, payload, recurrence_count, last_seen_at,
                duplicate_of, issue_url, pr_url, trace
            """,
            (incident_id,),
        ).fetchone()
        conn.commit()
        assert row is not None
        return dict(row)


def create_duplicate_incident(
    *,
    fingerprint: str,
    summary: str,
    payload: dict[str, Any],
    error_body: dict[str, Any],
    duplicate_of: UUID | None = None,
) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute(
            """
            INSERT INTO incidents (
                class, status, fingerprint, summary, error_body, payload,
                duplicate_of
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING
                id, created_at, class, status, fingerprint, summary,
                error_body, payload, recurrence_count, last_seen_at,
                duplicate_of, issue_url, pr_url, trace
            """,
            (
                "duplicate_delivery",
                "duplicate",
                fingerprint,
                summary,
                Jsonb(error_body),
                Jsonb(payload),
                duplicate_of,
            ),
        ).fetchone()
        conn.commit()
        assert row is not None
        return dict(row)


def increment_counter(key: str, window_start: Any) -> int:
    with connect() as conn:
        row = conn.execute(
            """
            INSERT INTO counters (key, window_start, count)
            VALUES (%s, %s, 1)
            ON CONFLICT (key, window_start)
            DO UPDATE SET count = counters.count + 1
            RETURNING count
            """,
            (key, window_start),
        ).fetchone()
        conn.commit()
        assert row is not None
        return int(row["count"])


def get_counter(key: str, window_start: Any) -> int:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT count FROM counters
            WHERE key = %s AND window_start = %s
            """,
            (key, window_start),
        ).fetchone()
        return int(row["count"]) if row else 0


def list_seen_province_codes() -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT error_body->>'province_code' AS code
            FROM incidents
            WHERE class = 'unknown_region'
              AND error_body ? 'province_code'
            """
        ).fetchall()
        return [r["code"] for r in rows if r["code"]]


def list_seen_phones() -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT error_body->>'phone' AS phone
            FROM incidents
            WHERE class = 'phone_format'
              AND error_body ? 'phone'
            """
        ).fetchall()
        return [r["phone"] for r in rows if r["phone"]]


def update_incident(
    incident_id: UUID,
    *,
    status: str | None = None,
    summary: str | None = None,
    error_body: dict[str, Any] | None = None,
    issue_url: str | None = None,
    pr_url: str | None = None,
) -> dict[str, Any]:
    assignments: list[str] = []
    values: list[Any] = []
    if status is not None:
        assignments.append("status = %s")
        values.append(status)
    if summary is not None:
        assignments.append("summary = %s")
        values.append(summary)
    if error_body is not None:
        assignments.append("error_body = %s")
        values.append(Jsonb(error_body))
    if issue_url is not None:
        assignments.append("issue_url = %s")
        values.append(issue_url)
    if pr_url is not None:
        assignments.append("pr_url = %s")
        values.append(pr_url)
    if not assignments:
        existing = get_incident(incident_id)
        assert existing is not None
        return existing
    values.append(incident_id)
    with connect() as conn:
        row = conn.execute(
            f"""
            UPDATE incidents
            SET {", ".join(assignments)}
            WHERE id = %s
            RETURNING
                id, created_at, class, status, fingerprint, summary,
                error_body, payload, recurrence_count, last_seen_at,
                duplicate_of, issue_url, pr_url, trace
            """,
            values,
        ).fetchone()
        conn.commit()
        assert row is not None
        return dict(row)


def append_incident_trace(incident_id: UUID, step: dict[str, Any]) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute(
            """
            UPDATE incidents
            SET trace = coalesce(trace, '[]'::jsonb) || %s::jsonb
            WHERE id = %s
            RETURNING
                id, created_at, class, status, fingerprint, summary,
                error_body, payload, recurrence_count, last_seen_at,
                duplicate_of, issue_url, pr_url, trace
            """,
            (Jsonb([step]), incident_id),
        ).fetchone()
        conn.commit()
        assert row is not None
        return dict(row)
