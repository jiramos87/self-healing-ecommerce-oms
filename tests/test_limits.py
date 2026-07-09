"""Rate limit and fail-closed counter tests."""

from __future__ import annotations

import os
import uuid
from unittest.mock import patch

import pytest
from app.limits import CountersUnavailableError
from app.main import app
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL") or not os.environ.get("WEBHOOK_SECRET"),
    reason="DATABASE_URL and WEBHOOK_SECRET required",
)

client = TestClient(app)


def test_simulate_rate_limit_429() -> None:
    ip = f"10.50.{uuid.uuid4().int % 200}.{uuid.uuid4().int % 200}"
    headers = {"X-Forwarded-For": ip}
    for _ in range(3):
        ok = client.post("/demo/simulate", json={"class": "valid"}, headers=headers)
        assert ok.status_code == 200
    limited = client.post("/demo/simulate", json={"class": "valid"}, headers=headers)
    assert limited.status_code == 429
    body = limited.json()
    assert body["error"] == "rate_limited"
    assert "retry_after" in body
    assert limited.headers.get("retry-after") is not None


def test_simulate_503_when_counters_down() -> None:
    ip = f"10.51.{uuid.uuid4().int % 200}.{uuid.uuid4().int % 200}"
    with patch(
        "app.simulate.check_and_increment_simulate",
        side_effect=CountersUnavailableError("down"),
    ):
        response = client.post(
            "/demo/simulate",
            json={"class": "valid"},
            headers={"X-Forwarded-For": ip},
        )
    assert response.status_code == 503
    assert response.json()["error"] == "counters_unavailable"


def test_agent_capped_stores_received_without_trigger() -> None:
    from app import db

    ip = f"10.52.{uuid.uuid4().int % 200}.{uuid.uuid4().int % 200}"
    with patch("app.webhooks.try_reserve_agent_run", return_value=False):
        response = client.post(
            "/demo/simulate",
            json={"class": "unknown_region"},
            headers={"X-Forwarded-For": ip},
        )
    assert response.status_code == 200
    result = response.json()["delivery"]["result"]
    assert result["trigger_agent"] is False
    assert result["reason"] == "capped"
    incident = db.get_incident(uuid.UUID(result["incident_id"]))
    assert incident is not None
    assert incident["status"] == "received"
    assert incident["error_body"]["reason"] == "capped"


def test_webhook_503_when_agent_counters_down() -> None:
    ip = f"10.53.{uuid.uuid4().int % 200}.{uuid.uuid4().int % 200}"
    with (
        patch(
            "app.webhooks.try_reserve_agent_run",
            side_effect=CountersUnavailableError("down"),
        ),
        patch("app.simulate.check_and_increment_simulate") as sim_limit,
    ):
        from app.limits import LimitDecision

        sim_limit.return_value = LimitDecision(allowed=True, count=1, limit=3)
        response = client.post(
            "/demo/simulate",
            json={"class": "unknown_region"},
            headers={"X-Forwarded-For": ip},
        )
    assert response.status_code == 200
    # delivery itself returns 503 from process_order_webhook
    delivery = response.json()["delivery"]
    assert delivery["http_status"] == 503
    assert delivery["result"]["error"] == "counters_unavailable"


def test_agent_cap_reserves_atomically() -> None:
    from datetime import UTC, datetime

    from app import db
    from app.limits import AGENT_DAILY_LIMIT, _utc_day_start, try_reserve_agent_run

    window = _utc_day_start(datetime.now(UTC))

    def _reset() -> None:
        with db.connect() as conn:
            conn.execute(
                "DELETE FROM counters WHERE key = 'agent_runs' AND window_start = %s",
                (window,),
            )
            conn.commit()

    _reset()
    try:
        for _ in range(AGENT_DAILY_LIMIT):
            assert try_reserve_agent_run() is True
        assert try_reserve_agent_run() is False
    finally:
        # Leave capacity for the rest of the suite and later demo runs today.
        _reset()


def test_health_includes_caps_state() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "remaining_daily_agent_runs" in body
    assert "kill_switch" in body
    assert "daily_agent_run_limit" in body
    assert body["daily_agent_run_limit"] == 20
