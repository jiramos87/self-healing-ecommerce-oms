"""LangGraph diagnosis pipeline through the act step.

build_graph(client, github) returns a compiled graph whose nodes close over
the per-run clients: concurrent diagnoses each get their own LLM call budget
and GitHub client, with no shared mutable state between runs.
"""

from __future__ import annotations

import json
import time
from typing import Any, NotRequired, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from app import db, statuses
from app.agent.llm import (
    CLASSIFY_MODEL,
    DIAGNOSE_MODEL,
    LlmClient,
    LlmError,
    parse_json_object,
)
from app.agent.schemas import (
    FIXABLE_CLASSES,
    NO_AGENT_CLASSES,
    validate_recipe_params,
)
from app.agent.trace import make_step, persist_step
from app.kb import retrieve_runbook


class AgentState(TypedDict):
    incident_id: str
    class_: str
    payload: dict[str, Any]
    error_body: dict[str, Any]
    summary: str
    runbook_path: NotRequired[str]
    runbook_content: NotRequired[str]
    diagnosis: NotRequired[str]
    recipe_params: NotRequired[dict[str, Any] | None]
    outcome: NotRequired[str]
    failure_reason: NotRequired[str | None]
    ready_to_act: NotRequired[bool]


_ROUTE_END_OUTCOMES = frozenset(
    {statuses.EXPECTED_BEHAVIOR, statuses.DUPLICATE, statuses.DIAGNOSIS_FAILED}
)

KNOWN_CLASSES = FIXABLE_CLASSES | NO_AGENT_CLASSES


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _fail(
    incident_id: str,
    state: AgentState,
    *,
    step_name: str,
    message: str,
    reason: str,
    ms: int,
) -> dict[str, Any]:
    """Record a terminal diagnosis failure: trace step + status + outcome."""
    persist_step(
        incident_id,
        make_step(step_name, message, served_by="none", ms=ms),
    )
    db.update_incident(
        UUID(incident_id),
        status=statuses.DIAGNOSIS_FAILED,
        error_body={
            **(state.get("error_body") or {}),
            "reason": reason,
        },
    )
    return {
        "outcome": statuses.DIAGNOSIS_FAILED,
        "failure_reason": reason,
        "ready_to_act": False,
    }


def _extract_once(
    client: LlmClient, state: AgentState, *, reask: bool
) -> dict[str, Any]:
    class_ = state.get("class_") or ""
    hint = ""
    if class_ == "unknown_region":
        hint = (
            'Schema: {"province_code": string, "province": string}. '
            "Use error_body / shipping_address values verbatim."
        )
    elif class_ == "phone_format":
        hint = (
            'Schema: {"name": string, "pattern": regex string, "description": string}. '
            "Pattern must match the offending phone."
        )
    reask_note = " Previous output was invalid; return corrected JSON only." if reask else ""
    prompt = (
        f"Extract typed recipe parameters for class {class_}. "
        f"Reply with JSON only. {hint}{reask_note}\n"
        f"error_body={json.dumps(state.get('error_body') or {})}\n"
        f"payload={json.dumps(state.get('payload') or {})}\n"
        f"diagnosis={state.get('diagnosis') or ''}"
    )
    result = client.chat(
        messages=[{"role": "user", "content": prompt}],
        model=DIAGNOSE_MODEL,
    )
    params = parse_json_object(result.text)
    validated = validate_recipe_params(class_, params)
    return {
        "params": validated.model_dump(),
        "served_by": result.served_by,
        "ms": result.ms,
    }


