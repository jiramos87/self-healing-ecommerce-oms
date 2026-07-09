---
description: Execute one item from an implementation backlog doc (minimal diff, typed acceptance gates, ledger update), then hand off the next item
---

Implement one item from an `implementation-backlog/v1` doc. Args: `{doc-path} {B-id | next} [--through {B-id}]`. `next` = first pending ledger row top-down. `--through` loops items sequentially until the target id, stopping on the first blocked. Doc contract: `docs/templates/implementation-backlog-template.md`; author skill: /improvement-backlog.

1. **Load contract.** Read the doc header + ledger + ONLY the assigned item (token economy: other items exist for other sessions; read another item only when yours names it in Depends-on and you need its seam). Check Depends-on rows are done; if not, report and stop. Claim your row: set it in-progress. If it is already in-progress or done, refuse the double-claim and stop (parallel sessions share this worktree).
2. **Implement.** Smallest diff that satisfies the item's Change + Acceptance. The Files list is the expected surface: touching outside it is allowed but must be noted in your ledger evidence. The PRD referenced in the header is the behavior source of truth when the item is ambiguous; the item body is never edited to fit the code.
3. **Verify by acceptance type.** Every acceptance line, by prefix: `build:` run `pnpm check-types && pnpm lint && pnpm build`; `test:` write/extend the named jest spec, red then green; `manual:` run the exact command/interaction and capture the output; `visual:` verify in the preview and screenshot (dark + light when the item says so); `eval:` run the eval script and meet the stated score. An acceptance still failing after 2 fix iterations: mark the row blocked with evidence and stop (in --through mode, stop the loop there).
4. **Ledger update.** Update YOUR row only: status (done | blocked | skipped + reason), date, `git rev-parse --short HEAD`, evidence string (test name / output summary / screenshot path / score). Never touch other rows or any item body.
5. **Hand off.** One product-language line on the outcome, then the next command: `/backlog-implement {doc-path} next` (or "backlog complete" when no pending rows remain).

Hard boundaries: never commit (developer's call); never re-rank or rewrite items (a wrong/stale item = blocked + reason, not an improvised different fix); scope `git add` suggestions to your own files (shared worktree).
