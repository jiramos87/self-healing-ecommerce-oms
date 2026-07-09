"""Shopify-shaped order webhook payload schema and store config."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.data import load_data_file


def load_store() -> dict[str, str]:
    return load_data_file("store.json")


def configured_shop_domain() -> str:
    return load_store()["shop_domain"]


class LineItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sku: str
    title: str
    quantity: int = Field(ge=1)
    price: str


class ShippingAddress(BaseModel):
    model_config = ConfigDict(extra="ignore")

    address1: str
    city: str
    zip: str
    province: str
    province_code: str
    country_code: str


class Customer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    first_name: str
    last_name: str


class OrderWebhook(BaseModel):
    model_config = ConfigDict(extra="ignore")

    order_number: str
    email: str
    phone: str
    total_price: str
    currency: str
    line_items: list[LineItem] = Field(min_length=1)
    shipping_address: ShippingAddress
    customer: Customer
    cancelled_at: str | None = None
