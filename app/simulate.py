"""POST /demo/simulate: generate, sign, and deliver webhooks in-process."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.generators import SimulateClass, generate_payload
from app.limits import CountersUnavailableError, check_and_increment_simulate
from app.validation import configured_shop_domain
from app.webhooks import process_order_webhook, sign_body

router = APIRouter()


class SimulateRequest(BaseModel):
    class_: SimulateClass = Field(alias="class")

    model_config = {"populate_by_name": True}


def _client_ip(request: Request) -> str:
    # On Vercel both headers are set at the edge and inbound spoofed values are
    # discarded, so neither is client-controllable there. x-real-ip is the
    # single-value form; keep the x-forwarded-for fallback for local runs.
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _deliver(payload: dict[str, Any]) -> dict[str, Any]:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    response = process_order_webhook(
        raw,
        hmac_signature=sign_body(raw),
        shop_domain=configured_shop_domain(),
    )
    raw_body = bytes(response.body)
    try:
        parsed: Any = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        parsed = {"raw": raw_body.decode("utf-8", errors="replace")}
    return {"http_status": response.status_code, "result": parsed, "payload": payload}


@router.post("/demo/simulate")
def simulate(request: Request, body: SimulateRequest) -> JSONResponse:
    ip = _client_ip(request)
    try:
        decision = check_and_increment_simulate(ip)
    except CountersUnavailableError:
        return JSONResponse(
            {"error": "counters_unavailable", "detail": "fail_closed"},
            status_code=503,
        )

    if not decision.allowed:
        return JSONResponse(
            {
                "error": "rate_limited",
                "detail": "Too many simulates from this IP. Try again shortly.",
                "retry_after": decision.retry_after_seconds,
            },
            status_code=429,
            headers={
                "Retry-After": str(decision.retry_after_seconds or 1),
            },
        )

    class_: SimulateClass = body.class_
    if class_ == "duplicate_delivery":
        payload = generate_payload(class_)
        first = _deliver(payload)
        second = _deliver(payload)
        return JSONResponse(
            {
                "class": class_,
                "first": first,
                "second": second,
            }
        )

    payload = generate_payload(class_)
    delivery = _deliver(payload)
    return JSONResponse(
        {
            "class": class_,
            "delivery": delivery,
        }
    )


__all__ = ["router", "SimulateRequest"]
