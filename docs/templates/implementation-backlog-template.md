# {Title} implementation backlog ({date})

backlog-format: implementation-backlog/v1
prd: docs/prd/{slug}.md (must be Status: DEFINED)
scope: {what this backlog covers; explicit exclusions}
ship-target: {date or "none"}
contract: {global rules every item inherits: verify gate, honesty rail, cost ceilings, style rules}
env-inventory: {every env var items reference, split runtime vs curation-only, so names stay consistent across items}

Items are ordered by dependency: suggested execution order = ledger order. Each item is
self-contained: an implementer with ONLY this doc's header + their assigned item (plus the
repo's CLAUDE.md, always ambient) can build it without the authoring session's context.
Effort: S < 0.5 day, M = 0.5-1.5 days, L > 1.5 days.

## Ledger

| item | status | date | sha | evidence |
|---|---|---|---|---|
| B01 | pending | - | - | - |
<!-- one row per item. status: pending | in-progress | done | skipped | blocked.
     Single-writer: the implementer claims a row (in-progress) and updates ONLY that row.
     evidence = test name / command output summary / screenshot path / eval score.
     skipped and blocked require a reason in evidence. sha = short HEAD at update time.
     Item bodies below are immutable after publish: corrections append a
     "Note ({date}):" line, never a rewrite. -->

---

## B{NN}. {Imperative title} [{S|M|L}] (PRD: {sections/acceptance lines this item implements})

**Goal.** {What exists when this is done, in behavior terms. Cite the PRD lines it satisfies.}

**Change.** {The build, 3-8 lines. Pin the seams that must not drift (paths, env names, table
names, model ids); leave internals to the implementer. Name in-repo precedent when one exists.
Flag "needs-human" for steps only Javier can do (account signups, content review).}

**Acceptance.** {2-4 checks, each TYPED so the implementer knows the gate:
- build: the repo verify gate passes (pnpm check-types && pnpm lint && pnpm build)
- test: named jest spec (apps/api) red then green
- manual: exact command or interaction + expected observable output
- visual: preview screenshot of the described state (dark + light when UI)
- eval: golden-set run meets the stated score}

**Files.** {Expected touch list, repo-relative. Touching outside it = note in ledger evidence.}

**Depends on.** {B-ids that must be done first, or "none".}

---

## Appendix A: ground-truth verdicts

<!-- Facts verified against live code/infra at authoring time, with how they were verified.
     The implementer trusts these without re-deriving; anything UNVERIFIED is marked so. -->

## Appendix B: drift found while authoring

<!-- Claims in docs/PRD contradicted by live code at authoring time. -->

## Appendix C: open questions / deferred

<!-- Decisions intentionally left to build time, found-but-out-of-scope items, v1.1 candidates. -->
