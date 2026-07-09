---
description: Reflect on the work session and feed the lessons back into the repo context, memory, and skills so the next agent starts better-equipped
---

You are closing the loop: prd -> implement -> verify -> learn. The work shipped; now make the toolchain that produced it a little better. This is the compounding step: capture what was learned this session and write it where a future agent will actually read it. You are improving context and tooling, not product behavior.

1. Reconstruct the session. Skim what actually happened: the diffs, the commands that failed before they worked, the dead ends, the corrections the human made, and any "I wish I had known this earlier" moments. Prefer evidence (transcript, git log, command history) over memory.
2. Classify each lesson by where it belongs:
   - Repo context (project rules) -> `CLAUDE.md` or the repo's conventions/gotchas doc: durable, project-specific facts ("run the API from apps/api so dotenv finds .env").
   - Memory (persistent, cross-session) -> a memory entry: preferences, working habits, and facts not derivable from the code.
   - Skills -> the relevant skill file: a missing step, a footgun to warn about, a sharper instruction.
3. Apply the smallest edits that capture each lesson. One fact per place; do not duplicate a learning across all three. Update an existing line rather than appending a near-duplicate, and link related notes where the format supports it.
4. Do not invent lessons to look productive. If nothing durable was learned, say so and change nothing. A no-op is a valid, honest outcome.
5. Report a short summary, grouped as skills improved / repo rules modified / memory entries added, with a one-line why for each.

Be honest, not flattering: the value is a toolchain that visibly compounds, not a changelog padded with restatements of what the code already says.
