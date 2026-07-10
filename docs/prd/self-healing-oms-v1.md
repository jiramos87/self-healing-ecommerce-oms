# PRD: Self-healing incident pipeline v1 (self-healing-ecommerce-oms)

Status: DEFINED. Behavior only. Locked platform decisions (stack, hosting, persistence, models, caps rationale) live in docs/idea.md; this spec defines observable behavior.

## Why

Portfolio proof that an agent can operate unattended with real side effects and production guardrails: marketplace webhook failures become incidents, an agent diagnoses each against runbooks and the codebase, and the outcome is a GitHub issue and (when safe) a one-line fix PR that a human merges. Audience: Full Stack AI Engineer hiring teams. Grounding in all public materials is phrased as generic production ecommerce OMS experience.

## User experience (the loop)

Actors: Visitor (anyone on the portfolio page), Human (Javier), the fix agent (system).

1. Visitor sees the incident list, a recent-orders list, and a "Simulate order" control with a class picker: valid, unknown_region, phone_format, duplicate_delivery, cancelled_order.
2. Visitor triggers unknown_region. Within 5 seconds an incident appears as received, then diagnosing; within 60 seconds it reaches pr_opened, showing the GitHub issue and PR links and an expandable per-step trace (step name, summary, model used, latency).
3. Visitor triggers valid: a new order appears in recent orders. No incident.
4. Visitor triggers duplicate_delivery: one fresh valid payload is delivered twice; the first creates an order, the second is acknowledged as duplicate and recorded as a duplicate incident linked to the first delivery. No agent run, no issue.
5. Visitor triggers cancelled_order: the incident reaches expected_behavior, citing the runbook that says cancelled orders are dropped by design. No issue, no PR.
6. Human merges the agent's PR. Re-sending an order with the previously unknown region now succeeds: the loop visibly closed. The original on_hold order stays on_hold (no reprocessing in v1).
7. When limits are hit or providers are down, the UI shows honest state (capped, degraded, diagnosis_failed) instead of silent failure.

## Inputs & outputs (the contract)

Inputs:

- `POST /webhooks/orders`: Shopify-shaped JSON subset, HMAC-signed (Shopify-style signature header; shared secret). Store identity via a Shopify-style shop-domain header; exactly one store is configured (hardcoded JSON in repo). Payload fields: `order_number`, `email`, `phone`, `total_price`, `currency`, `line_items[] {sku, title, quantity, price}`, `shipping_address {address1, city, zip, province, province_code, country_code}`, `customer {first_name, last_name}`, `cancelled_at` (null unless cancelled).
- `POST /demo/simulate` body `{class}` with class in {valid, unknown_region, phone_format, duplicate_delivery, cancelled_order}: generates a fresh payload for that class, signs it, and delivers it to the webhook endpoint (twice for duplicate_delivery). Generators guarantee unknown_region and phone_format values are novel (never previously seen). Returns the resulting order and/or incident references.
- `POST /incidents/{id}/retry` with admin token (env secret): re-runs diagnosis for an incident in diagnosis_failed.
- `GET /incidents?limit&cursor`, `GET /incidents/{id}`, `GET /orders?limit`, `GET /health` (includes caps state: remaining daily runs, kill-switch flag). All GETs public, read-only.

Outputs:

- Webhook responses: 200 accepted (order created), 200 duplicate (idempotent ack, no reprocessing), 401 bad/missing HMAC or unknown store, 422 malformed JSON or schema-invalid payload (no incident; incidents are for domain failures only).
- Incident shape: `id, created_at, class, status, fingerprint, summary, error_body, recurrence_count, last_seen_at, duplicate_of, github {issue_url, pr_url}, trace[] {step, summary, served_by, ms, at}`.
- Incident status enum (terminal states in bold): received, diagnosing, **pr_opened**, **issue_only**, **duplicate**, **expected_behavior**, **diagnosis_failed**. (issue_opened is a transient state between issue and PR creation for fixable classes.) An incident still diagnosing 5 minutes after its last trace step is reported as diagnosis_failed (reason: stalled) whenever read; retry becomes available.
- The unknown_region fix: the region mapping data file maps `province_code` to the region display name taken verbatim from the payload's `province` field, so the correct one-line fix is fully derivable from the incident with no judgment call. The phone_format fix: one rule appended to the normalizer rules data file.
- GitHub artifacts, English, deterministic section structure: issue titled `[agent] <class>: <detail>` with error body, diagnosis, runbook citation, fingerprint; PR with a one-line data-file diff, linked issue, branch `agent/fix-<fingerprint>`; recurrence = comment on the existing issue, never a new one. No employer names anywhere.

