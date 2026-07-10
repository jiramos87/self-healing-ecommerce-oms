# Deploy and launch gate

How to deploy this service to Vercel (Python, Fluid Compute) and run the B10
launch gate against the live URL. The agent never merges anything; the one human
step in the gate is merging a fix PR mid-run.

## What ships where

- The whole FastAPI app deploys as a single Vercel Function. Vercel resolves the
  entrypoint from `tool.vercel.entrypoint = "api.index:app"` in `pyproject.toml`,
  so every route (`/health`, `/webhooks/orders`, `/demo/simulate`, `/incidents`,
  `/orders`) is served by one function. No `/api` path prefix is required.
- `vercel.json` sets `maxDuration: 60` (the agent finishes well under 60s) and
  trims `tests/` and `scripts/` from the bundle. The Python builder includes all
  other reachable files by default, so `app/data/*.json` and `docs/runbooks/*.md`
  ship without extra config.
- Fixed infra cost stays at 0: Hobby tier, the existing Railway Postgres instance,
  and the shared prepaid OpenRouter key.

## Prerequisites

- `vercel` CLI logged in to the target account.
- The `self_healing_oms` database exists on Railway with migrations applied
  (`python scripts/migrate.py`).
- The fine-grained GitHub PAT from B08 exists (this repo only: contents, issues,
  pull-requests write).
- Real values for every env var below.

## Environment variables (needs-human)

Provision all of these in the Vercel project (Production, and Preview if you want
preview deploys to work). Never commit real values; `.env.example` lists the names.

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Railway `self_healing_oms` connection string |
| `OPENROUTER_API_KEY` | Shared prepaid OpenRouter key (diagnose/extract/classify) |
| `OPENROUTER_BASE_URL` | Optional base URL override |
| `GROQ_API_KEY` | Groq fallback provider |
| `GITHUB_FIX_PAT` | Fine-grained PAT scoped to this repo |
| `GITHUB_REPO` | `jiramos87/self-healing-ecommerce-oms` |
| `WEBHOOK_SECRET` | HMAC secret for `X-Shopify-Hmac-SHA256` |
| `ADMIN_TOKEN` | Guards `POST /incidents/{id}/retry` |
| `KILL_SWITCH` | Optional; any of `1/true/yes` disarms all agent runs |
| `TRIGGER_MODE` | `background` (default on Vercel per the B01 spike) |

Add one from the CLI (repeat per variable, or use the dashboard):

```bash
vercel env add WEBHOOK_SECRET production
```

## Deploy

Link the project once, then deploy to production:

```bash
vercel link            # repo root; select/create the project
vercel deploy --prod   # or push to the connected default branch
```

Git-connected deploys are preferred: merging a fix PR to the default branch then
triggers the redeploy the merge-closes-loop pass depends on.

## Verify routing after the first deploy

The single-function preset serves every route. Confirm before running the gate:

```bash
curl https://<deployment-url>/health
# {"ok": true, "remaining_daily_agent_runs": 20, "daily_agent_run_limit": 20, ...}
```

If `/health` returns 404, Vercel resolved a different entrypoint. Re-check that
`pyproject.toml` has `[tool.vercel] entrypoint = "api.index:app"` and redeploy; as
a fallback, add a catch-all rewrite to `vercel.json`:

```json
{ "rewrites": [{ "source": "/(.*)", "destination": "/api/index" }] }
```

## Run the launch gate

The gate delivers signed webhooks directly (the public `/demo/simulate` endpoint
is capped at 3 requests / 10 min per IP, which 20 rapid runs would trip). It needs
`WEBHOOK_SECRET` (to sign) and `DATABASE_URL` (novelty checks read the same DB) in
the local shell:

```bash
export WEBHOOK_SECRET=...        # must equal the deployment's secret
export DATABASE_URL=...          # the same Railway database the deployment uses
python scripts/launch_gate.py --base-url https://<deployment-url>
```

The gate runs 20 deliveries across all five classes, a recurrence pass, and a
merge-closes-loop pass, then prints a pass/fail table and exits non-zero on any
failure. Terminal states asserted: `unknown_region`/`phone_format` -> `pr_opened`,
`duplicate_delivery` -> `duplicate`, `cancelled_order` -> `expected_behavior`,
`valid` -> order created with no incident.

### The one human step

During the merge-closes-loop pass the gate pauses and prints a fix PR URL. Merge
that PR, wait for the git-connected redeploy to finish (the new region mapping
only takes effect on a fresh deployment), then press Enter. The gate re-sends the
same region and asserts it now succeeds as a normal order while the original
`on_hold` order stays `on_hold`.

Run `--no-merge-loop` to skip the interactive step; the summary then reports
PARTIAL because that is not a full launch gate.

## Caps and repeat runs

- A full gate consumes about 6 of the 20 daily agent-run slots. Two or three runs
  in one UTC day are fine; more will start returning `capped` incidents.
- The preflight prints `remaining_daily_agent_runs` and warns when it is low.
- To reset the daily counter for another run on the same day (operator action on
  the shared DB):

```sql
DELETE FROM counters WHERE key = 'agent_runs' AND window_start = date_trunc('day', now() AT TIME ZONE 'UTC');
```

## Cleanup

Each fixable incident opens a real issue and PR against `GITHUB_REPO`. After a gate
run, close the leftover `agent/fix-*` PRs and their issues (except any you merged
for the merge-closes-loop pass). The standalone PR-hygiene job is a post-v1 item.

## Rollback

Use `vercel rollback` or promote a previous deployment from the dashboard. Data in
Railway is unaffected by a rollback; only the bundled data files revert.
