---
description: Integrate a Claude Design handoff (tokens + components) into a Next.js + Tailwind + shadcn app
---

Integrate a Claude Design output into a Next.js (App Router) + Tailwind + shadcn/ui project.

1. Place the token sheet at `app/globals.css` (Tailwind v4 `@theme inline`), or wire the `:root` / `.dark` blocks plus `tailwind.config.ts` for v3.
2. Initialize shadcn if needed, then add the components the design uses (`npx shadcn@latest add ...`). The tokens already match the shadcn contract, so no renaming.
3. Build the pages from the design spec using the tokens and components. Never hardcode colors; reference the tokens (the brand accent maps to `--primary`).
4. Verify dark + light, AA contrast, and the gradient stays on the primary CTA only.
5. Run the `verify` skill. Keep the raw design handoff (`.dc.html` / `support.js`) in `design-reference/`, never shipped.
