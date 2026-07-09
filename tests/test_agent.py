"""Agent pipeline tests: fallback, call cap, stalled, trace shape."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.agent.llm import LlmClient
from app.agent.trace import make_step, present_incident

from tests.test_github import FakeGitHub

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL required",
)


def _transport_factory(responses: list[Any]):
    """Return a transport that pops scripted replies or raises."""

    queue = list(responses)

    def transport(payload: dict[str, Any], *, base_url: str, served_by: str) -> str:
        if not queue:
            raise RuntimeError("no scripted responses left")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        if callable(item):
            out = item(payload, base_url=base_url, served_by=served_by)
            return str(out)
        return str(item)

    return transport


def _seed_unknown_region_incident() -> uuid.UUID:
    from app import db

    suffix = uuid.uuid4().hex[:8]
    incident = db.create_incident(
        class_="unknown_region",
        status="received",
        fingerprint=f"agent-{suffix}",
        summary="Unknown region XX",
        error_body={"province_code": "XX", "province": "Xanadu"},
        payload={
            "order_number": f"A-{suffix}",
            "shipping_address": {
                "province_code": "XX",
                "province": "Xanadu",
            },
        },
    )
    return incident["id"]


def test_trace_shape_and_ready_to_act() -> None:
    from app.agent.graph import run_diagnosis

    incident_id = _seed_unknown_region_incident()

    def reply(payload: dict[str, Any], **_: Any) -> str:
        content = payload["messages"][0]["content"]
        if "Diagnose" in content:
            return '{"diagnosis": "Missing region mapping for XX", "fixable": true}'
        if "Extract" in content or "recipe parameters" in content:
            return '{"province_code": "XX", "province": "Xanadu"}'
        return '{"class": "unknown_region"}'

    client = LlmClient(
        openrouter_api_key="test",
        groq_api_key="test",
        _transport=_transport_factory([reply, reply, reply]),
    )
    gh = FakeGitHub()
    result = run_diagnosis(incident_id, client=client, github=gh)
    incident = result["incident"]
    assert incident is not None
    assert result["state"].get("outcome") == "pr_opened"
    assert result["state"].get("recipe_params") == {
        "province_code": "XX",
        "province": "Xanadu",
    }
    assert incident["status"] == "pr_opened"
    assert incident["issue_url"]
    assert incident["pr_url"]
    trace = incident["trace"]
    assert len(trace) >= 4
    for step in trace:
        assert set(step) >= {"step", "summary", "served_by", "ms", "at"}
    steps = [s["step"] for s in trace]
    assert "guardrail" in steps
    assert "classify" in steps
    assert "retrieve" in steps
    assert "diagnose" in steps
    assert "extract" in steps
    assert "act" in steps


def test_fallback_chain_served_by() -> None:
    from app.agent.graph import run_diagnosis

    incident_id = _seed_unknown_region_incident()
    calls: list[str] = []

    def transport(payload: dict[str, Any], *, base_url: str, served_by: str) -> str:
        calls.append(served_by)
        if served_by != "fallback":
            raise RuntimeError("primary down")
        content = payload["messages"][0]["content"]
        if "Diagnose" in content:
            return '{"diagnosis": "fallback diagnosis", "fixable": true}'
        return '{"province_code": "XX", "province": "Xanadu"}'

    client = LlmClient(
        openrouter_api_key="test",
        groq_api_key="test",
        _transport=transport,
    )
    result = run_diagnosis(incident_id, client=client, github=FakeGitHub())
    assert result["state"].get("outcome") == "pr_opened"
    assert "fallback" in calls
    diagnose_steps = [
        s for s in result["incident"]["trace"] if s["step"] == "diagnose"
    ]
    assert diagnose_steps
    assert diagnose_steps[0]["served_by"] == "fallback"


def test_llm_call_cap() -> None:
    from app.agent.graph import run_diagnosis

    incident_id = _seed_unknown_region_incident()
    client = LlmClient(
        openrouter_api_key="test",
        groq_api_key="test",
        max_calls=0,
        _transport=_transport_factory([]),
    )
    # With known class, classify is deterministic; diagnose hits cap.
    result = run_diagnosis(incident_id, client=client, github=FakeGitHub())
    assert result["state"].get("outcome") == "diagnosis_failed"
    assert result["incident"]["status"] == "diagnosis_failed"
    assert "llm_call_cap" in str(result["incident"]["error_body"].get("reason", ""))


def test_stalled_lazy_report() -> None:
    from app import db

    suffix = uuid.uuid4().hex[:8]
    incident = db.create_incident(
        class_="unknown_region",
        status="diagnosing",
        fingerprint=f"stall-{suffix}",
        summary="mid-flight",
        error_body={"province_code": "ST"},
        payload={},
    )
    old = (datetime.now(UTC) - timedelta(minutes=6)).isoformat()
    db.append_incident_trace(
        incident["id"],
        make_step(
            "diagnose",
            "partial",
            served_by="test",
            ms=1,
            at=datetime.fromisoformat(old),
        ),
    )
    presented = present_incident(db.get_incident(incident["id"]) or incident)
    assert presented["status"] == "diagnosis_failed"
    assert presented["error_body"]["reason"] == "stalled"


def test_both_providers_down() -> None:
    from app.agent.graph import run_diagnosis

    incident_id = _seed_unknown_region_incident()

    def transport(*_a: Any, **_k: Any) -> str:
        raise RuntimeError("down")

    client = LlmClient(
        openrouter_api_key="test",
        groq_api_key="test",
        _transport=transport,
    )
    result = run_diagnosis(incident_id, client=client, github=FakeGitHub())
    assert result["incident"]["status"] == "diagnosis_failed"


def test_parse_and_validate_helpers() -> None:
    from app.agent.llm import parse_json_object
    from app.agent.schemas import PhoneFormatParams, validate_recipe_params
    from pydantic import ValidationError

    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    params = validate_recipe_params(
        "phone_format",
        {"name": "odd", "pattern": "^BAD", "description": "demo"},
    )
    assert isinstance(params, PhoneFormatParams)
    assert params.name == "odd"
    with pytest.raises(ValidationError):
        validate_recipe_params("unknown_region", {"province_code": ""})
