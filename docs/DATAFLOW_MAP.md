# DATAFLOW_MAP

## Canonical pipeline
`scripts/yeusoft/scan.mjs`
-> `scripts/tools/calibrate_sales.py`
-> `scripts/tools/build_analysis_db.py`
-> `scripts/dashboard/main.py`
-> `reports/dashboard-history/*` and `site/dashboard/*`
-> `scripts/tools/check_pages_ready.py`

## Stage 1: Capture JSON
### Owner
- `scripts/yeusoft/scan.mjs`
- `scripts/dashboard/yeusoft.py`

### Inputs
- Yeusoft online pages and APIs.
- Local credentials/config loaded by `scripts/tools/local_dashboard_service.py`.

### Outputs
- `reports/capture-cache/*.json`
- `reports/scan-output/index.json`

### Notes
- Raw capture files preserve request/response bodies.
- `capturedAt` in the JSON is the runtime timestamp used later as one of the data freshness candidates.
- `scripts/dashboard/yeusoft.py` is the shared parser for request extraction, response extraction, row normalization, and POS highlight summaries.

## Stage 2: Calibration and source choice
### Owner
- `scripts/tools/calibrate_sales.py`

### Upstream sources it loads
- `销售清单.json`
- `店铺零售清单.json`
- `商品销售情况.json`
- `每日流水单.json`
- `出入库单据.json`
- Short-window Excel exports via `scripts/dashboard/input.py`

### What it decides
- `销售清单.json` is the master sales truth after:
  - store filter
  - doc type filter
  - total-row removal
  - field normalization
- `店铺零售清单.json` stays a validation source, not a merged truth source.
- `商品销售情况.json` stays a cumulative validation source.
- `每日流水单.json` stays a cash/payment validation source.
- `出入库单据.json` stays an inventory-context source.

### Main reusable logic
- `normalize_sales_lines()`
- `compare_sales_overlap()`
- `compare_master_to_product()`
- `compare_master_to_flow()`
- `build_daily_sales()`
- `build_monthly_sales()`
- `build_sku_sales()`

### Outputs
- `reports/calibration/source_inventory.md`
- `reports/calibration/source_comparison.md`
- `reports/calibration/summary.md`
- `reports/calibration/calibrated_order_lines.csv`
- `reports/calibration/daily_sales_calibrated.csv`
- `reports/calibration/monthly_sales_calibrated.csv`
- `reports/calibration/sku_sales_calibrated.csv`

### Value labels at this stage
- Directly observed:
  - calibrated master sales lines
  - daily/monthly/SKU aggregates derived deterministically from those lines
  - overlap/cumulative/cash comparison results
- Estimated:
  - none intentionally added here beyond deterministic ratios and diffs
- Forecast:
  - none

## Stage 3: SQLite sync
### Owner
- `scripts/tools/build_analysis_db.py`

### Inputs reused from calibration
- `load_capture_sales_master()`
- `load_capture_store_retail_validation()`
- `load_capture_product_sales()`
- `load_capture_daily_flow()`
- `load_capture_movement()`
- `build_daily_sales()`
- `build_monthly_sales()`
- `build_sku_sales()`

### Additional capture-only loaders
- `load_capture_inventory_detail()`
- `load_capture_inventory_sales()`
- `load_capture_stock_flow()`
- `load_capture_vip_analysis()`
- `load_capture_member_rank()`
- `load_capture_guide_report()`
- `load_capture_retail_detail()`

### What gets written
- Batch lineage:
  - `import_batches`
  - `source_files`
- Core sales:
  - `sales_order_lines`
  - `daily_sales_summary`
  - `monthly_sales_summary`
  - `sku_sales_summary`
- Inventory and retail snapshots:
  - `inventory_detail_snapshots`
  - `inventory_sales_snapshots`
  - `stock_flow_snapshots`
  - `size_metric_breakdowns`
  - `retail_detail_snapshots`
- Membership and guide snapshots:
  - `vip_analysis_members`
  - `member_sales_rank`
  - `guide_report_summary`
- Validation and reconciliation:
  - `quality_checks`
  - `order_reconciliation_results`
  - `daily_reconciliation_results`
  - `sku_reconciliation_results`
- Batch tables still queried directly later:
  - `product_sales_snapshot`
  - `movement_docs`

### Access pattern after sync
- Preferred read path: `latest_*` views tied to `latest_import_batch`.
- Current batch-only exceptions in dashboard code:
  - `product_sales_snapshot`
  - `movement_docs`

### Value labels at this stage
- Directly observed:
  - raw snapshot tables
  - summary tables derived deterministically from the current batch
- Estimated:
  - none stored as business forecasts
- Forecast:
  - none stored

## Stage 4: Dashboard analysis layer
### Owner
- `scripts/dashboard/main.py`

