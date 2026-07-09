"""Simulate endpoint contract tests."""

from __future__ import annotations

import os
import uuid

import pytest
from app.main import app
from fastapi.testclient import TestClient
from httpx import Response

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL") or not os.environ.get("WEBHOOK_SECRET"),
    reason="DATABASE_URL and WEBHOOK_SECRET required",
)

client = TestClient(app)


def _simulate(class_: str, *, ip: str | None = None) -> Response:
    headers: dict[str, str] = {}
    if ip is not None:
        headers["X-Forwarded-For"] = ip
    return client.post("/demo/simulate", json={"class": class_}, headers=headers)


def test_simulate_valid() -> None:
    ip = f"10.0.{uuid.uuid4().int % 200}.{uuid.uuid4().int % 200}"
    response = _simulate("valid", ip=ip)
    assert response.status_code == 200
    body = response.json()
    assert body["class"] == "valid"
    assert body["delivery"]["http_status"] == 200
    assert body["delivery"]["result"]["status"] == "accepted"
    assert body["delivery"]["result"]["incident_id"] is None


def test_simulate_unknown_region() -> None:
    from app import db

    ip = f"10.1.{uuid.uuid4().int % 200}.{uuid.uuid4().int % 200}"
    response = _simulate("unknown_region", ip=ip)
    assert response.status_code == 200
    body = response.json()
    result = body["delivery"]["result"]
    assert result["status"] == "accepted"
    assert result["trigger_agent"] is True
    incident = db.get_incident(uuid.UUID(result["incident_id"]))
    assert incident is not None
    assert incident["class"] == "unknown_region"
    code = body["delivery"]["payload"]["shipping_address"]["province_code"]
    assert len(code) == 2


def test_simulate_phone_format() -> None:
    from app import db

    ip = f"10.2.{uuid.uuid4().int % 200}.{uuid.uuid4().int % 200}"
    response = _simulate("phone_format", ip=ip)
    assert response.status_code == 200
    result = response.json()["delivery"]["result"]
    incident = db.get_incident(uuid.UUID(result["incident_id"]))
    assert incident is not None
    assert incident["class"] == "phone_format"


def test_simulate_cancelled_order() -> None:
    from app import db

    ip = f"10.3.{uuid.uuid4().int % 200}.{uuid.uuid4().int % 200}"
    response = _simulate("cancelled_order", ip=ip)
    assert response.status_code == 200
    result = response.json()["delivery"]["result"]
    assert result["trigger_agent"] is False
    incident = db.get_incident(uuid.UUID(result["incident_id"]))
    assert incident is not None
    assert incident["status"] == "expected_behavior"


def test_simulate_duplicate_delivery() -> None:
    ip = f"10.4.{uuid.uuid4().int % 200}.{uuid.uuid4().int % 200}"
    response = _simulate("duplicate_delivery", ip=ip)
    assert response.status_code == 200
    body = response.json()
    assert body["first"]["result"]["status"] == "accepted"
    assert body["second"]["result"]["status"] == "duplicate"
    assert body["first"]["result"]["order_id"] == body["second"]["result"]["order_id"]


def test_unknown_region_novelty() -> None:
    ip_a = f"10.5.{uuid.uuid4().int % 200}.{uuid.uuid4().int % 200}"
    ip_b = f"10.6.{uuid.uuid4().int % 200}.{uuid.uuid4().int % 200}"
    a = _simulate("unknown_region", ip=ip_a).json()
    b = _simulate("unknown_region", ip=ip_b).json()
    code_a = a["delivery"]["payload"]["shipping_address"]["province_code"]
    code_b = b["delivery"]["payload"]["shipping_address"]["province_code"]
    assert code_a != code_b
