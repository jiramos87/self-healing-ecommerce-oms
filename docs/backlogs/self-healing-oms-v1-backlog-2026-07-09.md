# self-healing-ecommerce-oms v1 implementation backlog (2026-07-09)

backlog-format: implementation-backlog/v1
prd: docs/prd/self-healing-oms-v1.md (Status: DEFINED)
scope: the full v1 incident pipeline per the PRD, including README, screenshots, and portfolio exhibit. Excluded: the portfolio UI page implementation (own PRD in the portfolio repo), PR hygiene job, on_hold reprocessing.
ship-target: none
contract: verify gate = ruff + pyright + pytest + app boot. Honesty rail: report failures plainly; degraded states visible, never silent. Cost ceiling: shared OpenRouter prepaid key; max 3 LLM calls per incident; caps 3 simulates/10min per IP, 20 agent runs/day global, limits fail closed. English everywhere. Public content never names past employers or internal codebases ("production ecommerce OMS experience"). Never commit or push without Javier's explicit ok. The agent product never merges anything.
env-inventory: runtime: DATABASE_URL, OPENROUTER_API_KEY, OPENROUTER_BASE_URL (optional override), GROQ_API_KEY, GITHUB_FIX_PAT, GITHUB_REPO, WEBHOOK_SECRET, ADMIN_TOKEN. Curation-only: none.
seams (pinned so items cannot drift): Python 3.13 FastAPI app in `app/`, Vercel entry `api/index.py`, deps in `requirements.txt`, tool config in `pyproject.toml`. Data files: `app/data/store.json`, `app/data/catalog.json`, `app/data/regions.json`, `app/data/phone_rules.json`. Agent write allowlist: `app/data/regions.json`, `app/data/phone_rules.json` only. Runbooks: `docs/runbooks/{unknown_region,phone_format,duplicate_delivery,cancelled_order}.md`. Tables: `orders`, `incidents`, `counters` in Railway database `self_healing_oms`. Incident classes: unknown_region, phone_format, duplicate_delivery, cancelled_order. Statuses per PRD enum. Fingerprint: sha256(class|store|offending_value) short form. Branch: `agent/fix-<fingerprint>`. Issue title: `[agent] <class>: <detail>`. Models: `google/gemini-3.5-flash` (diagnose/extract), `google/gemini-3.1-flash-lite` (classify), Groq `llama-3.3-70b-versatile` (fallback). Headers: `X-Shopify-Hmac-SHA256` (base64 HMAC-SHA256 of raw body with WEBHOOK_SECRET), `X-Shopify-Shop-Domain` (must match store.json). GITHUB_REPO: `jiramos87/self-healing-ecommerce-oms`.

Items are ordered by dependency: suggested execution order = ledger order. Each item is
self-contained: an implementer with ONLY this doc's header + their assigned item (plus the
repo's CLAUDE.md, always ambient) can build it without the authoring session's context.
Effort: S < 0.5 day, M = 0.5-1.5 days, L > 1.5 days.

## Ledger

| item | status | date | sha | evidence |
|---|---|---|---|---|
| B01 | done | 2026-07-09 | eb831fa | TRIGGER_MODE=background; 5/5 POST /spike ack <1s; SPIKE_BG_DONE in runtime logs + poll status=done after 10s; throwaway project vercel-py-bg-spike deleted |
| B02 | done | 2026-07-09 | eb831fa | ruff+pyright+pytest green (1 passed test_health_returns_ok); uvicorn boot + curl /health 200 {"ok":true}; gh repo view jiramos87/self-healing-ecommerce-oms PUBLIC; also .python-version + api/tests __init__.py |
| B03 | done | 2026-07-09 | eb831fa | CREATE DATABASE self_healing_oms on just-recreation Postgres; migrate 001_init; psql lists orders/incidents/counters; test_create_and_read_order_and_incident passed; ruff+pyright+pytest green (2); local .env set (needs-human: Vercel DATABASE_URL later) |
| B04 | done | 2026-07-09 | eb831fa | pytest 13 passed (test_webhook: 401/422/created/unknown_region/phone_format/cancelled/duplicate/recurrence + health/db); ruff+pyright green; also app/main.py router wire + app/db.py helpers |
| B05 | done | 2026-07-09 | eb831fa | pytest 24 passed (simulate per-class, novelty, 429, capped, 503, health caps); curl all 5 classes + /health; also app/db.py counters + app/main.py/webhooks.py wiring |
| B06 | done | 2026-07-09 | eb831fa | test_kb 4 passed (per-class, cancelled no-action, keyword fallback, unknown default); grep docs/runbooks/ no employer names; ruff+pyright+pytest 28 passed; needs-human: runbook copy review |
| B07 | done | 2026-07-09 | eb831fa | test_agent 6 passed (trace/fallback/cap/stalled/providers_down); live OpenRouter unknown_region ready_to_act recipe QQ→Quebrada Quimera, 2 LLM calls, trace 6 steps; ruff+pyright+pytest green; also requirements langgraph 1.2.8 + db update/append_trace |
| B08 | done | 2026-07-09 | eb831fa | pytest recipes+github+agent green (code review pass, 53 total); ruff+pyright green. Live proof against jiramos87/self-healing-ecommerce-oms with GITHUB_FIX_PAT: unknown_region SF -> pr_opened, issue #2 + PR #3, diff exactly 1 file +1/-0 (branch agent/fix-proofrun-sf), 2 LLM calls (gemini-3.5-flash diagnose+extract), trace 7 steps. Proof artifacts left open for human review. |
| B09 | pending | - | - | - |
| B10 | pending | - | - | - |
| B11 | pending | - | - | - |

