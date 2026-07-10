"""Serve the self-contained demo dashboard at the site root.

The document is a single static HTML file with inline CSS and JS (no bundler,
no external hosts, CSP-friendly). It is a pure client of the existing read API
and simulate endpoint; serving it adds no other server behavior.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_INDEX = Path(__file__).resolve().parent / "static" / "index.html"


@cache
def _dashboard_html() -> str:
    return _INDEX.read_text(encoding="utf-8")


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def dashboard() -> HTMLResponse:
    return HTMLResponse(_dashboard_html())
