# self-healing-ecommerce-oms: concept definition (pre-PRD)

Status: exploration output with decisions locked, base for /prd and /prd-grill-me. 2026-07-09.

## One-liner

A minimal ecommerce Order Management System whose webhook-ingestion failures are diagnosed and fixed by an autonomous agent: each failure becomes an incident, the agent investigates it against a runbook knowledge base and this codebase, then opens a GitHub issue and (when the fix is safe and mechanical) a fix PR. A human merges. A UI shows the whole pipeline live.

## Why this project

Target audience: hiring teams for "Full Stack AI Engineer" roles.

The thesis it proves: most portfolio AI is a chatbot that talks. This is an agent that acts, unattended, with real side effects (GitHub issues and PRs) and production-grade guardrails (idempotency, budget caps, file allowlists, human merge gate). It complements the existing portfolio concierge agent (RAG, conversational) with the other half of the skill set: event-driven autonomous operation.

It is also grounded in lived production experience building marketplace integrations for an ecommerce OMS: order-creation webhooks (Shopify and marketplace channels) failed daily; failures landed in an on-hold queue table, were retried by cron, and the unrecoverable ones became tickets for humans. The most iconic failure: a platform sending region codes or spellings missing from a hand-accreted region dictionary, fixed by a developer manually adding the entry. This project automates exactly that human loop, with the agent as the developer.

Real-world patterns this mirrors (public docs keep these generic; never name past employers or internal codebases):

- A region map accreted by hand, with dozens of spelling variants per region.
- An error thrown when the map misses: "State not found for: X".
- An error queue with bounded retries and a dead-letter list of non-retryable messages.
- An idempotency guard rejecting duplicate (store, order, platform) deliveries.
- Human ticket categories for address and region data problems.

## One demo run, narrated

1. Visitor presses "Simulate failing order" (or a script POSTs a signed Shopify-shaped webhook).
2. The simulator sends an order-creation payload with a region the OMS does not know, e.g. `province_code: "XN"` with `province: "Region de Nubaria"` (generated, plausible, guaranteed absent from the mapping).
3. The OMS validates the payload, fails at region resolution, creates the order in `on_hold` state, and records an incident with the full error body.
4. The agent wakes on the incident: fingerprints it, checks it is not a duplicate, classifies the error, retrieves the matching runbook, retrieves the relevant mapping file from the codebase.
5. It opens a GitHub issue (error body, diagnosis, runbook citation) and a PR adding the missing region entry to the mapping file, linked to the issue.
6. The UI timeline updates step by step: received, validated, failed, diagnosing (with per-node trace), issue opened (link), PR opened (link). The order stays on hold until a human merges; a merged mapping means the same region succeeds next time.

Total wall time target: under 60 seconds. Total LLM cost per run: about a cent.

## System shape

```
                     signed webhook (HMAC)
  Marketplace  ────────────────────────────►  OMS core (FastAPI, Python)
  simulator                                    - POST /webhooks/orders
  (fault injection menu)                       - validate -> create order | incident
                                               - incidents table (payload, error,
                                                 fingerprint, retries, status)
                                                          │ new incident
                                                          ▼
                                              Fix agent (LangGraph + OpenRouter)
                                              fingerprint/dedup -> classify ->
                                              retrieve runbook -> retrieve code ->
                                              diagnose -> act -> trace
                                                   │                    │
                                                   ▼                    ▼
                                              GitHub issue + PR    incident trace
                                              (never merges)            │
                                                                        ▼
                                              Observability UI (incident timeline,
                                              agent trace, GitHub links, trigger button)
```

Components:

1. Marketplace simulator: Shopify-flavored. Sends HMAC-signed webhooks (mirrors `X-Shopify-Hmac-SHA256`); only the simulator's secret is accepted. Fault-injection menu picks the error class; payload generators keep every run fresh.
2. OMS core: FastAPI. One webhook endpoint, order validation and creation, incidents persisted with a production-faithful shape (payload JSONB, error, fingerprint, retries, status). Product catalog and store config are hardcoded JSON files in the repo.
3. Fix agent: LangGraph (Python) mirroring the portfolio's proven pattern from `apps/web/lib/agent/graph.ts`: deterministic StateGraph, guardrail node first, deterministic (keyword-gated) tool execution instead of LLM tool-loops, because it is cheaper and reliable across cheap models.
4. Knowledge base: `docs/runbooks/*.md`, one runbook per error class, keyword retrieval. No embeddings in v1: the portfolio concierge already demonstrates RAG; this project's differentiator is action, and keyword retrieval over a dozen runbooks is honest engineering.
5. GitHub integration: issues and PRs via the existing PAT. Writes restricted to an allowlisted path set.
6. Observability UI: one screen. Incident list, detail timeline with per-node agent trace (node name, summary, tokens, latency), GitHub links, simulate button.