## Acceptance (Given / When / Then)

**Happy path**

- Given the service is deployed and healthy, When a signed unknown_region webhook arrives, Then a 200 is returned, the order is stored on_hold, an incident is created (received), and within 60s the incident is pr_opened with a GitHub issue and a PR whose diff is exactly one added line in the region mapping data file, mapping the payload's province_code to its province name.
- Given a valid signed webhook, When it arrives, Then a 200 is returned, the order is stored as created, it appears in `GET /orders`, and no incident exists for it.
- Given a phone_format webhook (a phone shape the normalizer rules cannot parse), When processed, Then the incident reaches pr_opened with a one-line addition to the normalizer rules data file.
- Given the agent's unknown_region PR is merged, When an order with that same region arrives, Then it succeeds as a valid order, and the original on_hold order remains on_hold.
- Given an incident in any state, When `GET /incidents/{id}` is called, Then the full trace to date is returned, each step with summary, served_by, and latency.

**Edge cases & failure modes**

- Given a webhook with a missing or wrong HMAC, When it arrives, Then 401, nothing is stored, nothing is counted against agent caps.
- Given malformed JSON or a schema-invalid payload, When it arrives, Then 422 with a machine-readable error and no incident.
- Given a duplicate_delivery simulation, When it runs, Then the first delivery creates an order, the second returns 200 duplicate and records a duplicate incident linked to the original delivery, and the agent does not run.
- Given any payload identical in (store, order_number) to an already-processed delivery, When it arrives, Then 200 duplicate with the same duplicate-incident behavior.
- Given a failing delivery whose fingerprint matches an existing incident, When it arrives, Then no new issue or PR; the existing incident's recurrence_count increments and a comment is posted on its issue.
- Given a cancelled_order payload, When processed, Then the incident reaches expected_behavior citing the runbook; no GitHub artifact is created.
- Given the LLM diagnosis step, When the primary provider fails or is capped, Then the fallback provider is used and the trace shows served_by fallback; When both fail, Then the incident is diagnosis_failed with the reason, and retry is available.
- Given an incident whose agent run died mid-flight, When it is read 5 minutes after its last trace step with no terminal state, Then it is reported diagnosis_failed (reason: stalled) and retry is available.
- Given a filled recipe whose computed diff violates its gate (more than 1 file, over line budget, any deletion, path outside allowlist, file no longer parses), When the gate runs, Then no PR is created, the incident lands issue_only, and the trace records the violated rule.
- Given GitHub is unreachable before issue creation, When artifact creation fails, Then the incident is diagnosis_failed with reason recorded (diagnosis preserved in trace) and retry is available; Given the issue exists but PR creation fails, Then the incident lands issue_only with the failure in the trace.
- Given an IP over 3 simulates in 10 minutes, When it simulates again, Then 429 with a friendly retry-after message.
- Given 20 agent runs have occurred today, When any new incident would trigger the agent, Then the incident is stored but the agent does not run (status received, reason capped, surfaced via /health); duplicate detection still works.
- Given the counters store is unreachable, When a simulate or webhook arrives, Then the request is refused (503, fails closed) rather than risking uncapped spend.
- Given a retry request with a bad admin token, Then 401; on an incident not in diagnosis_failed, Then 409.
- Given concurrent simulates from different classes, When processed, Then each incident's trace and artifacts reference only its own payload (no cross-contamination), and no incident exceeds 3 LLM calls.
- Given `GET /incidents` with no data, Then a well-formed empty list, not an error.

## Quality bar

- Verify gate green: ruff, typecheck (mypy or pyright), pytest, app boot.
- `GET` endpoints p95 under 500ms; incident visible in list under 5s after webhook ack; terminal state under 60s p90.
- Launch gate: a scripted sequence of 20 simulate runs covering all five classes, plus a recurrence pass and a merge-closes-loop pass, run against the live deployment, must land every incident on the correct terminal state, each under 60 seconds, with zero recipe-gate violations.
- Every incident cost-bounded: at most 3 LLM calls; per-run token caps enforced.
- All GitHub artifacts and UI-facing strings in English; issue/PR bodies follow one deterministic template each.
- No secrets in the repo; webhook secret, admin token, provider keys via env. Public GETs are safe to expose (read-only, no PII beyond generated fake data).
- Honest degradation everywhere: capped, degraded, and failed states are visible in API responses, never silent.

## Dependencies (resolved)

