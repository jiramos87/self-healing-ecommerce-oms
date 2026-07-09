"""Webhook Given/When/Then coverage from the PRD."""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

import pytest
from app.main import app
from app.validation import configured_shop_domain
from app.webhooks import fingerprint, sign_body
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL") or not os.environ.get("WEBHOOK_SECRET"),
    reason="DATABASE_URL and WEBHOOK_SECRET required",
)

client = TestClient(app)
STORE = configured_shop_domain()


def _sign(body: bytes) -> str:
    return sign_body(body)


def _valid_payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "order_number": f"ORD-{uuid.uuid4().hex[:10]}",
        "email": "buyer@example.com",
        "phone": "+56912345678",
        "total_price": "19990",
        "currency": "CLP",
        "line_items": [
            {
                "sku": "TEE-001",
                "title": "Organic Cotton Tee",
                "quantity": 1,
                "price": "19990",
            }
        ],
        "shipping_address": {
            "address1": "Av. Providencia 123",
            "city": "Santiago",
            "zip": "7500000",
            "province": "Región Metropolitana de Santiago",
            "province_code": "RM",
            "country_code": "CL",
        },
        "customer": {"first_name": "Ana", "last_name": "Pérez"},
        "cancelled_at": None,
    }
    base.update(overrides)
    if "shipping_address" in overrides:
        merged = {
            "address1": "Av. Providencia 123",
            "city": "Santiago",
            "zip": "7500000",
            "province": "Región Metropolitana de Santiago",
            "province_code": "RM",
            "country_code": "CL",
        }
        merged.update(overrides["shipping_address"])
        base["shipping_address"] = merged
    return base


def _post(
    payload: dict[str, Any],
    *,
    hmac_sig: str | None | object = ...,
    shop: str | None = None,
):
    body = json.dumps(payload).encode("utf-8")
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "X-Shopify-Shop-Domain": shop if shop is not None else STORE,
    }
    if hmac_sig is ...:
        headers["X-Shopify-Hmac-SHA256"] = _sign(body)
    elif isinstance(hmac_sig, str):
        headers["X-Shopify-Hmac-SHA256"] = hmac_sig
    return client.post("/webhooks/orders", content=body, headers=headers)


def test_missing_hmac_returns_401() -> None:
    from app import db

    payload = _valid_payload()
    before = db.find_order_by_store_and_number(STORE.lower(), payload["order_number"])
    assert before is None
    response = _post(payload, hmac_sig=None)
    assert response.status_code == 401
    assert db.find_order_by_store_and_number(STORE.lower(), payload["order_number"]) is None


def test_wrong_hmac_returns_401() -> None:
    response = _post(_valid_payload(), hmac_sig="not-a-valid-signature")
    assert response.status_code == 401


def test_non_ascii_hmac_rejected_without_raising() -> None:
    # Starlette decodes header bytes latin-1, so a signature can reach
    # verify_hmac as a non-ASCII str; compare_digest on str would raise
    # TypeError (500). The bytes comparison must return False instead.
    from app.webhooks import verify_hmac

    assert verify_hmac(b"{}", "caf\xe9-signature") is False


def test_unknown_store_returns_401() -> None:
    response = _post(_valid_payload(), shop="evil.myshopify.com")
    assert response.status_code == 401


def test_malformed_json_returns_422() -> None:
    body = b"{not-json"
    headers = {
        "Content-Type": "application/json",
        "X-Shopify-Shop-Domain": STORE,
        "X-Shopify-Hmac-SHA256": _sign(body),
    }
    response = client.post("/webhooks/orders", content=body, headers=headers)
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_json"


def test_schema_invalid_returns_422_no_incident() -> None:
    from app import db

    payload = _valid_payload()
    del payload["email"]
    response = _post(payload)
    assert response.status_code == 422
    assert response.json()["error"] == "schema_invalid"
    assert db.find_order_by_store_and_number(STORE.lower(), payload["order_number"]) is None