## Error taxonomy for the demo

Curated from a real production catalog of about twenty webhook-integration error classes. Four classes, four different agent behaviors, so the demo shows judgment, not just codegen:

| # | Class | Real analog | Agent action | Why infinitely repeatable |
| --- | --- | --- | --- | --- |
| E1 | Unknown region code | StateNotFound, the manual mapping-add fix | Issue + PR adding the mapping entry | Region generator invents plausible codes/spellings forever |
| E2 | Malformed phone/RUT the normalizer misses | DEFAULT_PHONE / DEFAULT_SSN fallback shims | Issue + PR appending one rule to the normalizer rules table (rules-as-data) | Format generator (new prefixes, separators) never dries up |
| E3 | Duplicate webhook delivery | ORDER_ALREADY_EXISTS dedup guard | No issue: incident marked duplicate, linked to the original | Replay any prior payload |
| E4 | Cancelled order / pending payment | "Order cancelled", "Order with pending payment" dead-letter list | Diagnose-only: issue-free, incident closed as expected behavior per runbook | Simulator flag |

E1 is the flagship: the fix PR is additive data (a mapping entry), so merging never un-seeds the demo. E4 is the guardrail showcase: the agent knowing when NOT to write code is the strongest senior signal in the project. E2 stays one-line by design because the normalizer is rule-table-driven (see Fix recipes below). Stretch class (post-v1): unknown SKU price mapping (marketplace-channel style per-SKU price keying).

## Fix recipes: constrained action space

The core mechanism that makes fix PRs cheap, deterministic, and safe. The LLM never edits files and never runs an agentic patch-search loop. Instead:

1. Every fixable error class has a typed recipe: target file (allowlisted, always a data file), a deterministic edit function, and post-edit validations.
2. The LLM's job ends at diagnosis plus structured extraction: it fills the recipe's parameter schema (e.g. `{class: unknown_region, province_code: "XN", region_name: "Region de Nubaria", state_id: 17}`) as validated structured output.
3. Deterministic code applies the edit in memory via the GitHub contents API (read file, insert one entry, create branch, commit, open PR). No repo checkout, no git binary, serverless-friendly.
4. Pre-PR gate, computed deterministically: exactly 1 file changed, additions within the recipe's line budget (1 for E1/E2), 0 deletions, path inside the allowlist, edited file still parses (JSON/YAML load) and the new key resolves. Any violation aborts to issue-only mode with the diagnosis attached. Worst case is a good issue, never a bad PR.

Consequences: one-file one-line diffs are guaranteed by construction, not by prompting; token cost per fix is one classifier call plus one extraction call plus one issue-body generation; "agent running in circles" is structurally impossible because there is no search loop to run. The fixable surface of the codebase is designed for this: region mappings and normalizer rules live in data files (JSON/YAML), not code. The README states this honestly: the agent diagnoses with an LLM and applies fixes through typed recipes, because unconstrained agentic patching is neither cheap nor safe.

## Reused stack (zero new accounts, zero new fixed cost)

| Concern | Reuse | Source of pattern |
| --- | --- | --- |
| LLM | OpenRouter prepaid via OpenAI-compatible client. Default `google/gemini-3.5-flash`, classifier `google/gemini-3.1-flash-lite` | portfolio `apps/web/lib/agent/models.ts`, `model-catalog.ts` |
| Fallback | Groq free tier, `llama-3.3-70b-versatile` | portfolio fallback chain (OpenRouter -> Groq -> honest "unavailable") |
| Orchestration | LangGraph, Python package this time | portfolio `graph.ts` StateGraph pattern |
| Spend guardrails | Prepaid cap + per-IP and global rate limits + kill switch, fails closed | portfolio `limits.ts` (Upstash) |
| Tracing | Langfuse existing account, fails open | portfolio `tracing.ts` |
| Hosting | Vercel free tier: FastAPI runs natively on Fluid Compute (Python 3.13/3.14, 300s default timeout) | portfolio web deploy |
| GitHub | Existing account + PAT | n/a |

Correction from exploration: the portfolio embeddings are NOT on Vercel free tier; they are Gemini `gemini-embedding-001` (free AI Studio key) stored in pgvector on the Railway Postgres. Irrelevant for v1 here since v1 has no embeddings.

## Cost model

