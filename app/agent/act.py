"""Act step: open GitHub issue + gated one-line fix PR from typed recipes."""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from app import db, statuses
from app.agent.github import (
    GitHubClient,
    GitHubError,
    branch_name,
    issue_body,
    issue_title,
    parse_issue_number,
    pr_body,
    recurrence_comment_body,
)
from app.agent.recipes import (
    RECIPE_PATHS,
    RecipeChange,
    apply_recipe,
    gate_change,
)
from app.agent.trace import make_step, persist_step
from app.kb import retrieve_runbook


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _detail_for_title(class_: str, params: dict[str, Any], error_body: dict[str, Any]) -> str:
    if class_ == "unknown_region":
        code = params.get("province_code") or error_body.get("province_code") or "?"
        return f"unknown province_code {code}"
    if class_ == "phone_format":
        phone = error_body.get("phone") or params.get("name") or "?"
        return f"unparseable phone {phone}"
    return class_


def _change_summary(class_: str, params: dict[str, Any]) -> str:
    if class_ == "unknown_region":
        return (
            f"Map `{params.get('province_code')}` to "
            f"`{params.get('province')}` in regions.json."
        )
    if class_ == "phone_format":
        return f"Append phone rule `{params.get('name')}` to phone_rules.json."
    return "Recipe data fix."


