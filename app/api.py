"""Public read API (incidents, orders) and the admin-gated retry endpoint."""

from __future__ import annotations

import base64
import binascii
import hmac
import os
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Header, Query
from fastapi.responses import JSONResponse

from app import db, statuses
from app.agent.trace import present_incident
from app.trigger import schedule_retry

router = APIRouter()

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _serialize_incident(incident: dict[str, Any]) -> dict[str, Any]:
    """Public incident shape per the PRD (github nested, payload withheld)."""
    inc = present_incident(incident)
    duplicate_of = inc.get("duplicate_of")
    return {
        "id": str(inc["id"]),
        "created_at": _iso(inc.get("created_at")),
        "class": inc.get("class"),
        "status": inc.get("status"),
        "fingerprint": inc.get("fingerprint"),
        "summary": inc.get("summary"),
        "error_body": inc.get("error_body"),
        "recurrence_count": inc.get("recurrence_count"),
        "last_seen_at": _iso(inc.get("last_seen_at")),
        "duplicate_of": str(duplicate_of) if duplicate_of else None,
        "github": {
            "issue_url": inc.get("issue_url"),
            "pr_url": inc.get("pr_url"),
        },
        "trace": inc.get("trace") or [],
    }


def _serialize_order(order: dict[str, Any]) -> dict[str, Any]:
    payload = order.get("payload") or {}
    return {
        "id": str(order["id"]),
        "order_number": order.get("order_number"),
        "store": order.get("store"),
        "status": order.get("status"),
        "total_price": payload.get("total_price"),
        "currency": payload.get("currency"),
        "created_at": _iso(order.get("created_at")),
    }


def _encode_cursor(row: dict[str, Any]) -> str:
    created_at = row["created_at"]
    raw = f"{_iso(created_at)}|{row['id']}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
    created_str, _, id_str = raw.rpartition("|")
    return datetime.fromisoformat(created_str), UUID(id_str)


@router.get("/incidents")
def get_incidents(
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: str | None = Query(None),
) -> JSONResponse:
    before: tuple[datetime, UUID] | None = None
    if cursor:
        try:
            before = _decode_cursor(cursor)
        except (binascii.Error, ValueError, UnicodeDecodeError):
            return JSONResponse(
                {"error": "invalid_cursor", "detail": "cursor is malformed"},
                status_code=400,
            )
    rows = db.list_incidents(limit=limit, before=before)
    incidents = [_serialize_incident(r) for r in rows]
    next_cursor = _encode_cursor(rows[-1]) if len(rows) == limit else None
    return JSONResponse({"incidents": incidents, "next_cursor": next_cursor})


@router.get("/incidents/{incident_id}")
def get_incident(incident_id: UUID) -> JSONResponse:
    incident = db.get_incident(incident_id)
    if incident is None:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return JSONResponse(_serialize_incident(incident))


@router.get("/orders")
def get_orders(
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
) -> JSONResponse:
    rows = db.list_orders(limit=limit)
    return JSONResponse({"orders": [_serialize_order(r) for r in rows]})


def _valid_admin_token(provided: str | None) -> bool:
    configured = os.environ.get("ADMIN_TOKEN") or ""
    if not configured or provided is None:
        return False
    # Compare as bytes: compare_digest raises TypeError on non-ASCII str operands.
    return hmac.compare_digest(provided.encode("utf-8"), configured.encode("utf-8"))


@router.post("/incidents/{incident_id}/retry")
def retry_incident(
    incident_id: UUID,
    background_tasks: BackgroundTasks,
    x_admin_token: str | None = Header(default=None),
) -> JSONResponse:
    if not _valid_admin_token(x_admin_token):
        return JSONResponse(
            {"error": "unauthorized", "detail": "bad_admin_token"},
            status_code=401,
        )
    incident = db.get_incident(incident_id)
    if incident is None:
        return JSONResponse({"error": "not_found"}, status_code=404)
    # Apply the lazy stalled transition so a stuck run becomes retryable.
    incident = present_incident(incident)
    if incident.get("status") != statuses.DIAGNOSIS_FAILED:
        return JSONResponse(
            {
                "error": "not_retryable",
                "detail": "incident is not in diagnosis_failed",
                "status": incident.get("status"),
            },
            status_code=409,
        )
    schedule_retry(str(incident_id), background_tasks)
    return JSONResponse(
        {"status": "retry_scheduled", "incident_id": str(incident_id)},
        status_code=202,
    )