def test_valid_webhook_creates_order() -> None:
    from app import db

    payload = _valid_payload()
    response = _post(payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["incident_id"] is None
    assert body["trigger_agent"] is False
    order = db.get_order(uuid.UUID(body["order_id"]))
    assert order is not None
    assert order["status"] == "created"


def test_unknown_region_on_hold_and_incident() -> None:
    from app import db

    code = f"X{uuid.uuid4().hex[:3].upper()}"
    payload = _valid_payload(
        shipping_address={
            "province_code": code,
            "province": "Zona Fantasma",
        }
    )
    response = _post(payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["trigger_agent"] is True
    order = db.get_order(uuid.UUID(body["order_id"]))
    assert order is not None
    assert order["status"] == "on_hold"
    incident = db.get_incident(uuid.UUID(body["incident_id"]))
    assert incident is not None
    assert incident["class"] == "unknown_region"
    assert incident["status"] == "received"
    assert incident["fingerprint"] == fingerprint(
        "unknown_region", STORE.lower(), code
    )


def test_phone_format_on_hold_and_incident() -> None:
    from app import db

    phone = f"not-a-phone-{uuid.uuid4().hex[:8]}"
    payload = _valid_payload(phone=phone)
    response = _post(payload)
    assert response.status_code == 200
    body = response.json()
    assert body["trigger_agent"] is True
    order = db.get_order(uuid.UUID(body["order_id"]))
    assert order is not None
    assert order["status"] == "on_hold"
    incident = db.get_incident(uuid.UUID(body["incident_id"]))
    assert incident is not None
    assert incident["class"] == "phone_format"
    assert incident["status"] == "received"


def test_cancelled_order_expected_behavior_no_agent() -> None:
    from app import db

    payload = _valid_payload(cancelled_at="2026-07-01T12:00:00Z")
    response = _post(payload)
    assert response.status_code == 200
    body = response.json()
    assert body["trigger_agent"] is False
    order = db.get_order(uuid.UUID(body["order_id"]))
    assert order is not None
    assert order["status"] == "on_hold"
    incident = db.get_incident(uuid.UUID(body["incident_id"]))
    assert incident is not None
    assert incident["class"] == "cancelled_order"
    assert incident["status"] == "expected_behavior"


def test_duplicate_delivery_returns_duplicate_incident() -> None:
    from app import db

    payload = _valid_payload()
    first = _post(payload)
    assert first.status_code == 200
    assert first.json()["status"] == "accepted"
    second = _post(payload)
    assert second.status_code == 200
    body = second.json()
    assert body["status"] == "duplicate"
    assert body["order_id"] == first.json()["order_id"]
    assert body["trigger_agent"] is False
    incident = db.get_incident(uuid.UUID(body["incident_id"]))
    assert incident is not None
    assert incident["class"] == "duplicate_delivery"
    assert incident["status"] == "duplicate"
    assert incident["error_body"]["original_order_id"] == first.json()["order_id"]
    assert str(incident["duplicate_of"]) == first.json()["order_id"]
    assert any(step["step"] == "runbook" for step in incident["trace"])

    # A third identical delivery must stay a clean duplicate ack (no 500)
    # and count as a recurrence of the same incident.
    third = _post(payload)
    assert third.status_code == 200
    third_body = third.json()
    assert third_body["status"] == "duplicate"
    assert third_body["incident_id"] == body["incident_id"]
    refreshed = db.get_incident(uuid.UUID(body["incident_id"]))
    assert refreshed is not None
    assert refreshed["recurrence_count"] == 2


def test_recurrence_increments_existing_incident() -> None:
    from app import db

    code = f"Q{uuid.uuid4().hex[:3].upper()}"
    first_payload = _valid_payload(
        shipping_address={"province_code": code, "province": "Mystery Region"}
    )
    first = _post(first_payload)
    assert first.status_code == 200
    first_body = first.json()
    incident_id = first_body["incident_id"]

    second_payload = _valid_payload(
        shipping_address={"province_code": code, "province": "Mystery Region"}
    )
    second = _post(second_payload)
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["incident_id"] == incident_id
    assert second_body["recurrence"] is True
    assert second_body["trigger_agent"] is False

    incident = db.get_incident(uuid.UUID(incident_id))
    assert incident is not None
    assert incident["recurrence_count"] == 2
