# PRD: Demo UI v1 (self-healing-ecommerce-oms)

Status: DEFINED. Behavior only. The UI is self-contained in this repo and served by the same FastAPI/Vercel deployment; it consumes the existing read API and simulate endpoint. It does not change any API contract.

## Why

The live URL currently returns raw JSON, so a recruiter clicking it sees `{"incidents":[...]}` instead of a demo. This turns the same public URL into a one-screen, self-serve demonstration of the self-healing loop: trigger a failing order, watch the agent diagnose it, follow the real GitHub issue and PR. It is the visual proof that the backend already earns; it must ship before the README screenshots and portfolio exhibit (B12).

## User experience (the loop)

1. A visitor opens the site root and sees a dashboard: a short hero explaining the demo and its guardrails, a row of caps/health state, a "Simulate" control with five buttons (valid, unknown_region, phone_format, duplicate_delivery, cancelled_order), an incident list, and a recent-orders list. The most recent real incidents and orders are already shown (the system has run before).
2. The visitor clicks "unknown_region." A new incident appears within a few seconds as received, then advances to diagnosing, then to pr_opened, updating live without a manual refresh.
3. The visitor expands that incident and sees its per-step agent trace (step name, model or "deterministic", latency), a status badge, and links to the real GitHub issue and PR.
4. The visitor clicks valid: a new order appears in recent orders, no incident. Clicks duplicate_delivery: an incident marked duplicate. Clicks cancelled_order: an incident marked expected_behavior, no GitHub artifacts. Each terminal state is visibly distinct.
5. If the visitor exceeds the simulate rate limit, a friendly banner explains the cost guardrail and shows a retry countdown; the buttons disable until the window resets.
6. If the daily agent cap is reached or a provider is degraded, the affected incidents show an honest capped/degraded state rather than silently stalling. If storage is unreachable, the dashboard shows an honest "temporarily unavailable" state instead of a blank screen or a raw error.

## Inputs & outputs (the contract)

The UI is a client of the existing surface. It introduces exactly one new server behavior: serving the dashboard document at the site root. It adds no other endpoint and changes no existing response shape.

- Consumes (read): `GET /health` (caps + counters state), `GET /incidents?limit&cursor`, `GET /incidents/{id}` (full trace), `GET /orders?limit`.
- Consumes (action): `POST /demo/simulate {class}` for the five classes; honors its 200 / 429 (with retry_after) / 503 responses.
- Serves: an HTML dashboard at `GET /` (and the assets it needs), self-contained, no build step, no external network dependencies at runtime (no CDN, no external fonts or trackers).
- Never touches: the admin retry endpoint (no admin token in the browser), the webhook endpoint, or any write path other than the rate-limited simulate.

## Acceptance (Given / When / Then)

**Happy path**

- Given the deployed site, When a visitor opens `/`, Then the dashboard HTML renders with the hero, caps/health strip, five simulate buttons, incident list, and recent-orders list, populated from the live API.
- Given the dashboard, When the visitor clicks unknown_region, Then a new incident appears and its status advances from received through diagnosing to pr_opened live (auto-updating), ending with a visible status badge and working GitHub issue and PR links.
- Given an incident row, When the visitor expands it, Then the full trace renders as an ordered timeline, each step showing its name, served-by (model id or deterministic), and latency in ms.
- Given the visitor clicks valid, Then a new order appears in recent orders and no incident is created for it.
- Given the visitor clicks duplicate_delivery, Then an incident with a duplicate badge appears and no GitHub artifacts are shown; Given cancelled_order, Then an expected_behavior badge and no GitHub artifacts.

**Edge cases and failure modes**

