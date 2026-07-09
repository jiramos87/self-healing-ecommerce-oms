"""Region code lookup against app/data/regions.json."""

from __future__ import annotations

from app.data import load_data_file


def load_regions() -> dict[str, str]:
    return load_data_file("regions.json")


def resolve_region(province_code: str) -> str | None:
    """Return display name for a known province_code, else None."""
    return load_regions().get(province_code.strip().upper())
