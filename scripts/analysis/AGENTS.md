# scripts/analysis/AGENTS.md

## Scope
This directory owns the analysis layer between SQLite and dashboard/page exports.

## Rules
- Reuse SQLite latest_* views before introducing new intermediate queries.
- Keep business rules explicit and comment the rationale.
- Prefer small functions with clear inputs/outputs.
- Separate:
  - metric construction
  - estimation logic
  - forecast logic
  - payload export logic
- Do not hide business logic only inside page rendering code.
- Any estimate must expose:
  - source basis
  - assumptions
  - uncertainty
- Any forecast must expose:
  - time window
  - driver factors
  - downgrade behavior when history is insufficient

## Output labels
Always label values as one of:
- actual
- estimate
- forecast