### Load step
- `load_analysis_db_snapshot()` reads the latest SQLite batch and returns DataFrames for:
  - master sales
  - validation sales
  - daily/monthly summaries
  - product snapshot
  - inventory snapshots
  - stock flow
  - size breakdowns
  - members / member rank / guide summary
  - retail detail
  - movement docs
  - quality checks

### Adaptation step
- `build_dashboard_data_from_analysis()` converts SQLite fields into the existing Chinese-column DataFrame contract expected by downstream dashboard logic.
- This preserves compatibility with the current dashboard layer without recalculating the ETL.

### Business-analysis step
- `build_metrics()` computes:
  - summary cards
  - sales / inventory / category / member tables
  - replenish / seasonal / clearance action tables
  - action summary counts
  - insight cards
- Optional enrichments:
  - cost snapshot and cost history for profit calculations
  - Yeusoft highlight bundle via `build_yeusoft_report_highlights()`

### Narrative and strategy step
- `build_time_strategy()`
- `build_execution_board()`
- `build_decision_engine()`
- `build_retail_consulting_analysis()`
- `build_today_focus()`
- `build_dashboard_tips()`

### Value labels at this stage
- Directly observed:
  - most sales, inventory, member, guide, category, and reference tables
  - `data_capture_at`
  - Yeusoft highlight summaries
- Estimated:
  - `estimated_inventory_days`
  - replenish / clearance / seasonal heuristics
  - breakeven and profit-to-date when cost basis falls back to historical/default margin
  - management narratives that infer likely causes from observed metrics
- Forecast:
  - `profit_snapshot.projected_*`
  - decision headline/summary when talking about month-end outcomes
  - daily/weekly/monthly action plans in `time_strategy`
  - monthly execution-board risk cards when they reference month-end profit outcomes

## Stage 5: Export
### Owner
- `scripts/dashboard/main.py::build_export_payload`
- `scripts/dashboard/main.py::write_outputs`

### Output roots
- `meta`
- `summary_cards`
- `today_focus`
- `execution_board`
- `health_lights`
- `time_strategy`
- `decision`
- `consulting_analysis`
- `dashboard_tips`
- `insights`
- `tables`

### File outputs
- History HTML:
  - `reports/dashboard-history/index.html`
  - `reports/dashboard-history/details.html`
  - `reports/dashboard-history/monthly.html`
  - `reports/dashboard-history/quarterly.html`
- History data:
  - `reports/dashboard-history/data/dashboard.json`
  - `reports/dashboard-history/data/details.json`
  - `reports/dashboard-history/data/monthly.json`
  - `reports/dashboard-history/data/quarterly.json`
  - `reports/dashboard-history/data/manifest.json`
- History side exports:
  - summary markdown
  - business report markdown
  - replenish CSV
  - clearance CSV
  - category risk CSV
- Mirrored Pages copies under `site/dashboard/`

### Compatibility rule
- HTML, Markdown, CSV, and JSON all derive from the same `metrics` object.
- Do not move KPI logic into page files.

## Stage 6: Publish orchestration
### Owner
- `scripts/tools/publish_static_site.py`

### Ordered steps
1. Optional capture refresh via `scan.mjs`
2. Field audit via `scripts.yeusoft.build_field_audit`
3. SQLite build via `scripts.tools.build_analysis_db`
4. Dashboard export via `scripts.dashboard.main`
5. Manuals rebuild via `scripts.docs_site.build`
6. Final readiness check via `scripts.tools.check_pages_ready`

### Publish report outputs
- `reports/dashboard-history/静态发布报告_latest.md`
- `reports/dashboard-history/静态发布报告_latest.json`

## Stage 7: Static pages and self-check
### Owner
- `scripts/tools/check_pages_ready.py`

### What it validates
- required `site/` files exist
- dashboard/data JSON files exist
- homepage and dashboard links exist
- expected dashboard tokens are present

### Current implementation note
- `site/dashboard/*.html` are generated Python outputs, not a separate frontend source tree.
- JSON payloads exist as a stable contract for static consumption and future decoupling, but the current HTML is rendered directly in Python.

## Current reusable extension points
- Prefer reading `latest_*` views for new business metrics.
- If new cross-page logic is needed, extract it from `scripts/dashboard/main.py` into reusable helpers instead of copying formulas.
- If new payload sections are needed, add them inside the current root contract before creating a parallel export path.

## Gaps found during the scan
- `scripts/analysis/` is not yet the primary home of business-analysis logic.
- Same-season historical comparison is still missing as a concrete module.
- Profit estimation depends on optional local cost files.
- Inventory valuation is retail-value based, not cost-based.
- No SKU-level movement lines means stock movement explanations remain partial.