- Given a fresh load with no data available yet, When the lists are empty, Then each shows a clear empty state, not a spinner forever and not an error.
- Given the API is still responding, When a request is in flight, Then a loading affordance shows and is replaced by content or an error, never left hanging.
- Given the visitor exceeds 3 simulates in 10 minutes, When they click again, Then a banner surfaces the 429 with a human retry countdown and the simulate buttons are disabled until the window resets, then re-enable.
- Given the daily agent cap (20/day) is reached, When a triggering class is simulated, Then the resulting incident is shown in a capped state (does not falsely display as diagnosing forever), consistent with `/health` reporting no remaining runs.
- Given a provider fell back or the run degraded, When the incident renders, Then the served-by and any degraded flag are shown honestly rather than hidden.
- Given storage is unreachable (API returns 503), When the dashboard polls, Then it shows an honest "temporarily unavailable, retrying" state and recovers automatically when the API returns, without a full reload.
- Given an incident that reached issue_only or diagnosis_failed, When rendered, Then its badge and available links reflect that terminal state (issue link but no PR for issue_only; a failure reason surfaced for diagnosis_failed).
- Given a fix PR was merged and the region now resolves, When the visitor re-simulates that flow, Then the newly delivered order succeeds as a normal order (the closed loop is observable end to end in the UI).

## Quality bar

- The site root renders the dashboard; the JSON endpoints keep their current paths unchanged (the launch gate and any external consumer must not break).
- No build step and no new deploy surface: the page ships inside the existing FastAPI/Vercel deployment with no bundler and no runtime dependency on any external host (CSP-friendly, all assets self-served or inline).
- Auto-updates while any incident is non-terminal (about every 3s) and backs off when everything is settled; no websockets.
- Honest degradation everywhere: capped, degraded, rate-limited, and storage-unavailable states are all visible, never silent, matching the API's own honesty flags.
- Reads well and screenshots cleanly on a laptop viewport and remains usable down to tablet width; legible contrast; buttons and status have text labels, not color alone.
- First meaningful render under ~2s on the deployed URL; a simulate click gives feedback within ~1s even though the agent run itself takes longer.
- No secrets or admin tokens in client code; the public surface stays read-plus-rate-limited-simulate only.

## Dependencies (resolved)

| Dependency | Approach | Fallback | Cost | Runtime vs curation |
| --- | --- | --- | --- | --- |
| Existing read API + simulate | Consume as-is; serve dashboard at `/` | If an endpoint errors, show that section's honest error state | 0 | Runtime |
| Rate limit (3/10min per IP) | Honor 429 + retry_after in the UI | n/a | 0 | Runtime |
| Real GitHub artifacts from public clicks | Kept (the demo's point); repo kept clean by a companion PR-hygiene cleanup job (nightly GitHub Action closing stale agent/* PRs and issues, pruning branches) tracked as its own backlog item, not part of this UI | Manual cleanup if the job is not yet shipped | 0 (Actions free on public repos) | Runtime |
| Static serving on Vercel Python | Dashboard served by the FastAPI app (no bundler) | n/a | 0 | Runtime |

## Out of scope

- The admin retry control (needs the admin token; stays operator-only, not in the public UI).
- The PR-hygiene cleanup job itself (companion backlog item; this PRD only depends on it).
- A portfolio-design-system version of the page (the portfolio app may later embed or link to this demo; that is separate).
- Authentication, per-visitor accounts, mobile-first layout, on_hold order reprocessing, and any change to agent behavior or the error taxonomy.

**Invariants**

- Existing JSON endpoint paths and response shapes do not change.
- The public surface stays read-only plus the rate-limited simulate; no new write path and no admin capability reaches the browser.
- No secrets in client-delivered code.
- Public-facing copy never names past employers or internal codebases ("production ecommerce OMS experience").

## Done looks like

Opening the live URL shows a self-contained dashboard where a visitor can trigger each of the five classes and watch incidents reach four visibly distinct terminal states with real GitHub links and a live agent trace, with every degraded state surfaced honestly, ready to screenshot for B12.

## Scope changes (living log)

- 2026-07-10: created DEFINED. Corrects the earlier decision that the UI lived only in the portfolio repo; v1 UI is self-contained in this repo (Human decision 2026-07-10). Real public triggering is kept, which promotes the previously v1.1-deferred PR-hygiene cleanup job into a companion v1 backlog item.