| Dependency | Approach | Fallback | Cost / quota | Runtime vs curation |
| --- | --- | --- | --- | --- |
| OpenRouter | Existing shared prepaid key; `google/gemini-3.5-flash` for diagnosis/extraction, `google/gemini-3.1-flash-lite` for classification | Groq free tier; both down = diagnosis_failed + retry | Under 1 cent per run; prepaid cap is the ceiling; caps (20/day) bound worst case | Runtime |
| Groq | Free tier, `llama-3.3-70b-versatile`, as fallback provider | Honest diagnosis_failed | Free | Runtime |
| GitHub REST API | New fine-grained PAT under the existing account, scoped to this repo only: contents, issues, pull-requests write | Failure paths specced in acceptance (diagnosis_failed / issue_only) | Free | Runtime |
| Railway Postgres | New database on the existing instance: incidents, orders, counters | Unreachable = fail closed (503) | Marginal cost about zero on the already-running instance | Runtime |
| Vercel Python (FastAPI, Fluid Compute) | Hosting + agent execution. Backlog item 1 is a spike verifying post-response execution for Python | If unsupported: simulate-orchestrated synchronous run (simulate invocation drives the agent after the webhook ack; UI polls meanwhile; direct webhooks stay received until manual retry) | Hobby tier, 0 fixed | Runtime |
| LangGraph + langchain-core (pip) | Deterministic StateGraph, guardrail node first, deterministic tool gating | n/a (library) | Free, MIT | Build/runtime |
| Runbooks + mapping/normalizer data files | Authored in-repo, English, one runbook per class; region map and phone rules as JSON/YAML data files (the agent's fixable surface) | n/a | Free | Curation |
| Demo generators | Deterministic generators for novel region codes/names and phone formats; uniqueness checked against existing data | n/a | Free | Runtime |
| Portfolio app UI (consumer) | Public GETs with permissive CORS; simulate POST rate-limited; UI page specced in the portfolio repo | UI absence does not affect this service | Free | Runtime |

## Out of scope

- The demo UI (its own spec: docs/prd/demo-ui-v1.md). This spec guarantees the read API + simulate endpoint the UI consumes.
- PR hygiene job (stale `agent/*` PR closer): separate small feature after v1.
- Reprocessing of on_hold orders after fixes merge.
- Embeddings/RAG retrieval; auto-merge; auto-deploy of merged fixes; real Shopify integration; additional marketplaces; multi-store or multi-tenant; user auth beyond the admin token; data retention/cleanup policies.

**Invariants**

- The agent never merges anything, anywhere.
- Fix PRs only ever come from typed recipes: allowlisted data files, one-file diff, within line budget, zero deletions. Free-form patching does not exist in the system.
- Spend can never exceed the caps: limit checks fail closed.
- Public surface is read-only except the webhook and the rate-limited simulate endpoint.
- Public-facing content (README, docs, issues, PRs, comments) never names past employers or their internal codebases; grounding is "production ecommerce OMS experience".

## Done looks like

A live Vercel URL passing the scripted 20-run launch gate, all acceptance scenarios covered by tests with the verify gate green, plus a README with the architecture diagram and generic-experience grounding, a screenshot set, and the portfolio exhibit entry published.

## Scope changes (living log)

- 2026-07-09: created as DRAFT from docs/idea.md.
- 2026-07-09 (grill): duplicate_delivery pinned to self-contained double-send - added - deterministic demo.
- 2026-07-09 (grill): region fix semantics pinned to code-to-payload-name mapping - added - fix derivable without judgment, merge-closes-loop stays deterministic.
- 2026-07-09 (grill): on_hold orders stay on_hold after merge - deferred (reprocessing) - loop closure shown by re-send.
- 2026-07-09 (grill): stalled diagnosing incidents lazily reported diagnosis_failed after 5 min - added - no stranded spinners without a scheduler.
- 2026-07-09 (grill): GitHub credential pinned to a new fine-grained PAT scoped to this repo - added - blast radius control.
- 2026-07-09 (grill): Python post-response execution flagged as spike; fallback pinned to simulate-orchestrated runs - added - dependency resolved, not assumed.
- 2026-07-09 (grill): launch gate pinned to a scripted 20-run pass against the live deployment - added - repeatable yardstick.
- 2026-07-09 (grill): README (diagram), screenshots, and portfolio exhibit promoted into this PRD's scope; all public grounding de-identified (no employer names) - promoted + changed - Human decision during grill.
- 2026-07-09: Status DRAFT -> DEFINED.
- 2026-07-10: demo UI moved out of the portfolio repo into a self-contained page in this repo - changed - Human decision; behavior now in docs/prd/demo-ui-v1.md. This PRD stays backend-only and still just guarantees the API the UI consumes.
