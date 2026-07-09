"""POST /webhooks/orders: HMAC, schema, domain validation, persistence."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from psycopg import errors as pg_errors
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app import db, statuses
from app.agent.trace import make_step
from app.kb import runbook_relpath
from app.limits import CountersUnavailableError, try_reserve_agent_run
from app.phones import normalize_phone
from app.regions import resolve_region
from app.validation import OrderWebhook, configured_shop_domain

logger = logging.getLogger(__name__)

router = APIRouter()

HMAC_HEADER = "X-Shopify-Hmac-SHA256"
SHOP_HEADER = "X-Shopify-Shop-Domain"


def _webhook_secret() -> str:
    secret = os.environ.get("WEBHOOK_SECRET")
    if not secret:
        raise RuntimeError("WEBHOOK_SECRET is not set")
    return secret


def sign_body(raw_body: bytes) -> str:
    """Base64 HMAC-SHA256 of the raw body (Shopify-style signature)."""
    digest = hmac.new(
        _webhook_secret().encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def verify_hmac(raw_body: bytes, signature: str | None) -> bool:
    if not signature:
        return False
    expected = sign_body(raw_body)
    # Compare as bytes: compare_digest raises TypeError on non-ASCII str operands.
    return hmac.compare_digest(expected.encode("utf-8"), signature.encode("utf-8"))


def fingerprint(class_: str, store: str, offending_value: str) -> str:
    material = f"{class_}|{store}|{offending_value}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


def _json_id(value: UUID | Any) -> str:
    return str(value)


def _cite_runbook(incident_id: Any, class_: str) -> None:
    path = runbook_relpath(class_)
    step = make_step(
        "runbook",
        f"Handled per {path}",
        served_by="deterministic",
        ms=0,
    )
    db.append_incident_trace(incident_id, step)


def process_order_webhook(
    raw_body: bytes,
    *,
    hmac_signature: str | None,
    shop_domain: str | None,
) -> JSONResponse:
    """Process a signed order webhook body (HTTP or in-process simulate)."""
    if not verify_hmac(raw_body, hmac_signature):
        return JSONResponse({"error": "unauthorized", "detail": "bad_hmac"}, status_code=401)

    store = (shop_domain or "").strip().lower()
    if store != configured_shop_domain().lower():
        return JSONResponse(
            {"error": "unauthorized", "detail": "unknown_store"},
            status_code=401,
        )

    try:
        payload_dict = json.loads(raw_body)
    except json.JSONDecodeError:
        return JSONResponse(
            {"error": "invalid_json", "detail": "malformed JSON"},
            status_code=422,
        )

    try:
        order = OrderWebhook.model_validate(payload_dict)
    except ValidationError as exc:
        return JSONResponse(
            {"error": "schema_invalid", "detail": exc.errors()},
            status_code=422,
        )

    existing = db.find_order_by_store_and_number(store, order.order_number)
    if existing is not None:
        return _duplicate_delivery(store, order, existing)

    dumped = order.model_dump()

    if order.cancelled_at is not None:
        return _domain_failure(
            store=store,
            order=order,
            dumped=dumped,
            class_="cancelled_order",
            offending_value=order.order_number,
            summary=f"Cancelled order {order.order_number}",
            error_body={
                "cancelled_at": order.cancelled_at,
                "runbook": runbook_relpath("cancelled_order"),
            },
            incident_status=statuses.EXPECTED_BEHAVIOR,
            trigger_agent=False,
        )

    region_name = resolve_region(order.shipping_address.province_code)
    if region_name is None:
        return _domain_failure(
            store=store,
            order=order,
            dumped=dumped,
            class_="unknown_region",
            offending_value=order.shipping_address.province_code,
            summary=(
                f"Unknown region code {order.shipping_address.province_code}"
            ),
            error_body={
                "province_code": order.shipping_address.province_code,
                "province": order.shipping_address.province,
            },
            incident_status=statuses.RECEIVED,
            trigger_agent=True,
        )

    if normalize_phone(order.phone) is None:
        return _domain_failure(
            store=store,
            order=order,
            dumped=dumped,
            class_="phone_format",
            offending_value=order.phone,
            summary=f"Unparseable phone {order.phone}",
            error_body={"phone": order.phone},
            incident_status=statuses.RECEIVED,
            trigger_agent=True,
        )

    try:
        created = db.create_order(
            order_number=order.order_number,
            store=store,
            status="created",
            payload=dumped,
        )
    except pg_errors.UniqueViolation:
        racing = db.find_order_by_store_and_number(store, order.order_number)
        if racing is None:
            raise
        return _duplicate_delivery(store, order, racing)
    return JSONResponse(
        {
            "status": "accepted",
            "order_id": _json_id(created["id"]),
            "incident_id": None,
            "trigger_agent": False,
        }
    )


@router.post("/webhooks/orders")
async def orders_webhook(
    request: Request,
    x_shopify_hmac_sha256: str | None = Header(default=None, alias=HMAC_HEADER),
    x_shopify_shop_domain: str | None = Header(default=None, alias=SHOP_HEADER),
) -> JSONResponse:
    raw_body = await request.body()
    # All webhook work is blocking sync I/O; keep it off the event loop.
    return await run_in_threadpool(
        process_order_webhook,
        raw_body,
        hmac_signature=x_shopify_hmac_sha256,
        shop_domain=x_shopify_shop_domain,
    )


def _duplicate_delivery(
    store: str,
    order: OrderWebhook,
    existing: dict[str, Any],
) -> JSONResponse:
    """Idempotent ack for a redelivered (store, order_number); one incident total."""
    dup_fp = (
        f"{fingerprint('duplicate_delivery', store, order.order_number)}"
        f"-{_json_id(existing['id'])[:8]}"
    )
    incident = db.find_incident_by_fingerprint(dup_fp)
    if incident is not None:
        incident = db.record_recurrence(incident["id"])
    else:
        try:
            incident = db.create_duplicate_incident(
                fingerprint=dup_fp,
                summary=f"Duplicate delivery for order {order.order_number}",
                payload=order.model_dump(),
                error_body={
                    "original_order_id": _json_id(existing["id"]),
                    "order_number": order.order_number,
                    "runbook": runbook_relpath("duplicate_delivery"),
                },
                duplicate_of=existing["id"],
            )
            _cite_runbook(incident["id"], "duplicate_delivery")
        except pg_errors.UniqueViolation:
            racing = db.find_incident_by_fingerprint(dup_fp)
            if racing is None:
                raise
            incident = db.record_recurrence(racing["id"])
    return JSONResponse(
        {
            "status": "duplicate",
            "order_id": _json_id(existing["id"]),
            "incident_id": _json_id(incident["id"]),
            "trigger_agent": False,
        }
    )


def _recurrence_response(
    created_order: dict[str, Any],
    incident: dict[str, Any],
) -> JSONResponse:
    updated = db.record_recurrence(incident["id"])
    try:
        from app.agent.act import comment_on_recurrence

        comment_on_recurrence(updated)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "recurrence comment failed for incident %s: %s", updated["id"], exc
        )
    return JSONResponse(
        {
            "status": "accepted",
            "order_id": _json_id(created_order["id"]),
            "incident_id": _json_id(updated["id"]),
            "recurrence": True,
            "recurrence_count": updated["recurrence_count"],
            "trigger_agent": False,
        }
    )


def _domain_failure(
    *,
    store: str,
    order: OrderWebhook,
    dumped: dict[str, Any],
    class_: str,
    offending_value: str,
    summary: str,
    error_body: dict[str, Any],
    incident_status: str,
    trigger_agent: bool,
) -> JSONResponse:
    fp = fingerprint(class_, store, offending_value)
    existing_incident = db.find_incident_by_fingerprint(fp)

    capped = False
    effective_trigger = trigger_agent
    body = dict(error_body)
    if trigger_agent and existing_incident is None:
        try:
            # Atomic reservation: concurrent webhooks cannot exceed the cap.
            if not try_reserve_agent_run():
                effective_trigger = False
                capped = True
                body["reason"] = "capped"
        except CountersUnavailableError:
            return JSONResponse(
                {"error": "counters_unavailable", "detail": "fail_closed"},
                status_code=503,
            )

    try:
        created_order = db.create_order(
            order_number=order.order_number,
            store=store,
            status="on_hold",
            payload=dumped,
        )
    except pg_errors.UniqueViolation:
        racing = db.find_order_by_store_and_number(store, order.order_number)
        if racing is None:
            raise
        return _duplicate_delivery(store, order, racing)

    if existing_incident is not None:
        return _recurrence_response(created_order, existing_incident)

    try:
        incident = db.create_incident(
            class_=class_,
            status=incident_status,
            fingerprint=fp,
            summary=summary,
            error_body=body,
            payload=dumped,
        )
    except pg_errors.UniqueViolation:
        racing_incident = db.find_incident_by_fingerprint(fp)
        if racing_incident is None:
            raise
        return _recurrence_response(created_order, racing_incident)

    if incident_status == statuses.EXPECTED_BEHAVIOR:
        _cite_runbook(incident["id"], class_)

    result: dict[str, Any] = {
        "status": "accepted",
        "order_id": _json_id(created_order["id"]),
        "incident_id": _json_id(incident["id"]),
        "trigger_agent": effective_trigger,
    }
    if capped:
        result["reason"] = "capped"
    return JSONResponse(result)
