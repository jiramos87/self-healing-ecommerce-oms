"""B11: the demo dashboard is served at / and the read API stays intact.

These run without a database: the dashboard is static, and the endpoint-path
guard inspects the router. Response shapes are covered in test_api.py.
"""

from __future__ import annotations

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)

SIMULATE_CLASSES = [
    "valid",
    "unknown_region",
    "phone_format",
    "duplicate_delivery",
    "cancelled_order",
]


def test_root_serves_dashboard_html() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    assert "<!doctype html>" in body.lower()
    assert "Self-healing OMS" in body
    # All five simulate controls are present and target the real endpoint.
    for cls in SIMULATE_CLASSES:
        assert f'data-class="{cls}"' in body
    assert "/demo/simulate" in body


def test_dashboard_exposes_no_admin_or_secret_surface() -> None:
    body = client.get("/").text.lower()
    # The public page must never carry the admin retry path or any token field.
    assert "/retry" not in body
    assert "x-admin-token" not in body
    assert "admin_token" not in body
    assert "webhook_secret" not in body


def test_dashboard_has_no_external_runtime_hosts() -> None:
    # CSP-friendly: assets are inline or data URIs, nothing loaded off-host.
    body = client.get("/").text
    assert 'src="http' not in body
    assert 'href="http' not in body
    assert "@import" not in body
    assert "cdn" not in body.lower()


def test_read_api_paths_unchanged() -> None:
    """The launch gate and any external consumer depend on these paths."""
    routes = {
        (path, method)
        for route in app.routes
        for path in [getattr(route, "path", None)]
        if path is not None
        for method in getattr(route, "methods", set()) or set()
    }
    assert ("/", "GET") in routes
    assert ("/health", "GET") in routes
    assert ("/incidents", "GET") in routes
    assert ("/incidents/{incident_id}", "GET") in routes
    assert ("/orders", "GET") in routes
    assert ("/demo/simulate", "POST") in routes
    assert ("/webhooks/orders", "POST") in routes
    assert ("/incidents/{incident_id}/retry", "POST") in routes