---

## B01. Spike: verify Vercel Python post-response execution [S] (PRD: Dependencies, Vercel Python row)

**Goal.** The TRIGGER_MODE decision is recorded: `background` if a FastAPI background task reliably completes after the response on Vercel Fluid Compute for Python, else `orchestrated` (simulate invocation drives the agent synchronously after the webhook ack; direct webhooks stay received until manual retry).

**Change.** Deploy a throwaway Vercel project: minimal FastAPI app whose endpoint returns immediately and schedules a background task that, 10 seconds later, writes a timestamped marker (runtime log line is enough). Invoke it several times; check whether markers appear after the response consistently. Record the verdict as a "Note (date):" under Appendix C, in the repo CLAUDE.md Gotchas, and in this ledger row's evidence. Delete the throwaway project afterward.

**Acceptance.**
- manual: curl returns in under 1s; Vercel runtime logs show the delayed marker present (background works) or absent/killed (orchestrated mode), consistently across at least 5 invocations.
- manual: ledger evidence line records `TRIGGER_MODE=background` or `TRIGGER_MODE=orchestrated`.

**Files.** Throwaway spike project outside this repo (scratch dir); CLAUDE.md (Gotchas note); this doc (Appendix C note).

**Depends on.** none.

---

## B02. Scaffold the FastAPI service, verify gate, and GitHub repo [M] (PRD: Quality bar)

**Goal.** A bootable FastAPI skeleton with the verify gate green and the public GitHub repo created, so every later item lands on real rails.

**Change.** Create `app/` package with FastAPI instance and a static `GET /health` stub; `api/index.py` Vercel entry importing it; `requirements.txt` (fastapi, langgraph, langchain-core, httpx, psycopg[binary] or asyncpg, pydantic; uvicorn for dev); `pyproject.toml` configuring ruff and pyright; pytest wiring; `.env.example` listing exactly the header env-inventory; `.gitignore` (env files, caches); minimal `vercel.json` if needed for the Python entry. Create the public GitHub repo `self-healing-ecommerce-oms` with gh. needs-human: approve the first commit and push (canon: no commits without explicit ok).

**Acceptance.**
- build: ruff + pyright + pytest all pass locally.
- manual: `uvicorn app.main:app` boots; `curl localhost:8000/health` returns 200 JSON.
- manual: `gh repo view jiramos87/self-healing-ecommerce-oms` succeeds.

**Files.** app/main.py, api/index.py, requirements.txt, pyproject.toml, .env.example, .gitignore, vercel.json, tests/test_health.py.

**Depends on.** none.

---

## B03. Database schema and connection [M] (PRD: Inputs & outputs; Dependencies, Railway row)

**Goal.** `orders`, `incidents`, and `counters` tables exist in a new `self_healing_oms` database on the existing Railway Postgres instance, and the app reads/writes them.

**Change.** Create the database on the existing Railway instance (railway CLI; dashboard if CLI permissions block it: needs-human in that case). SQL migrations in `db/migrations/` applied by `scripts/migrate.py`. Shapes follow the PRD contract: incidents (id, created_at, class, status TEXT + CHECK against the PRD enum, fingerprint unique, summary, error_body JSONB, payload JSONB, recurrence_count, last_seen_at, duplicate_of, issue_url, pr_url, trace JSONB array); orders (id, order_number, store, status created|on_hold, payload JSONB, created_at); counters (key, window_start, count) for rate limits. needs-human: set DATABASE_URL locally and in Vercel project env.

