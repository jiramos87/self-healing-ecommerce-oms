"""GitHub artifact templates, act paths, and recurrence comment tests."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest
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
from app.agent.recipes import PHONE_RULES_PATH, REGIONS_PATH

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL required",
)

ROOT = Path(__file__).resolve().parents[1]


class FakeGitHub:
    """In-memory GitHub stand-in for act/open_artifacts tests."""

    def __init__(
        self,
        *,
        fail_before_issue: bool = False,
        fail_after_issue: bool = False,
        fail_on: str | None = None,
        regions: str | None = None,
        phone_rules: str | None = None,
    ) -> None:
        self.fail_before_issue = fail_before_issue
        self.fail_after_issue = fail_after_issue
        self.fail_on = fail_on
        self.repo = "jiramos87/self-healing-ecommerce-oms"
        self.files = {
            REGIONS_PATH: regions
            or (ROOT / REGIONS_PATH).read_text(encoding="utf-8"),
            PHONE_RULES_PATH: phone_rules
            or (ROOT / PHONE_RULES_PATH).read_text(encoding="utf-8"),
        }
        self.shas = {p: f"sha-{i}" for i, p in enumerate(self.files)}
        self.main_sha = "mainsha"
        self.issues: list[dict[str, Any]] = []
        self.comments: list[dict[str, Any]] = []
        self.prs: list[dict[str, Any]] = []
        self.branches: list[str] = []
        self._issue_n = 0
        self._pr_n = 0

    def get_file(self, path: str, *, ref: str = "main") -> tuple[str, str]:
        if self.fail_on == "get_file":
            raise GitHubError("get_file failed")
        if path not in self.files:
            raise GitHubError(f"missing {path}")
        return self.files[path], self.shas[path]

    def get_ref_sha(self, ref: str = "main") -> str:
        if self.fail_after_issue or self.fail_on == "get_ref_sha":
            raise GitHubError("ref failed")
        return self.main_sha

    def create_branch(self, branch: str, *, from_sha: str) -> None:
        if self.fail_after_issue or self.fail_on == "create_branch":
            raise GitHubError("branch failed")
        self.branches.append(branch)

    def put_file(
        self,
        path: str,
        content: str,
        *,
        message: str,
        branch: str,
        sha: str,
    ) -> dict[str, Any]:
        if self.fail_after_issue or self.fail_on == "put_file":
            raise GitHubError("put_file failed")
        self.files[path] = content
        self.shas[path] = f"sha-{uuid.uuid4().hex[:8]}"
        return {"content": {"path": path}}

    def create_issue(self, *, title: str, body: str) -> dict[str, Any]:
        if self.fail_before_issue or self.fail_on == "create_issue":
            raise GitHubError("unreachable before issue")
        self._issue_n += 1
        issue = {
            "number": self._issue_n,
            "html_url": (
                f"https://github.com/{self.repo}/issues/{self._issue_n}"
            ),
            "title": title,
            "body": body,
        }
        self.issues.append(issue)
        return issue

    def create_issue_comment(self, issue_number: int, body: str) -> dict[str, Any]:
        comment = {"issue_number": issue_number, "body": body}
        self.comments.append(comment)
        return comment

    def create_pull_request(
        self,
        *,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> dict[str, Any]:
        if self.fail_after_issue or self.fail_on == "create_pull_request":
            raise GitHubError("pr failed")
        self._pr_n += 1
        pr = {
            "number": self._pr_n,
            "html_url": f"https://github.com/{self.repo}/pull/{self._pr_n}",
            "title": title,
            "body": body,
            "head": head,
            "base": base,
        }
        self.prs.append(pr)
        return pr


def _seed_incident(**kwargs: Any) -> dict[str, Any]:
    from app import db

    suffix = uuid.uuid4().hex[:8]
    defaults = {
        "class_": "unknown_region",
        "status": "diagnosing",
        "fingerprint": f"fp-{suffix}",
        "summary": "Unknown region QQ",
        "error_body": {"province_code": "QQ", "province": "Quebrada Quimera"},
        "payload": {
            "shipping_address": {
                "province_code": "QQ",
                "province": "Quebrada Quimera",
            }
        },
    }
    defaults.update(kwargs)
    return db.create_incident(**defaults)


def test_issue_and_pr_templates() -> None:
    title = issue_title("unknown_region", "unknown province_code QQ")
    assert title == "[agent] unknown_region: unknown province_code QQ"
    body = issue_body(
        class_="unknown_region",
        fingerprint="abc123",
        error_body={"province_code": "QQ"},
        diagnosis="Missing mapping",
        runbook_path="docs/runbooks/unknown_region.md",
    )
    assert "## Error body" in body
    assert "## Diagnosis" in body
    assert "## Runbook" in body
    assert "`abc123`" in body
    assert "docs/runbooks/unknown_region.md" in body
    assert "production ecommerce OMS experience" in body
    pr = pr_body(
        issue_number=7,
        fingerprint="abc123",
        path=REGIONS_PATH,
        summary="Map QQ",
    )
    assert "Fixes #7" in pr
    assert REGIONS_PATH in pr
    assert branch_name("abc123") == "agent/fix-abc123"
    assert parse_issue_number("https://github.com/o/r/issues/42") == 42
    comment = recurrence_comment_body(recurrence_count=3, fingerprint="abc123")
    assert "count=3" in comment
    assert "abc123" in comment


def test_open_artifacts_happy_path_pr_opened() -> None:
    from app.agent.act import open_artifacts

    incident = _seed_incident()
    gh = FakeGitHub()
    result = open_artifacts(
        incident_id=str(incident["id"]),
        class_="unknown_region",
        fingerprint=incident["fingerprint"],
        error_body=incident["error_body"],
        diagnosis="Missing region QQ",
        recipe_params={"province_code": "QQ", "province": "Quebrada Quimera"},
        runbook_path="docs/runbooks/unknown_region.md",
        client=gh,  # type: ignore[arg-type]
    )
    assert result["outcome"] == "pr_opened"
    assert result["issue_url"]
    assert result["pr_url"]
    assert len(gh.issues) == 1
    assert len(gh.prs) == 1
    assert gh.branches == [f"agent/fix-{incident['fingerprint']}"]
    parsed = json.loads(gh.files[REGIONS_PATH])
    assert parsed["QQ"] == "Quebrada Quimera"
    from app import db

    refreshed = db.get_incident(incident["id"])
    assert refreshed is not None
    assert refreshed["status"] == "pr_opened"
    assert refreshed["issue_url"] == result["issue_url"]
    assert refreshed["pr_url"] == result["pr_url"]


def test_phone_format_pr_title_matches_issue_title() -> None:
    """The PR must name the offending phone, not the recipe's rule name."""
    from app.agent.act import open_artifacts

    incident = _seed_incident(
        class_="phone_format",
        error_body={"phone": "BAD-9001-7"},
        payload={"phone": "BAD-9001-7"},
    )
    gh = FakeGitHub()
    result = open_artifacts(
        incident_id=str(incident["id"]),
        class_="phone_format",
        fingerprint=incident["fingerprint"],
        error_body=incident["error_body"],
        diagnosis="Normalizer has no rule for this shape",
        recipe_params={
            "name": "bad_prefix_rule",
            "pattern": "^BAD-\\d+-\\d+$",
            "description": "demo",
        },
        client=gh,  # type: ignore[arg-type]
    )
    assert result["outcome"] == "pr_opened"
    assert gh.issues[0]["title"] == gh.prs[0]["title"]
    assert "BAD-9001-7" in gh.prs[0]["title"]
    assert "bad_prefix_rule" not in gh.prs[0]["title"]