def build_graph(client: LlmClient, github: Any | None = None) -> Any:
    """Compile the pipeline with nodes closed over this run's clients."""

    def guardrail_node(state: AgentState) -> dict[str, Any]:
        started = time.perf_counter()
        class_ = state.get("class_") or ""
        incident_id = state["incident_id"]
        db.update_incident(UUID(incident_id), status=statuses.DIAGNOSING)

        no_agent_outcome = statuses.NO_AGENT_TERMINAL.get(class_)
        if no_agent_outcome is not None:
            persist_step(
                incident_id,
                make_step(
                    "guardrail",
                    f"No agent run for class {class_}",
                    served_by="deterministic",
                    ms=_ms(started),
                ),
            )
            db.update_incident(UUID(incident_id), status=no_agent_outcome)
            return {
                "outcome": no_agent_outcome,
                "ready_to_act": False,
                "failure_reason": None,
            }

        persist_step(
            incident_id,
            make_step(
                "guardrail",
                f"Proceeding with diagnosis for {class_ or 'unclassified'}",
                served_by="deterministic",
                ms=_ms(started),
            ),
        )
        return {"outcome": "diagnosing", "ready_to_act": False}

    def classify_node(state: AgentState) -> dict[str, Any]:
        started = time.perf_counter()
        incident_id = state["incident_id"]
        known = state.get("class_") or ""

        # Prefer the stored class when already set by ingestion.
        if known in KNOWN_CLASSES:
            persist_step(
                incident_id,
                make_step(
                    "classify",
                    f"Using ingestion class {known}",
                    served_by="deterministic",
                    ms=_ms(started),
                ),
            )
            return {"class_": known}

        prompt = (
            "Classify this ecommerce OMS incident. "
            "Reply with JSON only: {\"class\": one of "
            "[\"unknown_region\",\"phone_format\",\"duplicate_delivery\",\"cancelled_order\"]}.\n"
            f"error_body={json.dumps(state.get('error_body') or {})}\n"
            f"summary={state.get('summary') or ''}"
        )
        try:
            result = client.chat(
                messages=[{"role": "user", "content": prompt}],
                model=CLASSIFY_MODEL,
            )
            parsed = parse_json_object(result.text)
        except LlmError as exc:
            return _fail(
                incident_id,
                state,
                step_name="classify",
                message=f"Classification failed: {exc}",
                reason=str(exc),
                ms=_ms(started),
            )

        class_ = str(parsed.get("class") or "")
        if class_ not in KNOWN_CLASSES:
            # Never accept an out-of-vocabulary label: it would leave the
            # incident without a terminal status downstream.
            return _fail(
                incident_id,
                state,
                step_name="classify",
                message=f"Unclassifiable result {class_ or '(empty)'}",
                reason=f"unclassifiable:{class_ or 'empty'}",
                ms=result.ms,
            )
        persist_step(
            incident_id,
            make_step(
                "classify",
                f"Classified as {class_}",
                served_by=result.served_by,
                ms=result.ms,
            ),
        )
        return {"class_": class_}

    def retrieve_node(state: AgentState) -> dict[str, Any]:
        started = time.perf_counter()
        incident_id = state["incident_id"]
        class_ = state.get("class_") or "unknown_region"
        runbook = retrieve_runbook(class_)
        persist_step(
            incident_id,
            make_step(
                "retrieve",
                f"Retrieved {runbook['path']}",
                served_by="deterministic",
                ms=_ms(started),
            ),
        )
        return {
            "runbook_path": runbook["path"],
            "runbook_content": runbook["content"],
        }

    def diagnose_node(state: AgentState) -> dict[str, Any]:
        if state.get("outcome") == statuses.DIAGNOSIS_FAILED:
            return {}
        started = time.perf_counter()
        incident_id = state["incident_id"]
        prompt = (
            "Diagnose this OMS ingestion failure using the runbook. "
            "Reply with JSON only: {\"diagnosis\": string, \"fixable\": boolean}.\n"
            f"class={state.get('class_')}\n"
            f"error_body={json.dumps(state.get('error_body') or {})}\n"
            f"runbook={state.get('runbook_content') or ''}"
        )
        try:
            result = client.chat(
                messages=[{"role": "user", "content": prompt}],
                model=DIAGNOSE_MODEL,
            )
            parsed = parse_json_object(result.text)
        except LlmError as exc:
            return _fail(
                incident_id,
                state,
                step_name="diagnose",
                message=f"Diagnosis failed: {exc}",
                reason=str(exc),
                ms=_ms(started),
            )
        diagnosis = str(parsed.get("diagnosis") or result.text.strip())
        persist_step(
            incident_id,
            make_step(
                "diagnose",
                diagnosis[:240],
                served_by=result.served_by,
                ms=result.ms,
            ),
        )
        return {"diagnosis": diagnosis}

    def extract_node(state: AgentState) -> dict[str, Any]:
        if state.get("outcome") == statuses.DIAGNOSIS_FAILED:
            return {}
        class_ = state.get("class_") or ""
        incident_id = state["incident_id"]
        if class_ not in FIXABLE_CLASSES:
            # Defensive: guardrail/classify already terminalize other classes.
            return _fail(
                incident_id,
                state,
                step_name="extract",
                message=f"No recipe for class {class_}",
                reason=f"no_recipe:{class_ or 'empty'}",
                ms=0,
            )

        try:
            extracted = _extract_once(client, state, reask=False)
        except Exception as first_exc:  # noqa: BLE001
            try:
                extracted = _extract_once(client, state, reask=True)
            except Exception as second_exc:  # noqa: BLE001
                return _fail(
                    incident_id,
                    state,
                    step_name="extract",
                    message=(
                        f"Extraction failed: {first_exc}; reask failed: {second_exc}"
                    ),
                    reason=f"extract_failed:{second_exc}",
                    ms=0,
                )

        persist_step(
            incident_id,
            make_step(
                "extract",
                f"Extracted params {json.dumps(extracted['params'])[:200]}",
                served_by=extracted["served_by"],
                ms=extracted["ms"],
            ),
        )
        return {
            "recipe_params": extracted["params"],
            "ready_to_act": True,
            "outcome": "ready_to_act",
        }

    def act_node(state: AgentState) -> dict[str, Any]:
        """Open GitHub issue + gated fix PR (or degrade per PRD failure paths)."""
        started = time.perf_counter()
        incident_id = state["incident_id"]
        if state.get("outcome") == statuses.DIAGNOSIS_FAILED:
            return {}
        if not state.get("ready_to_act"):
            persist_step(
                incident_id,
                make_step(
                    "act",
                    "Act skipped (not ready)",
                    served_by="deterministic",
                    ms=_ms(started),
                ),
            )
            return {}

        from app.agent.act import open_artifacts

        incident = db.get_incident(UUID(incident_id))
        if incident is None:
            return {
                "outcome": statuses.DIAGNOSIS_FAILED,
                "failure_reason": "incident_missing",
            }

        result = open_artifacts(
            incident_id=incident_id,
            class_=state.get("class_") or incident["class"],
            fingerprint=str(incident["fingerprint"]),
            error_body=state.get("error_body") or incident.get("error_body") or {},
            diagnosis=state.get("diagnosis") or state.get("summary") or "",
            recipe_params=state.get("recipe_params") or {},
            runbook_path=state.get("runbook_path"),
            client=github,
        )
        return {
            "outcome": result["outcome"],
            "failure_reason": result.get("failure_reason"),
            "ready_to_act": False,
        }

    def _route_or_end(next_node: str) -> Any:
        def route(state: AgentState) -> str:
            if state.get("outcome") in _ROUTE_END_OUTCOMES:
                return "end"
            return next_node

        return route

    graph: StateGraph = StateGraph(AgentState)
    graph.add_node("guardrail", guardrail_node)
    graph.add_node("classify", classify_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("diagnose", diagnose_node)
    graph.add_node("extract", extract_node)
    graph.add_node("act", act_node)

    graph.add_edge(START, "guardrail")
    graph.add_conditional_edges(
        "guardrail",
        _route_or_end("classify"),
        {"classify": "classify", "end": END},
    )
    graph.add_conditional_edges(
        "classify",
        _route_or_end("retrieve"),
        {"retrieve": "retrieve", "end": END},
    )
    graph.add_edge("retrieve", "diagnose")
    graph.add_conditional_edges(
        "diagnose",
        _route_or_end("extract"),
        {"extract": "extract", "end": END},
    )
    graph.add_edge("extract", "act")
    graph.add_edge("act", END)
    return graph.compile()


def run_diagnosis(
    incident_id: UUID,
    *,
    client: LlmClient | None = None,
    github: Any | None = None,
) -> dict[str, Any]:
    incident = db.get_incident(incident_id)
    if incident is None:
        raise ValueError(f"incident not found: {incident_id}")

    graph = build_graph(client or LlmClient.from_env(), github)
    initial: AgentState = {
        "incident_id": str(incident_id),
        "class_": incident["class"],
        "payload": incident.get("payload") or {},
        "error_body": incident.get("error_body") or {},
        "summary": incident.get("summary") or "",
        "ready_to_act": False,
    }
    result = graph.invoke(initial)
    refreshed = db.get_incident(incident_id)
    return {
        "state": result,
        "incident": refreshed,
    }