**Acceptance.**
- test: env-gated pytest creates and reads back an incident and an order.
- manual: psql lists the 3 tables in `self_healing_oms`.
- build: verify gate green.

**Files.** db/migrations/001_init.sql, scripts/migrate.py, app/db.py, tests/test_db.py.

**Depends on.** B02.

---

## B04. Webhook ingestion and domain validation [M] (PRD: webhook contract lines; happy path 1-2; edge cases HMAC/422/duplicate/recurrence/cancelled)

**Goal.** `POST /webhooks/orders` behaves exactly per the PRD: 200 accepted, 200 duplicate, 401, 422; valid orders stored created; domain failures store on_hold orders plus incidents; duplicates and recurrences recorded (GitHub comment side lands in B08; here recurrence_count and last_seen_at update).

**Change.** HMAC verification against WEBHOOK_SECRET (header per seams); shop-domain check against `app/data/store.json`; pydantic schema for the PRD payload subset (422 on violation, no incident); region resolution via `app/data/regions.json` seeded with the 16 real Chilean regions (code to display name); phone normalization via `app/data/phone_rules.json` seeded with standard Chilean formats; `cancelled_at` non-null creates a cancelled_order incident (no agent trigger flag set); duplicate = existing (store, order_number); fingerprint per seams; unknown region and unparseable phone create on_hold order + incident of the matching class.

**Acceptance.**
- test: pytest covers every webhook Given/When/Then in the PRD (401, 422, created, on_hold+incident per class, duplicate, recurrence increments).
- build: verify gate green.

**Files.** app/webhooks.py, app/validation.py, app/regions.py, app/phones.py, app/data/store.json, app/data/catalog.json, app/data/regions.json, app/data/phone_rules.json, tests/test_webhook.py.

**Depends on.** B03.

---

## B05. Simulate endpoint, generators, and rate limits [M] (PRD: simulate contract; caps edge cases; /health)

**Goal.** `POST /demo/simulate` produces each class per contract; caps enforced fail-closed; `/health` reports caps state.

**Change.** Simulate generates a fresh payload per class, signs it, and delivers in-process to the webhook handler (duplicate_delivery: same fresh payload twice; response references both results). Generators guarantee novel region codes/names and novel phone formats (uniqueness vs data files and DB history). Rate limits on the counters table: 3 simulates/10min per IP (429 with retry-after), 20 agent runs/day global (incidents stored received, reason capped), counter store unreachable = 503 fail closed. `/health` returns remaining daily runs and kill-switch state.

**Acceptance.**
- test: per-class contract results; 429 path; capped path; 503 path (DB failure monkeypatched); novelty guarantee test (two unknown_region runs yield different codes).
- manual: local curl of each class shows the documented response shape.

**Files.** app/simulate.py, app/generators.py, app/limits.py, app/health.py, tests/test_simulate.py, tests/test_limits.py.

**Depends on.** B04.

---

## B06. Runbooks and retrieval [S] (PRD: Dependencies runbooks row; expected_behavior acceptance)

**Goal.** Four English runbooks exist and retrieval returns the right one per class.

**Change.** Write `docs/runbooks/{unknown_region,phone_format,duplicate_delivery,cancelled_order}.md`, each with Symptom, Diagnosis guidance, and Fix policy sections; cancelled_order's policy is explicit "expected behavior, no action, no artifact". Retrieval is deterministic class-to-file mapping with keyword fallback. No employer names. needs-human: Javier reviews runbook copy.

**Acceptance.**
- test: retrieval returns the expected runbook per class and a sensible default on unknown input.
- manual: grep of docs/runbooks/ for employer names returns nothing.

