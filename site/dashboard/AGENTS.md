# site/dashboard/AGENTS.md

## Scope
This directory renders static dashboard pages and should consume prepared payloads.

## Rules
- Do not recalculate core business KPIs in page templates or page scripts.
- Prefer consuming analysis-layer payload fields directly.
- Page wording must be understandable by a non-expert store owner.
- Put conclusion before detail.
- Show confidence / caution text when data is incomplete.
- Missing sections must degrade gracefully instead of breaking rendering.

## Presentation guidance
Each business block should try to show:
- one-line conclusion
- why it matters
- what to do today / this week / this month