def test_github_unreachable_before_issue() -> None:
    from app.agent.act import open_artifacts

    incident = _seed_incident()
    gh = FakeGitHub(fail_before_issue=True)
    result = open_artifacts(
        incident_id=str(incident["id"]),
        class_="unknown_region",
        fingerprint=incident["fingerprint"],
        error_body=incident["error_body"],
        diagnosis="Missing region QQ",
        recipe_params={"province_code": "QQ", "province": "Quebrada Quimera"},
        client=gh,  # type: ignore[arg-type]
    )
    assert result["outcome"] == "diagnosis_failed"
    assert result["issue_url"] is None
    from app import db

    refreshed = db.get_incident(incident["id"])
    assert refreshed is not None
    assert refreshed["status"] == "diagnosis_failed"
    assert "github_before_issue" in str(refreshed["error_body"].get("reason", ""))
    # Diagnosis preserved in summary
    assert refreshed["summary"] == "Missing region QQ"


def test_github_unreachable_after_issue() -> None:
    from app.agent.act import open_artifacts

    incident = _seed_incident()
    gh = FakeGitHub(fail_after_issue=True)
    result = open_artifacts(
        incident_id=str(incident["id"]),
        class_="unknown_region",
        fingerprint=incident["fingerprint"],
        error_body=incident["error_body"],
        diagnosis="Missing region QQ",
        recipe_params={"province_code": "QQ", "province": "Quebrada Quimera"},
        client=gh,  # type: ignore[arg-type]
    )
    assert result["outcome"] == "issue_only"
    assert result["issue_url"]
    assert result["pr_url"] is None
    from app import db

    refreshed = db.get_incident(incident["id"])
    assert refreshed is not None
    assert refreshed["status"] == "issue_only"
    assert "github_after_issue" in str(refreshed["error_body"].get("reason", ""))