**Files.** docs/runbooks/*.md, app/kb.py, tests/test_kb.py.

**Depends on.** B02.

---

## B07. Agent pipeline through diagnosis [L] (PRD: trace acceptance; LLM fallback; stalled; call caps)

**Goal.** A LangGraph pipeline runs classify, retrieve, diagnose, and extract recipe parameters, persisting a per-step trace; provider fallback and caps behave per PRD; stalled incidents report lazily.

**Change.** LangGraph StateGraph (deterministic edges, guardrail-first, mirroring the public portfolio repo's graph pattern). OpenRouter via OpenAI-compatible client with the pinned models; Groq fallback; `served_by` recorded per step; hard cap 3 LLM calls and per-run token limits; structured extraction validated against the recipe parameter schema with at most one re-ask; statuses received, diagnosing, then internal ready-to-act or diagnosis_failed (reason recorded). Reads of incidents still diagnosing 5 minutes after the last trace step report diagnosis_failed reason stalled. The act step is a stub here (returns extraction; GitHub lands in B08).

**Acceptance.**
- test: mocked-provider tests for fallback chain, call cap, stalled lazy report, trace shape (step, summary, served_by, ms, at).
- manual: one real unknown_region incident diagnosed locally against live OpenRouter, trace visible, cost under 1 cent.

**Files.** app/agent/graph.py, app/agent/llm.py, app/agent/trace.py, app/agent/schemas.py, tests/test_agent.py.

**Depends on.** B05, B06.

---

## B08. Fix recipes and GitHub artifacts [L] (PRD: recipe gate; GitHub artifact contract; recurrence comment; GitHub failure paths)

**Goal.** Fixable incidents produce a GitHub issue and a one-line PR through typed recipes; violations and GitHub failures land on the exact PRD statuses.

**Change.** GitHub REST (issues, contents, pulls) authenticated with GITHUB_FIX_PAT against GITHUB_REPO. Recipes: unknown_region inserts `province_code: province name from payload` into app/data/regions.json; phone_format appends one rule to app/data/phone_rules.json. Deterministic pre-PR gate: exactly 1 file, at most 1 added line, 0 deletions, path in allowlist, file parses, new key resolves; violation = issue_only with the rule named in the trace. Branch and issue title per seams; deterministic English issue/PR templates (error body, diagnosis, runbook citation, fingerprint); recurrence = comment on existing issue, never a new one; GitHub unreachable before issue = diagnosis_failed (diagnosis preserved), after issue = issue_only. needs-human: create the fine-grained PAT (this repo only: contents, issues, pull-requests write) and set it locally and in Vercel.

**Acceptance.**
- test: mocked GitHub tests for every gate rule, artifact body templates, recurrence comment, and both failure paths.
- manual: one real E1 run against the live repo produces an issue and a PR whose diff is exactly one added mapping line.

**Files.** app/agent/recipes.py, app/agent/github.py, app/agent/act.py, tests/test_recipes.py, tests/test_github.py.

**Depends on.** B07.

---

## B09. Trigger wiring, retry, and the status API [M] (PRD: GET contracts; retry edge cases; latency bars)

**Goal.** The full pipeline runs end to end per TRIGGER_MODE; retry works; the read API serves the UI contract.

**Change.** Wire webhook-to-agent per B01's recorded TRIGGER_MODE (background task in-invocation, or simulate-orchestrated with direct webhooks staying received until retry). `POST /incidents/{id}/retry` gated by ADMIN_TOKEN (401 bad token, 409 not diagnosis_failed). `GET /incidents` (cursor pagination, newest first), `GET /incidents/{id}` (full trace), `GET /orders` (recent). Permissive CORS on GETs only. Empty lists return well-formed.

**Acceptance.**
- test: retry auth and state transitions; list/detail/order shapes; empty-list behavior.
- manual: local run of every class reaches its correct terminal state in under 60s; GETs answer under 500ms locally.

**Files.** app/api.py, app/trigger.py, tests/test_api.py.

**Depends on.** B08 (uses B01 verdict).

---

## B10. Deploy and pass the launch gate [M] (PRD: Quality bar launch gate; Done looks like)

**Goal.** The live Vercel deployment passes the scripted 20-run launch gate.

**Change.** Create/link the Vercel project (repo root, Python), provision all runtime env vars, deploy to production. Write `scripts/launch_gate.py`: 20 simulate runs covering all five classes plus a recurrence pass and a merge-closes-loop pass, asserting correct terminal states, under 60s each, zero recipe-gate violations, against the live URL; prints a pass/fail table. needs-human: merge the E1 PR mid-gate for the merge-closes-loop pass; confirm Vercel env values.

**Acceptance.**
- manual: launch gate script output shows all passes against the live URL; output summary recorded in ledger evidence.
- build: verify gate still green.

**Files.** scripts/launch_gate.py, vercel.json, docs/deploy.md.

**Depends on.** B09.

---

## B11. README, screenshots, and portfolio exhibit [M] (PRD: Done looks like; public-content invariant)

**Goal.** The public story ships: README with architecture diagram, screenshot set, and the portfolio exhibit entry.

**Change.** README: what/why, architecture diagram (ASCII or SVG), demo guide, the guardrails story (recipes, gates, caps, human merge), cost story, grounding phrased as generic production ecommerce OMS experience. Screenshots of the live demo states (incident timeline, issue, one-line PR diff). Portfolio exhibit record generated with the agentic-dev-kit MCP `scaffold_exhibit` tool and added to the portfolio app's data (portfolio repo). needs-human: copy review and final screenshot capture.

**Acceptance.**
- manual: README renders correctly on GitHub; `grep -ri` for past-employer names across the repo returns nothing.
- manual: exhibit record exists in the portfolio repo and renders on the projects page locally.

**Files.** README.md, docs/screenshots/*, portfolio repo exhibit data file.

**Depends on.** B10.

---

## Appendix A: ground-truth verdicts

- Backlog template and conventions: VERIFIED. Copied from portfolio `docs/templates/implementation-backlog-template.md`; example backlog `agentic-concierge-backlog-2026-07-05.md` exists there.
- CLIs: VERIFIED present via `which`: gh (/opt/homebrew/bin), vercel (volta), railway (/opt/homebrew/bin). Auth state UNVERIFIED; first use in B02/B03/B10 confirms.
- Python 3.13.3 local: VERIFIED (`python3 --version`).
- Env var names to reuse (OPENROUTER_API_KEY, GROQ_API_KEY, DATABASE_URL, GITHUB_TOKEN): VERIFIED by name-only grep of portfolio env files; values not read.
- OpenRouter model slugs (`google/gemini-3.5-flash`, `google/gemini-3.1-flash-lite`) and Groq `llama-3.3-70b-versatile`: VERIFIED in portfolio code; repo comments state slugs verified live 2026-07-07.
- Railway Postgres instance: VERIFIED it exists (portfolio prod). Creating database `self_healing_oms` on it: UNVERIFIED until B03 (CLI permissions may require dashboard).
- Vercel Python post-response execution: UNVERIFIED. Vercel docs document waitUntil for Node/Edge only. Resolved by B01 spike; fallback pinned in PRD.
- Fine-grained GitHub PAT: does not exist yet; created in B08 (needs-human).
- LangGraph Python packages: UNVERIFIED locally (no venv yet); installed and pinned in B02.

## Appendix B: drift found while authoring

- None found. Two clarifying pins made while authoring (not drift): the Shopify-style signature header is pinned to `X-Shopify-Hmac-SHA256` over the raw body; store identity header pinned to `X-Shopify-Shop-Domain`. Both consistent with the PRD's "Shopify-style" wording.
- Accepted risk restated: the OpenRouter key and its prepaid cap are shared with the portfolio concierge (Human decision 2026-07-09); a noisy demo day consumes shared budget. The 20/day cap bounds it.

## Appendix C: open questions / deferred

- TRIGGER_MODE: decided by B01; recorded here as a Note when known.
- Note (2026-07-09): TRIGGER_MODE=background. Spike on throwaway project `vercel-py-bg-spike` (FastAPI `BackgroundTasks`, 10s sleep, then `SPIKE_BG_DONE` log + in-memory marker). Five POSTs returned in 0.29-0.63s; all five markers reached `status=done` after ~10s; runtime logs for each POST include `SPIKE_ACK`, `SPIKE_BG_START`, and `SPIKE_BG_DONE`. Project deleted after the run.
- PR hygiene job (close stale `agent/*` PRs via GitHub Actions): v1.1, own small PRD.
- Portfolio UI page: own PRD in the portfolio repo; consumes the B09 API.
- on_hold order reprocessing after merged fixes: v1.1 candidate.
- Second marketplace shape (marketplace-channel style, distinct from the direct Shopify shape): v1.1 candidate.
- Langfuse tracing: optional; add only if effort is trivial during B07 (idea.md lists it as reusable; PRD does not require it).
- Local folder rename to `self-healing-ecommerce-oms`: between sessions (session state is keyed to the current path).
- Note (2026-07-09, post-B08 code review): env-inventory addendum: `KILL_SWITCH` (optional, arms the global kill switch read by /health and the agent-run reservation; now in .env.example). Migration 002 repoints `incidents.duplicate_of` to `orders(id)` so duplicate incidents link the original delivery per the PRD shape. `record_agent_run`/`agent_capacity_available` were replaced by an atomic `try_reserve_agent_run` (increment-then-compare) wired at the webhook trigger decision, so B09 must NOT add its own counting. Recipe applies now TOP-insert into the data files so fix PR diffs are literally +1/-0; the gate counts diffs git-style with no comma exemption.
