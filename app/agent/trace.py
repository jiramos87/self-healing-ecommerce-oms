"""Per-step incident trace helpers and stalled reporting."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from app import db, statuses

STALL_AFTER = timedelta(minutes=5)


def make_step(
    step: str,
    summary: str,
    *,
    served_by: str,
    ms: int,
    at: datetime | None = None,
) -> dict[str, Any]:
    return {
        "step": step,
        "summary": summary,
        "served_by": served_by,
        "ms": ms,
        "at": (at or datetime.now(UTC)).isoformat(),
    }


def persist_step(incident_id: str | UUID, step: dict[str, Any]) -> None:
    """Single choke point for appending a trace step from any agent module."""
    iid = incident_id if isinstance(incident_id, UUID) else UUID(str(incident_id))
    db.append_incident_trace(iid, step)


def last_trace_at(incident: dict[str, Any]) -> datetime | None:
    trace = incident.get("trace") or []
    if not trace:
        return None
    raw = trace[-1].get("at")
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    text = str(raw).replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def apply_stalled_if_needed(incident: dict[str, Any]) -> dict[str, Any]:
    """Lazily report diagnosing incidents stalled after 5 minutes."""
    if incident.get("status") != statuses.DIAGNOSING:
        return incident
    last = last_trace_at(incident)
    if last is None:
        return incident
    if datetime.now(UTC) - last < STALL_AFTER:
        return incident
    updated = db.update_incident(
        incident["id"],
        status=statuses.DIAGNOSIS_FAILED,
        summary=(incident.get("summary") or "") + " [stalled]",
        error_body={
            **(incident.get("error_body") or {}),
            "reason": "stalled",
        },
    )
    return updated


def present_incident(incident: dict[str, Any]) -> dict[str, Any]:
    """Return incident as API readers should see it (applies stalled)."""
    return apply_stalled_if_needed(incident)
