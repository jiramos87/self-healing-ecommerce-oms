---
description: Grill a draft PRD with relentless polling rounds until design, behavior, and dependencies are locked, then rewrite it to a DEFINED spec
---

You are hardening a DRAFT PRD into a DEFINED one. Do not write product code. The input is an existing PRD (`docs/prd/{slug}.md`), typically the output of `/prd` or a hand-written draft with open questions and placeholders.

1. Load the draft and the ground truth. Read the PRD, the code and docs it links, and everything it depends on (third-party APIs, licenses, data sources, quotas). Build a punch list of every open question, every placeholder ("to detail", "to decide", "tentative"), and every unresolved dependency.
2. Grill in themed rounds. Poll the user one decision at a time via the question/polling tool, grouped into rounds: (a) problem and audience, (b) core experience, happy path, and the input/output contract (data shapes and result states), (c) edge cases and failure modes — force the sweep: both sides of every boundary, empty/missing/duplicate inputs, and each failure/degradation path, (d) data model and content sourcing, (e) dependencies and how each is solved (APIs, auth, licensing, quotas, fallbacks), (f) scope boundaries, the launch cut, and invariants that must not change, (g) success metrics and the quality bar. Prefer multiple-choice questions, each with a recommended default and a one-line rationale. Be relentless: do not advance a round while a material decision is undecided, and restate the still-open items at the top of each round until the user commits.
3. Resolve every dependency explicitly. For each external dependency, pin four things: the chosen approach, the fallback when it fails or vanishes, the cost / quota / licensing reality, and what runs at runtime versus at curation time. No dependency leaves the grill as "TBD".
4. Reflect decisions back after each round. Summarize what is now locked and what is still open. Close a round only when nothing material is undecided.
5. Rewrite the PRD to DEFINED using `templates/prd-template.md`. Fill every placeholder, encode the agreed behavior as Given / When / Then acceptance, set a concrete quality bar and explicit out-of-scope, and add a Dependencies section with the resolution for each one. Record every decision that changed the draft in the Scope changes log, then move `Status` to DEFINED.
6. Stop at "PRD DEFINED + next command" (`/implement`). Do not implement.

One product or feature per PRD. If scope balloons, split it.
