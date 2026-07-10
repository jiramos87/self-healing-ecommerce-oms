"""Shared test setup."""

from __future__ import annotations

import os

import pytest

# Automated tests must never fire real LLM/GitHub side effects, so ingestion
# does not auto-run the agent during the suite. Trigger wiring is covered
# explicitly in test_api.py; per-test overrides use monkeypatch.setenv, which
# restores this baseline afterwards.
os.environ["TRIGGER_MODE"] = "off"


@pytest.fixture(scope="session", autouse=True)
def _reset_agent_run_counter():
    """Free today's agent-run reservations consumed by earlier test runs.

    Webhook tests reserve real daily slots (20/day) on the shared database;
    without this reset, repeated test sessions in one day would start seeing
    capped incidents and fail for the wrong reason.
    """
    if not os.environ.get("DATABASE_URL"):
        yield
        return
    from datetime import UTC, datetime

    from app import db
    from app.limits import _utc_day_start

    window = _utc_day_start(datetime.now(UTC))
    with db.connect() as conn:
        conn.execute(
            "DELETE FROM counters WHERE key = 'agent_runs' AND window_start = %s",
            (window,),
        )
        conn.commit()
    yield
    db.close_pool()
