"""Health endpoint smoke test."""

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_health_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "remaining_daily_agent_runs" in body
    assert "kill_switch" in body