def test_recipe_gate_violation_lands_issue_only() -> None:
    from app.agent.act import open_artifacts
    from app.agent.recipes import RecipeChange, gate_change

    # Force a bad change via monkeypatch of apply_recipe
    incident = _seed_incident()
    gh = FakeGitHub()

    import app.agent.act as act_mod

    original = act_mod.apply_recipe

    def bad_apply(*_a: Any, **_k: Any) -> RecipeChange:
        return RecipeChange(
            path="app/main.py",
            old_content="x\n",
            new_content="x\ny\n",
        )

    act_mod.apply_recipe = bad_apply  # type: ignore[assignment]
    try:
        result = open_artifacts(
            incident_id=str(incident["id"]),
            class_="unknown_region",
            fingerprint=incident["fingerprint"],
            error_body=incident["error_body"],
            diagnosis="Missing region QQ",
            recipe_params={"province_code": "QQ", "province": "Quebrada Quimera"},
            client=gh,  # type: ignore[arg-type]
        )
    finally:
        act_mod.apply_recipe = original  # type: ignore[assignment]

    assert result["outcome"] == "issue_only"
    assert result.get("violated_rule") == "allowlist"
    from app import db

    refreshed = db.get_incident(incident["id"])
    assert refreshed is not None
    assert refreshed["status"] == "issue_only"
    assert "recipe_gate:allowlist" in str(refreshed["error_body"].get("reason", ""))
    # Confirm gate itself names the rule
    gate = gate_change(
        RecipeChange(path="app/main.py", old_content="x\n", new_content="x\ny\n"),
        class_="unknown_region",
        params={"province_code": "QQ", "province": "Quebrada Quimera"},
    )
    assert gate.violated_rule == "allowlist"


def test_recurrence_comment_on_existing_issue() -> None:
    from app import db
    from app.agent.act import comment_on_recurrence

    incident = _seed_incident(status="pr_opened")
    incident = db.update_incident(
        incident["id"],
        status="pr_opened",
        issue_url="https://github.com/jiramos87/self-healing-ecommerce-oms/issues/9",
    )
    updated = db.record_recurrence(incident["id"])
    gh = FakeGitHub()
    comment = comment_on_recurrence(updated, client=gh)  # type: ignore[arg-type]
    assert comment is not None
    assert len(gh.comments) == 1
    assert gh.comments[0]["issue_number"] == 9
    assert "Recurrence" in gh.comments[0]["body"]


def test_github_client_request_shapes() -> None:
    calls: list[tuple[str, str]] = []

    def transport(
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
    ) -> tuple[int, dict[str, Any]]:
        calls.append((method, urlparse(url).path))
        assert "Authorization" in headers
        if method == "POST" and url.endswith("/issues"):
            return 201, {"number": 1, "html_url": "https://github.com/o/r/issues/1"}
        return 200, {}

    client = GitHubClient(token="t", repo="o/r", _transport=transport)
    issue = client.create_issue(title="t", body="b")
    assert issue["number"] == 1
    assert ("POST", "/repos/o/r/issues") in calls
