"""Wire ingestion to the diagnosis agent per the recorded TRIGGER_MODE.

B01 verdict: TRIGGER_MODE=background. On Vercel Fluid Compute for Python a
FastAPI ``BackgroundTasks`` reliably completes after the HTTP response, so the
webhook acks fast and the agent runs in the same invocation.

Modes:
- ``background`` (default): schedule the run as an in-invocation background task.
- ``orchestrated``: run the agent synchronously after the ack (fallback shape).
- ``off``: never auto-run (used by the automated test suite, which must not
  incur real LLM/GitHub side effects; direct webhooks stay ``received`` until a
  manual retry, mirroring the PRD's orchestrated-fallback wording).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Protocol
from uuid import UUID

logger = logging.getLogger(__name__)


class _Scheduler(Protocol):
    def add_task(self, func: Any, /, *args: Any, **kwargs: Any) -> None: ...


def _mode() -> str:
    # Read at call time so per-request overrides (and tests) take effect.
    return (os.environ.get("TRIGGER_MODE") or "background").strip().lower()


def _run_agent(incident_id: str) -> None:
    """Run the full diagnosis pipeline for one incident, swallowing failures.

    A background task must never crash the worker: the pipeline already
    persists diagnosis_failed for its own errors, and anything unexpected here
    is logged, not raised.
    """
    from app.agent.graph import run_diagnosis

    try:
        run_diagnosis(UUID(incident_id))
    except Exception as exc:  # noqa: BLE001
        logger.exception("agent run failed for incident %s: %s", incident_id, exc)


def _dispatch(incident_id: str, scheduler: _Scheduler | None) -> None:
    if _mode() == "background" and scheduler is not None:
        scheduler.add_task(_run_agent, incident_id)
    else:
        _run_agent(incident_id)


def maybe_schedule(result: dict[str, Any], scheduler: _Scheduler | None) -> None:
    """Schedule an agent run when an ingestion result asks for one.

    ``result`` is a parsed webhook response body: it triggers when
    ``trigger_agent`` is truthy and an ``incident_id`` is present. A no-op in
    ``off`` mode.
    """
    if _mode() == "off":
        return
    if not result.get("trigger_agent"):
        return
    incident_id = result.get("incident_id")
    if not incident_id:
        return
    _dispatch(str(incident_id), scheduler)


def schedule_retry(incident_id: str, scheduler: _Scheduler | None) -> None:
    """Re-run diagnosis for an incident. Manual action: runs even in ``off`` mode."""
    _dispatch(str(incident_id), scheduler)
