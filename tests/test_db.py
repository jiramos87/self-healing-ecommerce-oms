"""Env-gated Postgres round-trip for orders and incidents."""

from __future__ import annotations

import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set",
)


def test_create_and_read_order_and_incident() -> None:
    from app import db

    suffix = uuid.uuid4().hex[:8]
    order = db.create_order(
        order_number=f"TEST-{suffix}",
        store="demo.myshopify.com",
        status="created",
        payload={"order_number": f"TEST-{suffix}", "currency": "CLP"},
    )
    assert order["order_number"] == f"TEST-{suffix}"
    assert order["status"] == "created"

    fetched_order = db.get_order(order["id"])
    assert fetched_order is not None
    assert fetched_order["id"] == order["id"]
    assert fetched_order["payload"]["currency"] == "CLP"

    incident = db.create_incident(
        class_="unknown_region",
        status="received",
        fingerprint=f"fp-{suffix}",
        summary="test incident",
        error_body={"code": "UNKNOWN_REGION"},
        payload={"province_code": "XX"},
    )
    assert incident["class"] == "unknown_region"
    assert incident["status"] == "received"
    assert incident["fingerprint"] == f"fp-{suffix}"
    assert incident["recurrence_count"] == 1
    assert incident["trace"] == []

    fetched_incident = db.get_incident(incident["id"])
    assert fetched_incident is not None
    assert fetched_incident["id"] == incident["id"]
    assert fetched_incident["error_body"]["code"] == "UNKNOWN_REGION"