- Fixed: 0. Vercel Hobby, GitHub, Groq free tier, Langfuse free tier.
- Per demo run: one classifier call (about 1k tokens, gemini-3.1-flash-lite) plus one diagnosis call (10 to 30k input, 1 to 3k output on gemini-3.5-flash). Well under 1 cent per run at 2026 OpenRouter pricing.
- Ceiling: OpenRouter prepaid with auto-top-up off is the hard cap, exactly like the portfolio. Decision below on sharing the existing 5 dollar/month key vs a second key under the same account.

## Persistence (the "minimize DB cost" answer)

| Option | Pros | Cons |
| --- | --- | --- |
| A. GitHub-as-DB (incidents are issues; state via labels) | True zero infra; poetic | Awkward for step-level traces; API rate limits; weakens the "errors logged to a DB table" story being told |
| B. Reuse existing Railway Postgres (new schema/database on the already-running instance) | Real errors table mirroring production OMS patterns; marginal cost about zero; no new account | Couples demo to portfolio infra; Railway is usage-billed |
| C. JSON state on Vercel Blob free tier | Free, simple | Concurrency is hand-rolled; less credible as an OMS |

Recommendation: B for incidents and traces (the ticket-table story is the point), with hardcoded JSON files in-repo for catalog/stores, and GitHub issues/PRs as the human-facing artifact layer. If pure-zero-infra becomes a goal, A+C is the fallback and the schema is small enough to swap.

## Guardrails (features, not chores)

- The agent opens PRs; it never merges. Branch naming `agent/fix-<fingerprint>`.
- Fixes apply only through typed recipes (see Fix recipes): file allowlist, one-file one-line diff gate, abort to issue-only on any violation. One PR per fingerprint.
- Idempotency: fingerprint = hash(error class + store + offending value). Recurrences comment on the existing issue instead of opening a new one (mirrors the alert-dedup-key pattern from production).
- Budget: per-run token cap, per-day run cap, global kill switch, fails closed (portfolio `limits.ts` posture).
- Webhook HMAC validation; unsigned or mis-signed payloads rejected before any processing.
- Honesty flags in the UI when degraded (fallback model, capped budget), streamed like the portfolio's `servedBy`/`degraded`.

## Demo repeatability

- Generators (regions, phone formats) guarantee the fault pool never dries, so merged fixes never kill the demo. This inverts the usual seeded-bug reset problem: fixes are additive.
- The agent PRs against this same repo: the self-healing story at full strength, safe because fixes are additive data/normalizer entries inside the allowlist.
- Unmerged agent PRs accumulate: needs a cleanup policy (open decision below).

## Deliverables (definition of done)

- Live URL: FastAPI service on Vercel plus the observability UI.
- Screenshots, no video. README with the architecture diagram and a grounding section phrased as generic production ecommerce OMS experience (no employer names).
- Portfolio exhibit entry (the agentic-dev-kit MCP `scaffold_exhibit` tool emits the Project record for the portfolio app).
- Docs trail: this file, then PRD(s) in `docs/prd/`, grilled.

## Out of scope for v1

- Embeddings/RAG retrieval (keyword over runbooks suffices; revisit only if runbooks grow).
- Auto-merge or auto-deploy of agent fixes.
- Additional marketplaces (a second marketplace-channel shape is a stretch goal; v1 is Shopify-shaped only).
- Real Shopify account integration; auth; multi-tenancy.

## Decisions (locked 2026-07-09)

1. UI home: a TS/Next.js page in the portfolio app consuming this service's API. This service also exposes read-only JSON status endpoints as its own surface.
2. Persistence: reuse the existing Railway Postgres instance (new database/schema on it). Catalog and store config stay as hardcoded JSON files in this repo.
3. OpenRouter key: share the existing prepaid key and its cap. The per-day run cap and kill switch protect the concierge's budget share.
4. Agent trigger: async task inside the same webhook invocation (no cron, no polling). A free GitHub Actions scheduled sweep over unresolved incidents can be added later if ever needed.
5. Framework: FastAPI on Vercel Fluid Compute (Python). Frontend: Next.js (portfolio app).
6. PR hygiene: GitHub Actions scheduled workflow (free on public repos) closes unmerged `agent/*` PRs older than N days and prunes branches.
7. Name: `self-healing-ecommerce-oms` (keeps the ecommerce keyword). Local folder rename happens between sessions; GitHub name is set at `gh repo create` time.
8. E2 ships in v1: rules-as-data makes the "code fix" class a one-line data addition (see Fix recipes).

## Next

Run `/prd` to turn this into a behavioral PRD, then `/prd-grill-me`.
