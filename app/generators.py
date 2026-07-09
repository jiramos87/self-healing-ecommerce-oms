"""Demo payload generators with novelty guarantees for region and phone."""

from __future__ import annotations

import random
import string
import uuid
from typing import Any, Literal

from app import db
from app.data import load_data_file
from app.phones import normalize_phone
from app.regions import load_regions

SimulateClass = Literal[
    "valid",
    "unknown_region",
    "phone_format",
    "duplicate_delivery",
    "cancelled_order",
]


def _catalog_product() -> dict[str, Any]:
    products = load_data_file("catalog.json")["products"]
    return random.choice(products)


def _base_payload() -> dict[str, Any]:
    product = _catalog_product()
    return {
        "order_number": f"SIM-{uuid.uuid4().hex[:10].upper()}",
        "email": f"buyer-{uuid.uuid4().hex[:6]}@example.com",
        "phone": "+56912345678",
        "total_price": product["price"],
        "currency": "CLP",
        "line_items": [
            {
                "sku": product["sku"],
                "title": product["title"],
                "quantity": 1,
                "price": product["price"],
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
        "customer": {"first_name": "Demo", "last_name": "Visitor"},
        "cancelled_at": None,
    }


def _known_region_codes() -> set[str]:
    known = {code.upper() for code in load_regions()}
    known.update(code.upper() for code in db.list_seen_province_codes())
    return known


def _known_phones() -> set[str]:
    return set(db.list_seen_phones())


def novel_region() -> tuple[str, str]:
    """Return (province_code, province name) never seen in data or DB."""
    known = _known_region_codes()
    alphabet = string.ascii_uppercase
    for _ in range(500):
        code = "".join(random.choices(alphabet, k=2))
        if code in known:
            continue
        name = f"Generated Region {code}"
        return code, name
    raise RuntimeError("exhausted region code space")


def novel_phone() -> str:
    """Return a phone string that matches no rule and is not in DB history."""
    known = _known_phones()
    for i in range(500):
        phone = f"BAD-{uuid.uuid4().hex[:8].upper()}-{i}"
        if phone in known:
            continue
        if normalize_phone(phone) is not None:
            continue
        return phone
    raise RuntimeError("exhausted novel phone space")


def generate_payload(class_: SimulateClass) -> dict[str, Any]:
    payload = _base_payload()
    if class_ in {"valid", "duplicate_delivery"}:
        return payload
    if class_ == "cancelled_order":
        payload["cancelled_at"] = "2026-07-09T12:00:00Z"
        return payload
    if class_ == "unknown_region":
        code, name = novel_region()
        payload["shipping_address"]["province_code"] = code
        payload["shipping_address"]["province"] = name
        return payload
    if class_ == "phone_format":
        payload["phone"] = novel_phone()
        return payload
    raise ValueError(f"unknown simulate class: {class_}")
