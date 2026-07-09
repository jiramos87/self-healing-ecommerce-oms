# self-healing-ecommerce-oms: build context

Portfolio project: a minimal ecommerce Order Management System whose webhook-ingestion errors are diagnosed and fixed by an autonomous agent (GitHub issue + fix PR, human merges). Public. Target audience: Full Stack AI Engineer hiring teams.

## Canon (imported rules)

@~/projects/agentic-dev-kit/rules/code-craft.md
@~/projects/agentic-dev-kit/rules/testing.md
@~/projects/agentic-dev-kit/rules/writing-and-prose.md
@~/projects/agentic-dev-kit/rules/workflow-and-git.md
@~/projects/agentic-dev-kit/rules/reference-systems.md

<!-- Imports resolve on machines with the kit cloned at ~/projects/agentic-dev-kit. -->
<!-- Canon source: https://github.com/jiramos87/agentic-dev-kit (rules/). Missing imports are non-fatal for other clones. -->
<!-- Validate after editing imports: node ~/projects/agentic-dev-kit/tools/validate-imports.mjs --file CLAUDE.md -->
<!-- If a TypeScript UI lands in this repo, re-add: @~/projects/agentic-dev-kit/rules/stack-notes/typescript-node.md -->

## What this repo is

Self-healing OMS demo. Python backend (FastAPI) receives Shopify-style order webhooks; failures become incidents; a LangChain + OpenRouter agent diagnoses each incident against a markdown knowledge base and this codebase, then opens a GitHub issue and a fix PR. Concept doc: docs/idea.md. UI surface and final architecture get locked via /prd and /prd-grill-me.

## Commands

TBD: scaffold pending PRD. The verify gate for Python here will be lint (ruff) + typecheck (mypy or pyright) + tests (pytest) + app boot.

## Repo-specific rules

- Cost ceiling is a feature: OpenRouter prepaid credit only, cheap models, no new accounts or billing (no Anthropic API). Fixed infra cost must stay at 0 (free tiers, hardcoded JSON data, GitHub-as-database where sane).
- The agent opens issues and PRs; it never merges. Guardrails are part of the product story.
- Seeded error classes must be repeatable: fixes must not exhaust the demo (e.g. unknown region codes are generated, so the pool never runs dry).
- Public-facing content (README, docs/, issues, PRs, code comments) never names past employers or their internal codebases. Grounding is always phrased as "production ecommerce OMS experience". Private references live in session memory only.
- Fix PRs are recipe-generated, never free-form: the LLM only fills a typed parameter schema; deterministic code edits allowlisted data files via the GitHub contents API. Hard gate before opening a PR: exactly 1 file, additions within the recipe's line budget (1 for E1/E2), 0 deletions; any violation degrades to issue-only. Fixable surfaces live in data files (mappings, normalizer rules), not code.

## Gotchas

- TRIGGER_MODE=background (2026-07-09 B01 spike): FastAPI `BackgroundTasks` reliably complete after the HTTP response on Vercel Fluid Compute for Python (5/5 runs; ~10s delayed marker present in runtime logs and in-memory poll). Wire the agent as an in-invocation background task, not simulate-orchestrated.

## Docs map

- docs/idea.md: expanded concept definition (base for the PRD and grill).
- docs/prd/self-healing-oms-v1.md: v1 behavioral spec (DEFINED).
- docs/backlogs/self-healing-oms-v1-backlog-2026-07-09.md: dependency-ordered implementation backlog (execute via /backlog-implement).
- docs/build-plan.md: one-line progress ledger across sessions.
- docs/templates/implementation-backlog-template.md: backlog doc contract.
