---
description: Implement a feature from its PRD with minimal diffs, then run the verify gate
---

Implement the feature defined in `docs/prd/{slug}.md`.

1. Read the PRD acceptance, quality bar, invariants, and out-of-scope. If the acceptance is ambiguous, stop and ask. Restate the acceptance scenarios + edge cases as a checklist, and map each one to a planned test.
2. Identify the seam: which layer / extension point this plugs into, and what must stay unchanged (the pure core, public contracts, the PRD's invariants). Prefer extending via data/config over editing core logic. Then plan the smallest diff that satisfies the acceptance, matching the surrounding code style.
3. Implement in place. Grow tests for the feature from the checklist in step 1 — one test per acceptance scenario AND per edge case, asserting both sides of every boundary (red then green).
4. Run the verify gate (see the `verify` skill). Iterate until green.
5. Stop before commit. Summarize what changed (and which invariants you preserved) and the next command.

Do not exceed the PRD scope. New ideas become new PRDs.
