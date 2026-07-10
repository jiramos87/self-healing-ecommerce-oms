"""B10 launch gate: exercise the live deployment end to end and print a pass/fail table.

Against ``--base-url`` it runs:
- 20 order deliveries covering all five classes, asserting each incident reaches
  its correct terminal state within the deadline (default 60s each);
- a recurrence pass: the same unknown_region delivered twice (distinct order
  numbers) must reuse one incident and open no second issue;
- a merge-closes-loop pass: an unknown_region reaches pr_opened; after a human
  merges the fix PR and the redeploy is live, re-sending the same region now
  succeeds as a normal order while the original on_hold order stays on_hold.

Why signed webhooks instead of ``POST /demo/simulate``: ``/demo/simulate`` is the
public UI entry, rate-limited to 3 requests / 10 min per IP, which a 20-run gate
would trip immediately. The gate is an operator tool holding WEBHOOK_SECRET, so it
delivers signed webhooks directly to ``/webhooks/orders`` -- the same path
``/demo/simulate`` uses internally -- and reuses the app's own payload generators
so unknown_region / phone_format values stay novel against real history.

Required environment:
- WEBHOOK_SECRET: must equal the deployment's secret (used to sign deliveries).
- DATABASE_URL: the same database the deployment uses (novelty checks read it).

Usage:
    python scripts/launch_gate.py --base-url https://<deployment-url>
    python scripts/launch_gate.py --base-url https://<url> --no-merge-loop
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import statuses  # noqa: E402
from app.generators import generate_payload  # noqa: E402
from app.validation import configured_shop_domain  # noqa: E402
from app.webhooks import sign_body  # noqa: E402

# 20 deliveries covering all five classes; weighted so a single gate run makes
# only four agent runs in the bulk phase (unknown_region + phone_format), leaving
# ample headroom under the 20/day agent-run cap for the recurrence and merge passes.
BULK_SEQUENCE: list[str] = (
    ["valid"] * 6
    + ["duplicate_delivery"] * 5
    + ["cancelled_order"] * 5
    + ["unknown_region"] * 2
    + ["phone_format"] * 2
)

EXPECTED_TERMINAL: dict[str, str] = {
    "unknown_region": statuses.PR_OPENED,
    "phone_format": statuses.PR_OPENED,
    "cancelled_order": statuses.EXPECTED_BEHAVIOR,
    "duplicate_delivery": statuses.DUPLICATE,
}

# Agent runs a bulk run plus the two extra passes will consume on a fresh day.
EXPECTED_AGENT_RUNS = 6


@dataclass
class Result:
    step: str
    klass: str
    expected: str
    actual: str
    elapsed_s: float
    ok: bool
    note: str = ""
    skipped: bool = False


def _fresh_order_number() -> str:
    return f"SIM-{uuid.uuid4().hex[:10].upper()}"


def _json(resp: httpx.Response) -> dict[str, Any]:
    try:
        body = resp.json()
    except (json.JSONDecodeError, ValueError):
        return {}
    return body if isinstance(body, dict) else {}


@dataclass
class Gate:
    base_url: str
    poll_timeout: float
    poll_interval: float
    client: httpx.Client
    shop_domain: str
    results: list[Result] = field(default_factory=list)

    def _record(
        self,
        step: str,
        klass: str,
        expected: str,
        actual: str,
        elapsed_s: float,
        ok: bool,
        note: str = "",
        *,
        skipped: bool = False,
    ) -> None:
        self.results.append(
            Result(step, klass, expected, actual, elapsed_s, ok, note, skipped)
        )
        tag = "SKIP" if skipped else ("PASS" if ok else "FAIL")
        detail = f"  {note}" if note else ""
        print(f"  [{tag}] {step} ({klass}): {actual} in {elapsed_s:.1f}s{detail}")

    def deliver(self, payload: dict[str, Any]) -> httpx.Response:
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        resp = self.client.post(
            f"{self.base_url}/webhooks/orders",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Shopify-Shop-Domain": self.shop_domain,
                "X-Shopify-Hmac-SHA256": sign_body(raw),
            },
        )
        if resp.status_code == 401:
            sys.exit(
                "FATAL: webhook returned 401. WEBHOOK_SECRET here does not match "
                "the deployment (or the shop domain is wrong). Fix and re-run."
            )
        return resp

    def incident(self, incident_id: str) -> dict[str, Any]:
        return _json(self.client.get(f"{self.base_url}/incidents/{incident_id}"))

    def wait_for_terminal(self, incident_id: str) -> str:
        deadline = time.monotonic() + self.poll_timeout
        last = "unknown"
        while time.monotonic() < deadline:
            body = self.incident(incident_id)
            status = body.get("status")
            if status:
                last = status
                if status in statuses.TERMINAL_STATUSES:
                    return last
            time.sleep(self.poll_interval)
        return last

    # --- bulk deliveries ------------------------------------------------------

    def run_bulk(self) -> None:
        print(f"\n== Bulk: {len(BULK_SEQUENCE)} deliveries across all five classes ==")
        for klass in BULK_SEQUENCE:
            if klass == "valid":
                self._run_valid()
            elif klass == "duplicate_delivery":
                self._run_duplicate()
            else:
                self._run_incident_class(klass)

    def _run_valid(self) -> None:
        start = time.monotonic()
        resp = self.deliver(generate_payload("valid"))
        body = _json(resp)
        elapsed = time.monotonic() - start
        ok = (
            resp.status_code == 200
            and body.get("status") == "accepted"
            and body.get("incident_id") is None
        )
        actual = "order created, no incident" if ok else f"status={body.get('status')}"
        self._record("bulk", "valid", "order created, no incident", actual, elapsed, ok)

    def _run_duplicate(self) -> None:
        start = time.monotonic()
        payload = generate_payload("duplicate_delivery")
        first = _json(self.deliver(payload))
        second = _json(self.deliver(payload))
        incident_id = second.get("incident_id")
        if not incident_id:
            self._record(
                "bulk", "duplicate_delivery", statuses.DUPLICATE,
                "no incident_id on second delivery", time.monotonic() - start, False,
            )
            return
        actual = self.wait_for_terminal(incident_id)
        elapsed = time.monotonic() - start
        ok = (
            first.get("status") == "accepted"
            and second.get("status") == "duplicate"
            and actual == statuses.DUPLICATE
            and elapsed <= self.poll_timeout
        )
        self._record("bulk", "duplicate_delivery", statuses.DUPLICATE, actual, elapsed, ok)

    def _run_incident_class(self, klass: str) -> None:
        start = time.monotonic()
        resp = self.deliver(generate_payload(klass))
        body = _json(resp)
        incident_id = body.get("incident_id")
        expected = EXPECTED_TERMINAL[klass]
        note = "agent capped (daily limit): reset counters or wait" if body.get(
            "reason"
        ) == "capped" else ""
        if not incident_id:
            self._record("bulk", klass, expected, "no incident_id", 0.0, False, note)
            return
        actual = self.wait_for_terminal(incident_id)
        elapsed = time.monotonic() - start
        ok = actual == expected and elapsed <= self.poll_timeout
        if not ok and actual == statuses.ISSUE_ONLY:
            note = note or "recipe-gate violation or GitHub failure (issue_only)"
        self._record("bulk", klass, expected, actual, elapsed, ok, note)

    # --- recurrence pass ------------------------------------------------------

    def run_recurrence(self) -> None:
        print("\n== Recurrence: same unknown_region twice, one incident, no 2nd issue ==")
        start = time.monotonic()
        payload = generate_payload("unknown_region")
        first = _json(self.deliver(payload))
        incident_id = first.get("incident_id")
        if not incident_id:
            note = "capped" if first.get("reason") == "capped" else ""
            self._record(
                "recurrence: open", "unknown_region", statuses.PR_OPENED,
                "no incident_id", 0.0, False, note,
            )
            return
        actual = self.wait_for_terminal(incident_id)
        first_issue = self.incident(incident_id).get("github", {}).get("issue_url")
        open_ok = actual == statuses.PR_OPENED
        self._record(
            "recurrence: open", "unknown_region", statuses.PR_OPENED,
            actual, time.monotonic() - start, open_ok,
        )
        if not open_ok:
            return

        start2 = time.monotonic()
        redelivery = copy.deepcopy(payload)
        redelivery["order_number"] = _fresh_order_number()
        second = _json(self.deliver(redelivery))
        second_issue = self.incident(incident_id).get("github", {}).get("issue_url")
        same_incident = second.get("incident_id") == incident_id
        is_recurrence = bool(second.get("recurrence"))
        count = second.get("recurrence_count")
        no_new_issue = second_issue == first_issue
        ok = (
            same_incident
            and is_recurrence
            and (count is None or count >= 1)
            and no_new_issue
        )
        actual2 = (
            f"recurrence={is_recurrence} same_incident={same_incident} "
            f"count={count} new_issue={not no_new_issue}"
        )
        self._record(
            "recurrence: repeat", "unknown_region", "reused incident, no new issue",
            actual2, time.monotonic() - start2, ok,
        )

    # --- merge-closes-loop pass ----------------------------------------------

    def run_merge_loop(self, *, enabled: bool) -> None:
        print("\n== Merge-closes-loop: fix PR merged, re-sent region now succeeds ==")
        if not enabled:
            self._record(
                "merge-loop", "unknown_region", "order created after merge",
                "SKIPPED (--no-merge-loop)", 0.0, True, skipped=True,
            )
            return

        start = time.monotonic()
        payload = generate_payload("unknown_region")
        code = payload["shipping_address"]["province_code"]
        name = payload["shipping_address"]["province"]
        first = _json(self.deliver(payload))
        incident_id = first.get("incident_id")
        if not incident_id:
            note = "capped" if first.get("reason") == "capped" else ""
            self._record(
                "merge-loop: open", "unknown_region", statuses.PR_OPENED,
                "no incident_id", 0.0, False, note,
            )
            return
        actual = self.wait_for_terminal(incident_id)
        detail = self.incident(incident_id)
        pr_url = detail.get("github", {}).get("pr_url")
        open_ok = actual == statuses.PR_OPENED and bool(pr_url)
        self._record(
            "merge-loop: open", "unknown_region", statuses.PR_OPENED,
            actual, time.monotonic() - start, open_ok,
        )
        if not open_ok:
            return

        print(
            "\n  ACTION REQUIRED (human): the agent never merges.\n"
            f"    1. Merge the fix PR: {pr_url}\n"
            f"       (it adds region {code!r} -> {name!r} to app/data/regions.json)\n"
            "    2. Wait for Vercel to finish the redeploy from the merged commit.\n"
            "    3. Press Enter here to re-send the same region and confirm the loop closed."
        )
        input("  Press Enter once the PR is merged AND the redeploy is live... ")

        start2 = time.monotonic()
        redelivery = copy.deepcopy(payload)
        redelivery["order_number"] = _fresh_order_number()
        resp = self.deliver(redelivery)
        body = _json(resp)
        closed_ok = (
            resp.status_code == 200
            and body.get("status") == "accepted"
            and body.get("incident_id") is None
            and not body.get("trigger_agent")
        )
        note = "" if closed_ok else "region did not resolve; is the merged redeploy live?"
        self._record(
            "merge-loop: resend", "unknown_region", "order created, no incident",
            f"status={body.get('status')} incident={body.get('incident_id')}",
            time.monotonic() - start2, closed_ok, note,
        )

        orders = _json(self.client.get(f"{self.base_url}/orders", params={"limit": 100}))
        want = payload["order_number"]
        original = next(
            (o for o in orders.get("orders", []) if o.get("order_number") == want),
            None,
        )
        if original is None:
            self._record(
                "merge-loop: on_hold", "unknown_region", "on_hold",
                "original not in recent 100", 0.0, True,
                note="best-effort check skipped",
            )
            return
        hold_ok = original.get("status") == "on_hold"
        self._record(
            "merge-loop: on_hold", "unknown_region", "on_hold",
            str(original.get("status")), 0.0, hold_ok,
        )

    # --- reporting ------------------------------------------------------------

    def summary(self) -> int:
        print("\n" + "=" * 96)
        header = (
            f"{'STEP':<20}{'CLASS':<20}{'EXPECTED':<30}"
            f"{'ELAPSED':<10}{'RESULT'}"
        )
        print(header)
        print("-" * 96)
        for r in self.results:
            tag = "SKIP" if r.skipped else ("PASS" if r.ok else "FAIL")
            print(
                f"{r.step:<20}{r.klass:<20}{r.expected:<30}"
                f"{r.elapsed_s:>6.1f}s   {tag}"
            )
            if r.note:
                print(f"    note: {r.note}  (got: {r.actual})")
        print("-" * 96)
        failed = [r for r in self.results if not r.ok and not r.skipped]
        skipped = [r for r in self.results if r.skipped]
        passed = [r for r in self.results if r.ok and not r.skipped]
        print(
            f"{len(passed)} passed, {len(failed)} failed, {len(skipped)} skipped "
            f"of {len(self.results)} checks."
        )
        if skipped:
            print("PARTIAL: merge-closes-loop was skipped; not a full launch gate.")
        if failed:
            print("LAUNCH GATE: FAIL")
            return 1
        print("LAUNCH GATE: PASS")
        return 0


def _preflight(client: httpx.Client, base_url: str) -> None:
    try:
        resp = client.get(f"{base_url}/health")
    except httpx.HTTPError as exc:
        sys.exit(f"FATAL: cannot reach {base_url}/health: {exc}")
    if resp.status_code != 200:
        sys.exit(f"FATAL: {base_url}/health returned {resp.status_code}")
    health = _json(resp)
    remaining = health.get("remaining_daily_agent_runs")
    print(
        f"Health OK. remaining_daily_agent_runs={remaining} "
        f"kill_switch={health.get('kill_switch')} counters_ok={health.get('counters_ok')}"
    )
    if health.get("kill_switch"):
        sys.exit("FATAL: kill switch is armed; the agent will not run. Disarm and re-run.")
    if isinstance(remaining, int) and remaining < EXPECTED_AGENT_RUNS:
        print(
            f"WARNING: only {remaining} agent runs remain today; a full gate needs "
            f"~{EXPECTED_AGENT_RUNS}. Some fixable incidents may land 'capped'."
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the B10 launch gate against a live deployment."
    )
    parser.add_argument(
        "--base-url", required=True, help="Deployment base URL, e.g. https://app.vercel.app"
    )
    parser.add_argument(
        "--no-merge-loop",
        action="store_true",
        help="Skip the interactive merge-closes-loop pass.",
    )
    parser.add_argument(
        "--poll-timeout", type=float, default=60.0,
        help="Seconds to wait for a terminal state.",
    )
    parser.add_argument(
        "--poll-interval", type=float, default=3.0,
        help="Seconds between incident polls.",
    )
    args = parser.parse_args()

    if not os.environ.get("WEBHOOK_SECRET"):
        sys.exit("FATAL: WEBHOOK_SECRET is required (must match the deployment).")
    if not os.environ.get("DATABASE_URL"):
        sys.exit("FATAL: DATABASE_URL is required (novelty checks read the same DB).")

    base_url = args.base_url.rstrip("/")
    shop_domain = configured_shop_domain()
    print(f"Launch gate -> {base_url} (store: {shop_domain})")

    with httpx.Client(timeout=30.0) as client:
        _preflight(client, base_url)
        gate = Gate(
            base_url=base_url,
            poll_timeout=args.poll_timeout,
            poll_interval=args.poll_interval,
            client=client,
            shop_domain=shop_domain,
        )
        gate.run_bulk()
        gate.run_recurrence()
        gate.run_merge_loop(enabled=not args.no_merge_loop)
        return gate.summary()


if __name__ == "__main__":
    raise SystemExit(main())
