---
description: Decompose a DEFINED PRD into a dependency-ordered, self-contained implementation backlog doc that sequential implementer sessions execute item by item via /backlog-implement
---

Build an implementation backlog from a PRD. Input: `docs/prd/{slug}.md` (must be Status: DEFINED; if DRAFT, stop and point to /prd-grill-me). Optional: `--refresh docs/backlogs/{doc}.md` to re-verify an existing backlog instead of authoring a new one. Adapted from territory-developer's improvement-backlog skill: this variant decomposes a greenfield PRD instead of auditing an existing surface.

Position in the loop: one expensive planning session writes ONE ordered backlog doc; cheap implementer sessions then run `/backlog-implement` per item with zero planning context beyond the doc header + their item. `/implement` remains the right tool for a small single-session PRD; use this when the PRD is too big for one session.

Template (the doc contract lives there): `docs/templates/implementation-backlog-template.md`.

1. **Load contract.** Read the PRD in full (acceptance, quality bar, dependencies, invariants, out-of-scope). Read the repo seams the work will touch (live code, not memory).
2. **Ground-truth pass.** Verify every PRD dependency claim against live code/infra where possible (schema, env, scripts, deployed services). Record verdicts for Appendix A; anything unverifiable is marked UNVERIFIED with what would verify it. PRD-vs-reality contradictions go to Appendix B and get surfaced to Javier before writing items.
3. **Decompose.** Slice the PRD into dependency-ordered items (aim for 0.5-1.5 day granularity). Every item passes the self-containment test: an implementer with ONLY the doc header + that item (+ ambient CLAUDE.md) can build it. Pin cross-item seams in the header (env-var names, paths, table names) so items cannot drift apart. Steps only a human can do (account signups, content review) get a needs-human flag inside the owning item.
4. **Write doc.** Instantiate the template at `docs/backlogs/{slug}-backlog-{YYYY-MM-DD}.md`: header, ledger (all items pending), items, appendices. Shape check before handoff: every item has typed acceptance, a files list, a depends-on line, and a PRD reference; every env var an item mentions appears in the header inventory.
5. **Register + hand off.** Append one progress line to `docs/build-plan.md`. Do NOT implement anything and do NOT commit. End with the item count, the top of the ledger, and the first dispatch: `/backlog-implement {doc-path} B01`.

Refresh mode: skip 3-4; re-run 2 against the doc's own items, update ledger rows contradicted by live code (with evidence), append a refreshed Appendix A.

Hard boundaries: item bodies are immutable once published (corrections append a "Note ({date}):" line); one backlog doc per PRD; never commit; stop after handoff.
