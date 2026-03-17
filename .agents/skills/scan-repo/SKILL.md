---
name: scan-repo
description: Scan this repository, update codebase maps, and identify the right extension points before implementation.
---

# scan-repo

Use this skill when the task requires understanding the repository before coding.

## Goals
- scan the codebase
- identify the current data flow
- identify reusable logic
- identify extension points
- update repository maps under `docs/`

## Required reading order
1. `scripts/tools/build_analysis_db.py`
2. `scripts/tools/calibrate_sales.py`
3. `scripts/dashboard/yeusoft.py`
4. `scripts/dashboard/main.py`
5. files under `docs/`

## Required outputs
Update or create:
- `docs/CODEBASE_MAP.md`
- `docs/DATAFLOW_MAP.md`
- `docs/SQLITE_ANALYSIS_MAP.md`
- `docs/DASHBOARD_PAYLOAD_MAP.md`

## Guardrails
- Do not rewrite the database schema.
- Do not replace the current JSON -> SQLite -> analysis -> export pipeline.
- Do not change business logic unless explicitly asked.
- When field meaning is unclear, record assumptions instead of inventing certainty.

## Success criteria
- repository structure is summarized
- data flow is documented
- existing dashboard logic reuse points are identified
- missing analysis-layer modules are listed
- page integration points are documented