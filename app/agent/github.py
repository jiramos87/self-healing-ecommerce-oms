"""GitHub REST client for issues, comments, contents, and pull requests."""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

DEFAULT_REPO = "jiramos87/self-healing-ecommerce-oms"
API_BASE = "https://api.github.com"


class GitHubError(Exception):
    """Raised when a GitHub API call fails."""


Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, dict[str, Any]]]


_http: httpx.Client | None = None


def _http_client() -> httpx.Client:
    # One keep-alive client per warm instance; httpx.Client is thread-safe.
    global _http
    if _http is None:
        _http = httpx.Client(timeout=30.0)
    return _http


def _default_transport(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
) -> tuple[int, dict[str, Any]]:
    try:
        resp = _http_client().request(method, url, headers=headers, content=body)
    except httpx.HTTPError as exc:
        raise GitHubError(f"unreachable: {exc}") from exc

    if resp.status_code >= 400:
        detail: dict[str, Any]
        try:
            parsed = resp.json()
            detail = parsed if isinstance(parsed, dict) else {"message": str(parsed)}
        except Exception:  # noqa: BLE001
            detail = {"message": resp.text or resp.reason_phrase}
        raise GitHubError(f"HTTP {resp.status_code}: {detail.get('message', detail)}")

    if not resp.content:
        return resp.status_code, {}
    try:
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise GitHubError(f"invalid JSON response: {exc}") from exc
    if not isinstance(data, dict):
        raise GitHubError("unexpected non-object JSON response")
    return resp.status_code, data


@dataclass
class GitHubClient:
    token: str
    repo: str
    _transport: Transport = _default_transport

    @classmethod
    def from_env(cls, *, transport: Transport | None = None) -> GitHubClient:
        token = os.environ.get("GITHUB_FIX_PAT") or ""
        if not token:
            raise GitHubError("GITHUB_FIX_PAT is not set")
        repo = os.environ.get("GITHUB_REPO") or DEFAULT_REPO
        return cls(token=token, repo=repo, _transport=transport or _default_transport)

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "self-healing-ecommerce-oms-agent",
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{API_BASE}{path}"
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        try:
            _status, data = self._transport(method, url, self._headers(), body)
        except GitHubError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise GitHubError(str(exc)) from exc
        return data

    def get_file(self, path: str, *, ref: str = "main") -> tuple[str, str]:
        """Return (decoded_text, sha) for a file at ref."""
        data = self._request("GET", f"/repos/{self.repo}/contents/{path}?ref={ref}")
        if data.get("encoding") != "base64" or "content" not in data:
            raise GitHubError(f"unexpected contents response for {path}")
        text = base64.b64decode(data["content"]).decode("utf-8")
        sha = str(data["sha"])
        return text, sha

    def get_ref_sha(self, ref: str = "main") -> str:
        data = self._request("GET", f"/repos/{self.repo}/git/ref/heads/{ref}")
        obj = data.get("object") or {}
        sha = obj.get("sha")
        if not sha:
            raise GitHubError(f"missing sha for ref {ref}")
        return str(sha)

    def create_branch(self, branch: str, *, from_sha: str) -> None:
        self._request(
            "POST",
            f"/repos/{self.repo}/git/refs",
            {"ref": f"refs/heads/{branch}", "sha": from_sha},
        )

    def put_file(
        self,
        path: str,
        content: str,
        *,
        message: str,
        branch: str,
        sha: str,
    ) -> dict[str, Any]:
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        return self._request(
            "PUT",
            f"/repos/{self.repo}/contents/{path}",
            {
                "message": message,
                "content": encoded,
                "branch": branch,
                "sha": sha,
            },
        )

    def create_issue(self, *, title: str, body: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/repos/{self.repo}/issues",
            {"title": title, "body": body},
        )

    def create_issue_comment(self, issue_number: int, body: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/repos/{self.repo}/issues/{issue_number}/comments",
            {"body": body},
        )

    def create_pull_request(
        self,
        *,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/repos/{self.repo}/pulls",
            {"title": title, "body": body, "head": head, "base": base},
        )


def issue_title(class_: str, detail: str) -> str:
    return f"[agent] {class_}: {detail}"


def issue_body(
    *,
    class_: str,
    fingerprint: str,
    error_body: dict[str, Any],
    diagnosis: str,
    runbook_path: str,
) -> str:
    error_json = json.dumps(error_body, indent=2, ensure_ascii=False)
    return (
        f"## Error body\n\n```json\n{error_json}\n```\n\n"
        f"## Diagnosis\n\n{diagnosis}\n\n"
        f"## Runbook\n\nCited: `{runbook_path}`\n\n"
        f"## Fingerprint\n\n`{fingerprint}`\n\n"
        "---\n"
        "_Opened by the self-healing OMS agent. Grounded in production ecommerce OMS "
        "experience. A human must merge any fix PR._\n"
    )


def pr_body(*, issue_number: int, fingerprint: str, path: str, summary: str) -> str:
    return (
        f"Fixes #{issue_number}\n\n"
        f"## Change\n\n{summary}\n\n"
        f"## File\n\n`{path}`\n\n"
        f"## Fingerprint\n\n`{fingerprint}`\n\n"
        "Recipe-generated one-line data fix. Human merge required.\n"
    )


def recurrence_comment_body(*, recurrence_count: int, fingerprint: str) -> str:
    return (
        f"Recurrence detected (count={recurrence_count}) for fingerprint `{fingerprint}`. "
        "No new issue or PR; linking this sighting to the existing incident.\n"
    )


def branch_name(fingerprint: str) -> str:
    return f"agent/fix-{fingerprint}"


def parse_issue_number(issue_url: str) -> int | None:
    # https://github.com/owner/repo/issues/123
    parts = issue_url.rstrip("/").split("/")
    if len(parts) >= 2 and parts[-2] == "issues":
        try:
            return int(parts[-1])
        except ValueError:
            return None
    return None
