"""Rate limits on the counters table: simulate IP and daily agent runs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app import db

SIMULATE_LIMIT = 3
SIMULATE_WINDOW = timedelta(minutes=10)
AGENT_DAILY_LIMIT = 20


class CountersUnavailableError(RuntimeError):
    """Raised when the counters store cannot be reached (fail closed)."""


@dataclass(frozen=True)
class LimitDecision:
    allowed: bool
    count: int
    limit: int
    retry_after_seconds: int | None = None


def kill_switch_enabled() -> bool:
    return os.environ.get("KILL_SWITCH", "").strip().lower() in {"1", "true", "yes"}


def _floor_window(now: datetime, window: timedelta) -> datetime:
    now = now.astimezone(UTC)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    seconds = int((now - epoch).total_seconds())
    bucket = seconds - (seconds % int(window.total_seconds()))
    return epoch + timedelta(seconds=bucket)


def _utc_day_start(now: datetime) -> datetime:
    now = now.astimezone(UTC)
    return datetime(now.year, now.month, now.day, tzinfo=UTC)


def check_and_increment_simulate(ip: str, *, now: datetime | None = None) -> LimitDecision:
    now = now or datetime.now(UTC)
    window_start = _floor_window(now, SIMULATE_WINDOW)
    key = f"simulate:{ip}"
    try:
        # Fail closed on any counter failure.
        count = db.increment_counter(key, window_start)
    except Exception as exc:  # noqa: BLE001
        raise CountersUnavailableError(str(exc)) from exc
    if count > SIMULATE_LIMIT:
        retry = int(
            (window_start + SIMULATE_WINDOW - now).total_seconds()
        )
        return LimitDecision(
            allowed=False,
            count=count,
            limit=SIMULATE_LIMIT,
            retry_after_seconds=max(retry, 1),
        )
    return LimitDecision(allowed=True, count=count, limit=SIMULATE_LIMIT)


def agent_runs_today(*, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    window_start = _utc_day_start(now)
    try:
        return db.get_counter("agent_runs", window_start)
    except Exception as exc:  # noqa: BLE001
        raise CountersUnavailableError(str(exc)) from exc


def remaining_daily_agent_runs(*, now: datetime | None = None) -> int:
    used = agent_runs_today(now=now)
    return max(AGENT_DAILY_LIMIT - used, 0)


def try_reserve_agent_run(*, now: datetime | None = None) -> bool:
    """Atomically reserve one of today's agent-run slots.

    Increment-then-compare (single upsert) so concurrent callers cannot all
    observe free capacity: at most AGENT_DAILY_LIMIT reservations succeed.
    """
    if kill_switch_enabled():
        return False
    now = now or datetime.now(UTC)
    window_start = _utc_day_start(now)
    try:
        count = db.increment_counter("agent_runs", window_start)
    except Exception as exc:  # noqa: BLE001
        raise CountersUnavailableError(str(exc)) from exc
    return count <= AGENT_DAILY_LIMIT


def health_caps_state() -> dict[str, Any]:
    try:
        remaining = remaining_daily_agent_runs()
        counters_ok = True
    except CountersUnavailableError:
        remaining = 0
        counters_ok = False
    return {
        "remaining_daily_agent_runs": remaining,
        "daily_agent_run_limit": AGENT_DAILY_LIMIT,
        "kill_switch": kill_switch_enabled(),
        "counters_ok": counters_ok,
    }
