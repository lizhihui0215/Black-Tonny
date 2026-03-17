# AGENTS.md

## Repo purpose
This repository builds a retail business analysis workflow:

capture JSON -> sync to SQLite -> local analysis -> export JSON/CSV/HTML -> static pages self-check

The agent must extend the analysis layer and decision-support layer on top of the existing pipeline.
Do not rebuild the database. Do not replace the current data flow.

## Non-negotiable rules
- Do not redesign the SQLite schema unless explicitly requested.
- Do not replace existing ETL responsibilities in `scripts/tools/build_analysis_db.py`.
- Prefer reusing current latest_* views, existing dashboard logic, and current export payload structure.
- Separate:
  - actual values
  - estimated values
  - forecast values
- Any business conclusion must state whether it is:
  - directly observed
  - estimated
  - forecasted
- If data is insufficient, say so explicitly. Never fabricate historical comparisons.

## Required working order
Before proposing code changes, read in this order:
1. `scripts/tools/build_analysis_db.py`
2. `scripts/tools/calibrate_sales.py`
3. `scripts/dashboard/yeusoft.py`
4. `scripts/dashboard/main.py`
5. `docs/CODEBASE_MAP.md`
6. `docs/DATAFLOW_MAP.md`
7. `docs/SQLITE_ANALYSIS_MAP.md`
8. `docs/DASHBOARD_PAYLOAD_MAP.md`

## Two-phase workflow
Phase 1:
- scan and understand the repository
- summarize current data flow
- summarize reusable logic
- identify gaps
- propose an implementation plan

Phase 2:
- modify or add code
- keep changes incremental
- preserve current pipeline and payload compatibility

## Business-analysis expectations
The analysis layer should cover:
- overall business overview
- inventory health
- sales performance
- best sellers
- slow movers
- stockout risk
- overstock risk
- sell-through / days of supply
- product mix optimization
- gross margin / discount analysis if fields support it
- current inventory value
- profit estimate to date
- today's actions
- next 7 days actions
- next 30 days actions
- quarterly actions
- same-season historical reference if data is sufficient
- data quality / confidence reminders

## Reuse guidance
Prefer reusing:
- existing latest_* SQLite views
- functions already present in `scripts/dashboard/main.py`
- current dashboard payload format
- current static page data contract

Avoid:
- duplicating business logic in multiple files
- recalculating the same KPI separately in page code
- pushing complex opaque scoring logic into one large script

## Output requirements
Every analysis output should try to include:
- conclusion
- evidence
- recommended action
- data source
- confidence / caveat

## Validation before finishing
After changes:
- verify SQL queries still run
- verify exported JSON/CSV/HTML still generate
- verify static page payload fields remain compatible
- verify newly added sections degrade gracefully when data is missing