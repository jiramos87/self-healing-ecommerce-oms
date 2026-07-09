"""Runbook retrieval: class map first, then keyword fallback."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNBOOKS_DIR = ROOT / "docs" / "runbooks"

CLASS_TO_FILE: dict[str, str] = {
    "unknown_region": "unknown_region.md",
    "phone_format": "phone_format.md",
    "duplicate_delivery": "duplicate_delivery.md",
    "cancelled_order": "cancelled_order.md",
}

KEYWORD_HINTS: dict[str, tuple[str, ...]] = {
    "unknown_region": ("province_code", "region", "regions.json", "unknown region"),
    "phone_format": ("phone", "normalizer", "phone_rules", "unparseable"),
    "duplicate_delivery": ("duplicate", "order_number", "redelivery", "idempotent"),
    "cancelled_order": ("cancelled_at", "cancelled", "expected behavior"),
}

DEFAULT_CLASS = "unknown_region"


def runbook_path(class_: str) -> Path:
    filename = CLASS_TO_FILE.get(class_, CLASS_TO_FILE[DEFAULT_CLASS])
    return RUNBOOKS_DIR / filename


def runbook_relpath(class_: str) -> str:
    """Repo-relative runbook path, for citations in traces and error bodies."""
    return str(runbook_path(class_).relative_to(ROOT))


def retrieve_runbook(class_or_query: str) -> dict[str, str]:
    """Return path and markdown for a class name or free-text query."""
    key = class_or_query.strip().lower().replace(" ", "_")
    if key in CLASS_TO_FILE:
        path = runbook_path(key)
        return {
            "class": key,
            "path": str(path.relative_to(ROOT)),
            "content": path.read_text(encoding="utf-8"),
        }

    query = class_or_query.strip().lower()
    best_class = DEFAULT_CLASS
    best_score = -1
    for class_name, hints in KEYWORD_HINTS.items():
        score = sum(1 for hint in hints if hint in query)
        if class_name.replace("_", " ") in query:
            score += 2
        if score > best_score:
            best_score = score
            best_class = class_name

    path = runbook_path(best_class)
    return {
        "class": best_class,
        "path": str(path.relative_to(ROOT)),
        "content": path.read_text(encoding="utf-8"),
    }