def _issue_only(
    incident_id: str,
    *,
    issue_url: str,
    error_body: dict[str, Any],
    recipe_params: dict[str, Any],
    message: str,
    reason: str,
    failure_reason: str,
    started: float,
    served_by: str = "github",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Shared degrade path: keep the issue, skip the PR, record why."""
    persist_step(
        incident_id,
        make_step("act", message, served_by=served_by, ms=_ms(started)),
    )
    db.update_incident(
        UUID(incident_id),
        status=statuses.ISSUE_ONLY,
        issue_url=issue_url,
        error_body={
            **error_body,
            "recipe_params": recipe_params,
            "reason": reason,
        },
    )
    result: dict[str, Any] = {
        "outcome": statuses.ISSUE_ONLY,
        "failure_reason": failure_reason,
        "issue_url": issue_url,
        "pr_url": None,
    }
    if extra:
        result.update(extra)
    return result


def open_artifacts(
    *,
    incident_id: str,
    class_: str,
    fingerprint: str,
    error_body: dict[str, Any],
    diagnosis: str,
    recipe_params: dict[str, Any],
    runbook_path: str | None = None,
    client: GitHubClient | None = None,
) -> dict[str, Any]:
    """Create issue + (if gate passes) PR. Updates incident status and URLs."""
    started = time.perf_counter()
    gh = client or GitHubClient.from_env()
    runbook = runbook_path or retrieve_runbook(class_)["path"]
    detail = _detail_for_title(class_, recipe_params, error_body)
    title = issue_title(class_, detail)
    body = issue_body(
        class_=class_,
        fingerprint=fingerprint,
        error_body=error_body,
        diagnosis=diagnosis,
        runbook_path=runbook,
    )

    # --- Issue creation (failure => diagnosis_failed, diagnosis preserved) ---
    try:
        issue = gh.create_issue(title=title, body=body)
    except GitHubError as exc:
        persist_step(
            incident_id,
            make_step(
                "act",
                f"GitHub unreachable before issue: {exc}",
                served_by="github",
                ms=_ms(started),
            ),
        )
        db.update_incident(
            UUID(incident_id),
            status=statuses.DIAGNOSIS_FAILED,
            summary=diagnosis,
            error_body={
                **error_body,
                "recipe_params": recipe_params,
                "reason": f"github_before_issue:{exc}",
            },
        )
        return {
            "outcome": statuses.DIAGNOSIS_FAILED,
            "failure_reason": str(exc),
            "issue_url": None,
            "pr_url": None,
        }

    issue_url = str(issue.get("html_url") or "")
    issue_number = int(issue.get("number") or 0)
    db.update_incident(
        UUID(incident_id),
        status=statuses.ISSUE_OPENED,
        summary=diagnosis,
        issue_url=issue_url,
        error_body={**error_body, "recipe_params": recipe_params},
    )
    persist_step(
        incident_id,
        make_step(
            "act",
            f"Opened issue #{issue_number}",
            served_by="github",
            ms=_ms(started),
        ),
    )

    # --- Build recipe change + gate (fetch only the recipe's target file) ---
    try:
        path = RECIPE_PATHS[class_]
        text, file_sha = gh.get_file(path)
        change = apply_recipe(class_, recipe_params, file_contents={path: text})
        gate = gate_change(change, class_=class_, params=recipe_params)
    except (GitHubError, ValueError, KeyError) as exc:
        return _issue_only(
            incident_id,
            issue_url=issue_url,
            error_body=error_body,
            recipe_params=recipe_params,
            message=f"PR preparation failed after issue: {exc}",
            reason=f"github_after_issue:{exc}",
            failure_reason=str(exc),
            started=started,
        )

    if not gate.ok:
        rule = gate.violated_rule or "unknown"
        return _issue_only(
            incident_id,
            issue_url=issue_url,
            error_body=error_body,
            recipe_params=recipe_params,
            message=f"Recipe gate violated: {rule}",
            reason=f"recipe_gate:{rule}",
            failure_reason=f"recipe_gate:{rule}",
            started=started,
            served_by="deterministic",
            extra={"violated_rule": rule},
        )

    # --- Branch + contents + PR ---
    try:
        pr_url = _open_pr(
            gh,
            change=change,
            file_sha=file_sha,
            fingerprint=fingerprint,
            issue_number=issue_number,
            class_=class_,
            params=recipe_params,
            error_body=error_body,
        )
    except GitHubError as exc:
        return _issue_only(
            incident_id,
            issue_url=issue_url,
            error_body=error_body,
            recipe_params=recipe_params,
            message=f"PR creation failed after issue: {exc}",
            reason=f"github_after_issue:{exc}",
            failure_reason=str(exc),
            started=started,
        )

    persist_step(
        incident_id,
        make_step(
            "act",
            f"Opened PR for {change.path}",
            served_by="github",
            ms=_ms(started),
        ),
    )
    db.update_incident(
        UUID(incident_id),
        status=statuses.PR_OPENED,
        summary=diagnosis,
        issue_url=issue_url,
        pr_url=pr_url,
        error_body={**error_body, "recipe_params": recipe_params},
    )
    return {
        "outcome": statuses.PR_OPENED,
        "failure_reason": None,
        "issue_url": issue_url,
        "pr_url": pr_url,
    }


def _open_pr(
    gh: GitHubClient,
    *,
    change: RecipeChange,
    file_sha: str,
    fingerprint: str,
    issue_number: int,
    class_: str,
    params: dict[str, Any],
    error_body: dict[str, Any],
) -> str:
    base_sha = gh.get_ref_sha("main")
    branch = branch_name(fingerprint)
    branch_reused = False
    try:
        gh.create_branch(branch, from_sha=base_sha)
    except GitHubError as exc:
        # Branch may already exist from a prior attempt; continue if so.
        if "Reference already exists" not in str(exc):
            raise
        branch_reused = True
    if branch_reused:
        # A prior attempt may have committed to the branch; refresh the sha.
        _text, file_sha = gh.get_file(change.path, ref=branch)
    message = f"fix({class_}): {_change_summary(class_, params)}"
    gh.put_file(
        change.path,
        change.new_content,
        message=message,
        branch=branch,
        sha=file_sha,
    )
    pr = gh.create_pull_request(
        # Same detail as the issue title: an empty error_body here would fall
        # back to the recipe's rule name and mislabel phone_format PRs.
        title=issue_title(class_, _detail_for_title(class_, params, error_body)),
        body=pr_body(
            issue_number=issue_number,
            fingerprint=fingerprint,
            path=change.path,
            summary=_change_summary(class_, params),
        ),
        head=branch,
        base="main",
    )
    return str(pr.get("html_url") or "")


def comment_on_recurrence(
    incident: dict[str, Any],
    *,
    client: GitHubClient | None = None,
) -> dict[str, Any] | None:
    """Post a recurrence comment on the existing issue when one exists."""
    issue_url = incident.get("issue_url")
    if not issue_url:
        return None
    number = parse_issue_number(str(issue_url))
    if number is None:
        return None
    try:
        gh = client or GitHubClient.from_env()
        body = recurrence_comment_body(
            recurrence_count=int(incident.get("recurrence_count") or 0),
            fingerprint=str(incident.get("fingerprint") or ""),
        )
        return gh.create_issue_comment(number, body)
    except GitHubError:
        # Recurrence comment is best-effort; count already incremented in DB.
        return None
