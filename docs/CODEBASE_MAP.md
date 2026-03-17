# CODEBASE_MAP

## Repo purpose
- This repo extends an existing retail workflow, not a blank-slate BI rebuild.
- The current canonical chain is:
  `Yeusoft capture JSON -> calibration/audit -> SQLite latest_* snapshot -> local business analysis -> HTML/JSON/CSV/Markdown export -> site/ self-check`
- Core truth lives in calibrated sales lines and the SQLite `latest_*` views, not in `site/dashboard/` artifacts.

## Canonical execution path
1. `scripts/yeusoft/scan.mjs`
   - Refreshes `reports/capture-cache/*.json`.
   - Writes scan status to `reports/scan-output/index.json`.
2. `scripts/tools/calibrate_sales.py`
   - Audits capture sources plus short-window Excel exports.
   - Picks `销售清单.json` as the master sales truth after store/doc-type filtering.
   - Writes audit markdown and calibrated CSV files to `reports/calibration/`.
3. `scripts/tools/build_analysis_db.py`
   - Reuses calibration loaders plus Yeusoft parsing helpers.
   - Writes the SQLite analysis database and `latest_*` views to `reports/calibration/black_tony_analysis.sqlite`.
4. `scripts/dashboard/main.py`
   - Reads the latest SQLite batch, optional cost snapshots, and optional Yeusoft highlight captures.
   - Builds metrics, decision text, monthly execution boards, report content, and export payloads.
5. `scripts/tools/publish_static_site.py`
   - Orchestrates end-to-end publish: capture refresh -> field audit -> SQLite build -> dashboard export -> manuals build -> readiness check.
6. `scripts/tools/check_pages_ready.py`
   - Verifies `site/` is publish-ready.

## Runtime ownership map
| Area | Main files | Responsibility | Main outputs |
| --- | --- | --- | --- |
| Capture | `scripts/yeusoft/scan.mjs`, `scripts/dashboard/yeusoft.py` | Refresh Yeusoft raw JSON and parse request/response payloads | `reports/capture-cache/*.json`, scan index |
| Calibration | `scripts/tools/calibrate_sales.py`, `scripts/dashboard/input.py` | Normalize sales-like sources, compare overlaps, produce trusted sales summaries | `reports/calibration/*.md`, `*.csv` |
| SQLite sync | `scripts/tools/build_analysis_db.py` | Persist batch lineage, sales, inventory, member, guide, retail, and reconciliation tables | `reports/calibration/black_tony_analysis.sqlite` |
| Dashboard analysis | `scripts/dashboard/main.py`, `scripts/dashboard/rendering.py` | Convert SQLite snapshot into business metrics, narratives, tables, charts, and payloads | in-memory `metrics` object |
| Static export | `scripts/dashboard/main.py::write_outputs` | Render HTML/Markdown/CSV/JSON for history and Pages copies | `reports/dashboard-history/*`, `site/dashboard/*` |
| Publish orchestration | `scripts/tools/publish_static_site.py`, `scripts/tools/check_pages_ready.py`, `scripts/docs_site/build.py` | Run the full publish pipeline and final validation | publish report, `site/` deliverables |
| Repo maps | `docs/*.md` | Record current architecture, data flow, SQLite usage, and payload contract | living documentation |

## Important directories
- `scripts/tools/`
  - Pipeline runners, calibration, SQLite build, publish orchestration, readiness checks.
- `scripts/dashboard/`
  - Current business logic, payload assembly, HTML rendering, and Yeusoft helper parsers.
- `scripts/analysis/`
  - Intended home for extracted analysis-layer modules.
  - Currently not the main source of business logic yet.
- `scripts/docs_site/`
  - Builds the manuals site under `site/manuals/`.
- `reports/`
  - Runtime artifacts: capture cache, calibration outputs, dashboard history, publish reports.
- `data/local/`
  - Optional cost snapshot and cost history inputs for profit analysis.
- `site/dashboard/`
  - Generated Pages-ready dashboard artifacts.
  - Treat this as output, not source of truth.
- `site/manuals/`
  - Generated manuals site.

## Priority entry files
- `scripts/tools/build_analysis_db.py`
- `scripts/tools/calibrate_sales.py`
- `scripts/dashboard/yeusoft.py`
- `scripts/dashboard/main.py`
- `scripts/tools/publish_static_site.py`
- `scripts/tools/check_pages_ready.py`

## Reusable logic already present
- `scripts/tools/calibrate_sales.py`
  - `load_capture_*`
  - `compare_sales_overlap`
  - `compare_master_to_product`
  - `compare_master_to_flow`
  - `build_daily_sales`
  - `build_monthly_sales`
  - `build_sku_sales`
- `scripts/tools/build_analysis_db.py`
  - `load_capture_inventory_*`
  - `load_capture_stock_flow`
  - `load_capture_vip_analysis`
  - `load_capture_member_rank`
  - `load_capture_guide_report`
  - `load_capture_retail_detail`
  - `prepare_quality_checks`
  - `prepare_*_reconciliation`
- `scripts/dashboard/yeusoft.py`
  - Shared capture decoding, request extraction, row extraction, and POS highlight builders.
- `scripts/dashboard/main.py`
  - `load_analysis_db_snapshot`
  - `build_*_from_analysis`
  - `build_metrics`
  - `build_time_strategy`
  - `build_execution_board`
  - `build_decision_engine`
  - `build_retail_consulting_analysis`
  - `build_export_payload`

## Safe extension points
- Add new analysis modules under `scripts/analysis/` that read `latest_*` views and return clearly labeled outputs.
- Extract reusable business helpers out of `scripts/dashboard/main.py` only when both payload and HTML need the same logic.
- Extend `build_export_payload()` under existing root sections before inventing a parallel payload format.
- Put new action-first page sections on top of the existing payload roots when possible; the monthly execution page now reads `execution_board` instead of inventing a second JSON file shape.
- Add new SQLite derived views if reuse is needed across multiple consumers.
- Keep HTML wording in `main.py` or shared helpers, not in `site/dashboard/` generated files.

## Current risks and gaps
- `scripts/dashboard/main.py` still owns most business-analysis logic.
- Same-season historical reference is not yet a first-class module.
- Profit depends on external cost snapshots and fallback margin assumptions.
- Inventory value is currently a retail-value proxy, not a cost valuation.
- `movement_docs` has no SKU-level lines, so inventory explanations cannot fully trace stock moves by style/color/size.
- `site/dashboard/*.html` are generated artifacts; direct edits will drift from the real source.
- `latest_*` views expose only the latest batch; any multi-batch historical analysis must query base tables intentionally.

## Guardrails for future work
- Do not redesign the SQLite schema unless explicitly asked.
- Do not bypass `scripts/tools/build_analysis_db.py` as the sync layer.
- Do not duplicate KPI logic into page files.
- Keep actual values, estimated values, and forecast values explicitly distinguishable in docs and payloads.
