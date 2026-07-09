"""Incident status constants: the single home for the PRD status enum."""

from __future__ import annotations

RECEIVED = "received"
DIAGNOSING = "diagnosing"
ISSUE_OPENED = "issue_opened"
PR_OPENED = "pr_opened"
ISSUE_ONLY = "issue_only"
DUPLICATE = "duplicate"
EXPECTED_BEHAVIOR = "expected_behavior"
DIAGNOSIS_FAILED = "diagnosis_failed"

TERMINAL_STATUSES = frozenset(
    {PR_OPENED, ISSUE_ONLY, DUPLICATE, EXPECTED_BEHAVIOR, DIAGNOSIS_FAILED}
)

# Terminal outcome for classes the agent deliberately does not act on.
NO_AGENT_TERMINAL: dict[str, str] = {
    "cancelled_order": EXPECTED_BEHAVIOR,
    "duplicate_delivery": DUPLICATE,
}
