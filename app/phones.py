"""Phone normalization against app/data/phone_rules.json."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from app.data import load_data_file


def load_phone_rules() -> list[dict[str, Any]]:
    return list(load_data_file("phone_rules.json")["rules"])


@lru_cache(maxsize=1)
def _compiled_patterns() -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(rule["pattern"]) for rule in load_phone_rules())


def normalize_phone(phone: str) -> str | None:
    """Return the phone if it matches a known rule, else None."""
    candidate = phone.strip()
    for pattern in _compiled_patterns():
        if pattern.fullmatch(candidate):
            return candidate
    return None
