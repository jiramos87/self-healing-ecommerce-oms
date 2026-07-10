"""B09: read API shapes, retry auth/state, and trigger wiring."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.main import app
from app.validation import configured_shop_domain
from app.webhooks import sign_body
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL") or not os.environ.get("WEBHOOK_SECRET"),
    reason="DATABASE_URL and WEBHOOK_SECRET required",
)

client = TestClient(app)
STORE = configured_shop_domain()
ADMIN_TOKEN = "test-admin-token"


def _new_incident(status: str, class_: str = "unknown_region") -> dict[str, Any]:
    from app import db

    suffix = uuid.uuid4().hex[:10]
    return db.create_incident(
        class_=class_,
        status=status,
        fingerprint=f"api-{suffix}",
        summary=f"api test {suffix}",
        error_body={"province_code": "ZZ", "province": "Zeta"},
        payload={"order_number": f"A-{suffix}"},
    )


# --- GET /incidents -----------------------------------------------------------


def test_incidents_list_shape_and_newest_first() -> None:
    older = _new_incident("received")
    newer = _new_incident("pr_opened")

    response = client.get("/incidents", params={"limit": 50})
    assert response.status_code == 200
    body = response.json()
    assert "incidents" in body
    assert "next_cursor" in body

    ids = [i["id"] for i in body["incidents"]]
    assert str(newer["id"]) in ids
    assert str(older["id"]) in ids
    # Newest first: the just-created newer incident precedes the older one.
    assert ids.index(str(newer["id"])) < ids.index(str(older["id"]))

    sample = next(i for i in body["incidents"] if i["id"] == str(newer["id"]))
    assert set(sample) >= {
        "id",
        "created_at",
        "class",
        "status",
        "fingerprint",
        "summary",
        "error_body",
        "recurrence_count",
        "last_seen_at",
        "duplicate_of",
        "github",
        "trace",
    }
    assert set(sample["github"]) == {"issue_url", "pr_url"}
    assert isinstance(sample["trace"], list)


def test_incidents_cursor_paginates() -> None:
    for _ in range(3):
        _new_incident("received")

    first = client.get("/incidents", params={"limit": 2}).json()
    assert len(first["incidents"]) == 2
    assert first["next_cursor"]

    second = client.get(
        "/incidents", params={"limit": 2, "cursor": first["next_cursor"]}
    ).json()
    first_ids = {i["id"] for i in first["incidents"]}
    second_ids = {i["id"] for i in second["incidents"]}
    assert first_ids.isdisjoint(second_ids)


def test_incidents_empty_list_is_well_formed() -> None:
    # A cursor before all rows yields an empty, well-formed page (not an error).
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    import base64

    raw = f"{epoch.isoformat()}|{uuid.UUID(int=0)}"
    cursor = base64.urlsafe_b64encode(raw.encode()).decode()
    response = client.get("/incidents", params={"cursor": cursor})
    assert response.status_code == 200
    body = response.json()
    assert body["incidents"] == []
    assert body["next_cursor"] is None


def test_incidents_bad_cursor_returns_400() -> None:
    response = client.get("/incidents", params={"cursor": "!!!not-base64!!!"})
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_cursor"


# --- GET /incidents/{id} ------------------------------------------------------


def test_incident_detail_shape() -> None:
    incident = _new_incident("received")
    response = client.get(f"/incidents/{incident['id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(incident["id"])
    assert body["class"] == "unknown_region"
    assert body["github"] == {"issue_url": None, "pr_url": None}
    assert isinstance(body["trace"], list)
    assert "payload" not in body


def test_incident_detail_not_found() -> None:
    response = client.get(f"/incidents/{uuid.uuid4()}")
    assert response.status_code == 404


# --- GET /orders --------------------------------------------------------------


def test_orders_list_shape() -> None:
    from app import db

    number = f"ORD-{uuid.uuid4().hex[:10]}"
    order = db.create_order(
        order_number=number,
        store=STORE.lower(),
        status="created",
        payload={"total_price": "19990", "currency": "CLP"},
    )
    response = client.get("/orders", params={"limit": 50})
    assert response.status_code == 200
    body = response.json()
    assert "orders" in body
    found = next((o for o in body["orders"] if o["id"] == str(order["id"])), None)
    assert found is not None
    assert set(found) >= {
        "id",
        "order_number",
        "store",
        "status",
        "created_at",
    }
    assert found["order_number"] == number
    assert found["total_price"] == "19990"


# --- POST /incidents/{id}/retry ----------------------------------------------


def test_retry_bad_token_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    incident = _new_incident("diagnosis_failed")
    response = client.post(
        f"/incidents/{incident['id']}/retry",
        headers={"X-Admin-Token": "wrong"},
    )
    assert response.status_code == 401


def test_retry_missing_token_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    incident = _new_incident("diagnosis_failed")
    response = client.post(f"/incidents/{incident['id']}/retry")
    assert response.status_code == 401


def test_retry_non_ascii_token_rejected_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Headers decode latin-1, so a token can reach the check as a non-ASCII str;
    # compare_digest on str would raise TypeError (500). Must be a plain False.
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    from app.api import _valid_admin_token

    assert _valid_admin_token("caf\xe9-token") is False


def test_retry_wrong_state_returns_409(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    incident = _new_incident("received")
    response = client.post(
        f"/incidents/{incident['id']}/retry",
        headers={"X-Admin-Token": ADMIN_TOKEN},
    )
    assert response.status_code == 409
    assert response.json()["status"] == "received"


def test_retry_not_found_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    response = client.post(
        f"/incidents/{uuid.uuid4()}/retry",
        headers={"X-Admin-Token": ADMIN_TOKEN},
    )
    assert response.status_code == 404


def test_retry_diagnosis_failed_schedules_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    ran: list[str] = []
    monkeypatch.setattr("app.trigger._run_agent", lambda incident_id: ran.append(incident_id))

    incident = _new_incident("diagnosis_failed")
    response = client.post(
        f"/incidents/{incident['id']}/retry",
        headers={"X-Admin-Token": ADMIN_TOKEN},
    )
    assert response.status_code == 202
    assert response.json()["incident_id"] == str(incident["id"])
    assert ran == [str(incident["id"])]


def test_retry_stalled_incident_is_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import db
    from app.agent.trace import make_step

    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    ran: list[str] = []
    monkeypatch.setattr("app.trigger._run_agent", lambda incident_id: ran.append(incident_id))

    incident = _new_incident("diagnosing")
    stale_at = datetime.now(UTC) - timedelta(minutes=6)
    db.append_incident_trace(
        incident["id"],
        make_step("diagnose", "mid-flight", served_by="test", ms=1, at=stale_at),
    )

    response = client.post(
        f"/incidents/{incident['id']}/retry",
        headers={"X-Admin-Token": ADMIN_TOKEN},
    )
    assert response.status_code == 202
    assert ran == [str(incident["id"])]


# --- Trigger wiring -----------------------------------------------------------


class _FakeScheduler:
    def __init__(self) -> None:
        self.tasks: list[tuple[Any, tuple[Any, ...]]] = []

    def add_task(self, func: Any, /, *args: Any, **kwargs: Any) -> None:
        self.tasks.append((func, args))


def test_maybe_schedule_background_adds_task(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import trigger

    monkeypatch.setenv("TRIGGER_MODE", "background")
    scheduler = _FakeScheduler()
    trigger.maybe_schedule(
        {"trigger_agent": True, "incident_id": "abc"}, scheduler
    )
    assert len(scheduler.tasks) == 1
    func, args = scheduler.tasks[0]
    assert func is trigger._run_agent
    assert args == ("abc",)


def test_maybe_schedule_off_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import trigger

    monkeypatch.setenv("TRIGGER_MODE", "off")
    scheduler = _FakeScheduler()
    trigger.maybe_schedule({"trigger_agent": True, "incident_id": "abc"}, scheduler)
    assert scheduler.tasks == []


def test_maybe_schedule_ignores_untriggered(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import trigger

    monkeypatch.setenv("TRIGGER_MODE", "background")
    scheduler = _FakeScheduler()
    trigger.maybe_schedule({"trigger_agent": False, "incident_id": "abc"}, scheduler)
    assert scheduler.tasks == []


def test_webhook_route_schedules_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    # End to end through the HTTP handler: an unknown_region webhook flags a
    # trigger, and the background task fires (TestClient runs it in-request).
    monkeypatch.setenv("TRIGGER_MODE", "background")
    ran: list[str] = []
    monkeypatch.setattr("app.trigger._run_agent", lambda incident_id: ran.append(incident_id))

    code = f"W{uuid.uuid4().hex[:3].upper()}"
    payload = {
        "order_number": f"ORD-{uuid.uuid4().hex[:10]}",
        "email": "buyer@example.com",
        "phone": "+56912345678",
        "total_price": "19990",
        "currency": "CLP",
        "line_items": [
            {"sku": "TEE-001", "title": "Tee", "quantity": 1, "price": "19990"}
        ],
        "shipping_address": {
            "address1": "Av. Providencia 123",
            "city": "Santiago",
            "zip": "7500000",
            "province": "Zona Fantasma",
            "province_code": code,
            "country_code": "CL",
        },
        "customer": {"first_name": "Ana", "last_name": "Perez"},
        "cancelled_at": None,
    }
    raw = json.dumps(payload).encode("utf-8")
    response = client.post(
        "/webhooks/orders",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Shopify-Shop-Domain": STORE,
            "X-Shopify-Hmac-SHA256": sign_body(raw),
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["trigger_agent"] is True
    assert ran == [body["incident_id"]]
