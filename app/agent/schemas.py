"""Typed recipe parameter schemas for diagnosis extraction."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class UnknownRegionParams(BaseModel):
    province_code: str = Field(min_length=1)
    province: str = Field(min_length=1)


class PhoneFormatParams(BaseModel):
    name: str = Field(min_length=1)
    pattern: str = Field(min_length=1)
    description: str = Field(min_length=1)


RecipeClass = Literal["unknown_region", "phone_format"]

RECIPE_SCHEMAS: dict[str, type[BaseModel]] = {
    "unknown_region": UnknownRegionParams,
    "phone_format": PhoneFormatParams,
}

FIXABLE_CLASSES = frozenset(RECIPE_SCHEMAS)
NO_AGENT_CLASSES = frozenset({"duplicate_delivery", "cancelled_order"})


def validate_recipe_params(class_: str, params: dict[str, Any]) -> BaseModel:
    schema = RECIPE_SCHEMAS.get(class_)
    if schema is None:
        raise ValueError(f"no recipe schema for class {class_}")
    return schema.model_validate(params)
