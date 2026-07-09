---
description: Diff a PRD against the shipped product, log the deltas, and update the PRD to match reality
---

You are closing the loop: prd -> implement -> verify -> reconcile. The product has drifted from its PRD (scope dropped, metrics promoted, features added that were never written down). Make the spec honest again. You are updating the doc, not the code; do not change product behavior here.

1. Load both sides. Read the PRD (`docs/PRD.md` or `docs/prd/{slug}.md`) and the shipped reality: the relevant code, the seed/fixtures, the live config, and any real metrics. Where possible, check the deployed app, not just the source.
2. Diff acceptance vs reality. For each Given/When/Then and each scope / quality-bar line, classify it as: met, dropped, promoted (target/placeholder -> real), deferred, or shipped-beyond-spec (built but never written down).
3. Record the deltas in the PRD's `Scope changes` log first (dated, one line each, with a why). Do not silently rewrite the body before logging.
4. Update the PRD body to match the live product, and move `Status` to SHIPPED once the body and reality agree.
5. Report a short table of deltas, and flag which are real gaps (promised, not built) versus intentional changes.

Be honest, not flattering: a too-perfect PRD reads as fabricated. The recorded deltas are evidence the loop adapts, which is worth more than a spec that pretends it never moved.
