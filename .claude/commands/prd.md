---
description: Define one feature as a behavioral PRD via polling, then write it to docs/prd/{slug}.md
---

You are defining ONE product feature before implementation. Do not write code.

1. Load context: read the relevant existing code and any linked docs so questions are grounded.
2. Poll the user one decision at a time until the inputs/outputs (the data contract), the user experience, the edge cases (both sides of every boundary, empty/missing/duplicate inputs, failure modes), and "done looks like" are unambiguous. Prefer multiple-choice questions, each with a recommended default. Be persistent; do not stop while a material decision is undecided.
3. Write a behavioral PRD to `docs/prd/{slug}.md` using `templates/prd-template.md`. Behavior only: Given/When/Then acceptance, a concrete quality bar, and out-of-scope. Do NOT prescribe class names or implementation steps.
4. Stop at "PRD ready + next command". Do not implement.

One feature per PRD. If scope balloons, split it.
