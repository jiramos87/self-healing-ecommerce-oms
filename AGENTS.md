# AI Agent Guide: self-healing-ecommerce-oms

> Cross-harness canonical guide. Claude Code deltas (imports, hooks, commands) live in [CLAUDE.md](CLAUDE.md). Keep workflow here; keep host-specific surface in the host file.

## Reading order

1. This file.
2. Engineering canon (plain paths; non-Claude harnesses do not expand `@import`):
   - `~/projects/agentic-dev-kit/rules/code-craft.md`
   - `~/projects/agentic-dev-kit/rules/testing.md`
   - `~/projects/agentic-dev-kit/rules/writing-and-prose.md`
   - `~/projects/agentic-dev-kit/rules/workflow-and-git.md`
   - `~/projects/agentic-dev-kit/rules/reference-systems.md`
   - Canon source of truth: https://github.com/jiramos87/agentic-dev-kit (rules/)
3. docs/idea.md (concept), then docs/prd/ (behavioral specs).

## Workflow

Product loop: Explore -> PRD -> Grill -> Implement -> Verify -> ship -> learn. Define behavior first (PRD, Given/When/Then acceptance), implement the smallest diff that satisfies it, grow tests from acceptance, verify with real gates, report honestly. Skills for each step: agentic-dev-kit `skills/`, vendored into `.claude/commands/`.

## Hard lines

Never commit, push, or merge unless explicitly asked. Grep for references before deleting any file. English everywhere. No em-dash. Full canon: rules files above.
