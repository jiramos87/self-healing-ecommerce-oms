"""FastAPI application entry."""

import psycopg
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout

from app.api import router as api_router
from app.db import StorageUnavailableError
from app.health import router as health_router
from app.limits import CountersUnavailableError
from app.simulate import router as simulate_router
from app.webhooks import router as webhooks_router

app = FastAPI(title="self-healing-ecommerce-oms")

# Public GETs are safe to expose cross-origin for the portfolio UI; the webhook,
# simulate, and retry POSTs are not (no preflight is allowed for them).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(webhooks_router)
app.include_router(simulate_router)
app.include_router(api_router)


def _fail_closed(_request: Request, _exc: Exception) -> JSONResponse:
    return JSONResponse(
        {"error": "storage_unavailable", "detail": "fail_closed"},
        status_code=503,
    )


# PRD invariant: when the store is unreachable or unconfigured, refuse (503)
# instead of 500. OperationalError covers connection failures only; constraint
# violations and SQL bugs still surface as 500s. /health stays 200 and reports
# counters_ok=false, so a misconfigured deploy is still discoverable.
app.add_exception_handler(psycopg.OperationalError, _fail_closed)
app.add_exception_handler(PoolTimeout, _fail_closed)
app.add_exception_handler(CountersUnavailableError, _fail_closed)
app.add_exception_handler(StorageUnavailableError, _fail_closed)
