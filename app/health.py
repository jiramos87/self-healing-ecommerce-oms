"""GET /health with caps state."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.limits import health_caps_state

router = APIRouter()


@router.get("/health")
def health() -> JSONResponse:
    caps = health_caps_state()
    return JSONResponse({"ok": True, **caps})
