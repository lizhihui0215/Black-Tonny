# SQLITE_ANALYSIS_MAP

## Preferred read order
- First anchor on `latest_import_batch`.
- Then prefer `latest_*` views for current-state analysis.
- Use base tables only when the dashboard still needs batch-scoped access:
  - `product_sales_snapshot`
  - `movement_docs`
  - reconciliation tables

## Batch and lineage objects
| Object | Purpose | Grain | Time field | Key measures / dimensions | Current consumers | Caveats |
| --- | --- | --- | --- | --- | --- | --- |
| `latest_import_batch` | Anchor the current analysis batch | 1 row per latest batch | `created_at` | `batch_id`, `store_name`, `capture_dir` | all `latest_*` views, dashboard freshness | latest-only, not history |
| `import_batches` | Persist batch history and notes | 1 row per import run | `created_at` | store, capture dir, notes | history lookup, troubleshooting | not directly used by dashboard pages |
| `source_files` | Persist per-source lineage and audit metadata | 1 row per batch + source | `captured_at` | path, hash, requested range, row counts | audit, provenance, trust checks | metadata JSON requires decoding |

## Sales truth objects
| Object | Purpose | Grain | Time field | Key measures / dimensions | Current consumers | Caveats |
| --- | --- | --- | --- | --- | --- | --- |
| `latest_master_sales_order_lines` | Canonical calibrated store sales truth | order line | `sale_date`, `sale_day`, `sale_month` | qty, sales amount, tag amount, discount, member, guide, category, return flags | sales window, summary cards, category sales, guide perf, member ratio | excludes validation rows by design |
| `latest_sales_order_lines` | Latest master + validation sales lines | order line | `sale_date`, `sale_day`, `sale_month` | same as above + `source_role` | validation references | mixed source roles, do not treat all rows as truth |
| `latest_daily_sales_summary` | Trusted daily sales summary | 1 row per day | `sale_date` | gross/net sales, prop sales, orders, net qty, flow actual/cash amounts | current trend, recent sales window, MTD lookup | cash fields include order-level payment logic and can include props |
| `latest_monthly_sales_summary` | Trusted monthly sales summary | 1 row per month | `month` | monthly net sales, cash fields, order counts | MTD summary, historical monthly chart | monthly sales are derived from latest batch only |
| `latest_sku_sales_summary` | Trusted cumulative SKU sales summary | SKU + color + category tuple | none explicit beyond batch | gross/net sales, qty, order count | best sellers, long-tail SKU reads | no explicit time window, latest batch only |
| `product_sales_snapshot` | Cumulative SKU snapshot from `商品销售情况.json` | SKU + color | `first_arrival_date`, `first_sale_date` | cumulative sales qty/amount, returns, current stock, arrival qty | replenish candidates, cumulative sales source label, total sell-through | queried by `batch_id`, not via `latest_*`; cumulative report semantics differ from line-level returns |

## Inventory, retail, and stock objects
| Object | Purpose | Grain | Time field | Key measures / dimensions | Current consumers | Caveats |
| --- | --- | --- | --- | --- | --- | --- |
| `latest_inventory_detail_snapshots` | Current inventory by SKU + color with retail-value totals | SKU + color snapshot | no business date, latest batch only | total stock qty/amount, retail qty/amount, category, year/season/period, retail price | inventory detail, inventory amount, negative inventory, size allocation base | inventory amount is retail-value style, not cost |
| `latest_inventory_sales_snapshots` | Inventory-sales ratio snapshot | SKU + color snapshot | no business date, latest batch only | stock/sales ratio, retail qty/amount | stock-sales ratio, category risk | still snapshot-based, not full time series |
| `latest_stock_flow_snapshots` | Stock-flow and stock-on-hand summary | SKU + color snapshot | no business date, latest batch only | opening, arrival, transfers, return, sale, ledger stock, actual stock, wait stock, sell-through | slow movers, clearance, inventory detail wait-stock allocation | period meaning comes from upstream report, not a persisted date column |
| `latest_size_metric_breakdowns` | Size breakdown rows split out from JSON blobs | snapshot + size label + metric scope | no business date, latest batch only | stock qty / retail qty / retail detail qty by size | inventory detail size-level rows, retail-detail size signals | must filter by `source_name` and `metric_scope` |
| `latest_retail_detail_snapshots` | Retail-detail sales snapshot by SKU + color | SKU + color snapshot | latest batch only | total qty, retail amount, sale amount, discount rate, category, year/season/period | discount pressure, size pressure, product enrichment | not line-level raw sales; already aggregated |
| `movement_docs` | Inbound/outbound document headers | movement document | `come_date`, `receive_date` | doc type/status, from/to store, qty, amount | movement table, net inbound/outbound explanations | no SKU-level lines, batch table not `latest_*` view |

## Member and staff objects
| Object | Purpose | Grain | Time field | Key measures / dimensions | Current consumers | Caveats |
| --- | --- | --- | --- | --- | --- | --- |
| `latest_vip_analysis_members` | Member lifecycle snapshot | member card | `birth_date`, `input_date`, `last_sale_date` | total sale amount, sale count, avg sale, stored value, points | top members, member count, member value, dormant/active signals | snapshot-based, not transaction history |
| `latest_member_sales_rank` | Member ranking snapshot | rank row | no explicit business date | rank, sale amount, sale qty, sale share | Yeusoft highlight enrichment | not currently the main top-member table in dashboard |
| `latest_guide_report_summary` | Guide/staff performance snapshot | guide | latest batch only | sale qty, sale amount, VIP amount, order count, average ticket, attachment rate | guide performance table, guide highlights | snapshot report semantics come from upstream POS |

## Quality and reconciliation objects
| Object | Purpose | Grain | Time field | Key measures / dimensions | Current consumers | Caveats |
| --- | --- | --- | --- | --- | --- | --- |
| `latest_quality_checks` | Persist key trust checks for the latest batch | check row | latest batch only | check name, scope, status, observed/expected values | internal confidence checks, future confidence banners | dashboard currently loads base `quality_checks` by batch |
| `quality_checks` | Same checks across all batches | check row | batch created time via join | pass/warning/fail plus detail JSON | current dashboard loads latest batch from this table | base table read, not view |
| `order_reconciliation_results` | Order-level diff results | order + comparison label | no explicit date field | left/right amount, qty, diff, problem flag | audit only | not yet surfaced in exported payload |
| `daily_reconciliation_results` | Day-level diff results | day + comparison label | `sale_day` | left/right amount, qty, orders, diff, problem flag | audit only | not yet surfaced in exported payload |
| `sku_reconciliation_results` | SKU-level diff results | SKU + color + comparison label | latest batch only | amount diff, qty diff, return qty, problem flag | audit only | not yet surfaced in exported payload |

## Current business metric mapping
| Business need | Preferred source | Current value label | How it is used now | Caveat |
| --- | --- | --- | --- | --- |
| Overall business overview | `latest_master_sales_order_lines`, `latest_daily_sales_summary`, `latest_monthly_sales_summary` | directly observed / deterministic derived | summary cards, trend, insights | recent sales window is intentionally short and rolling |
| Inventory health | `latest_inventory_detail_snapshots`, `latest_stock_flow_snapshots`, `quality_checks` | directly observed + derived | inventory totals, negative SKU count, wait stock | inventory accuracy still depends on upstream snapshot quality |
| Sales performance | `latest_master_sales_order_lines`, `latest_daily_sales_summary`, `latest_monthly_sales_summary` | directly observed / deterministic derived | sales amount, qty, orders, category sales | props are explicitly separated |
| Best sellers | `product_sales_snapshot`, `latest_retail_detail_snapshots` | directly observed + heuristic ranking | low-stock bestsellers, replenish base | cumulative and current-period measures are mixed intentionally |
| Slow movers | `latest_stock_flow_snapshots` | directly observed + heuristic filter | slow-moving and clearance tables | no SKU-level movement root cause |
| Stockout risk | `product_sales_snapshot` + current stock | estimated | replenish candidates, stockout pressure | based on rules, not probabilistic forecast |
| Overstock risk | `latest_inventory_sales_snapshots`, `latest_stock_flow_snapshots` | estimated | category risk, clearance lists | thresholds are heuristic |
| Sell-through | `latest_stock_flow_snapshots`, `product_sales_snapshot` | directly observed / deterministic derived | `动销率`, `周期售罄`, `总售罄` | snapshot semantics differ between reports |
| Days of supply | latest sales window + inventory qty | estimated | `estimated_inventory_days` | recent 8-day rolling window can overreact |
| Discount pressure | `latest_retail_detail_snapshots` | directly observed + heuristic interpretation | markdown pressure, discount categories | no gross-margin cost join in SQLite |
| Current inventory value | `latest_inventory_detail_snapshots.total_stock_amount` | directly observed proxy | inventory amount cards/tables | retail-value proxy, not purchase-cost valuation |
| Realized sales MTD | `latest_monthly_sales_summary` | directly observed | MTD sales amount lookup | latest batch only |
| Profit estimate to date | SQLite sales + local cost snapshots | estimated | `summary_cards.profit_snapshot` | requires files outside SQLite |
| Month-end forecast | profit snapshot projected fields | forecast | decision engine, forecast headline | depends on margin and remaining-days assumptions |
| Action-first monthly execution board | inventory snapshots + member snapshots + monthly sales + profit snapshot | mixed direct / estimated / forecast | `execution_board` on the monthly payload and monthly HTML | cards are rule-driven summaries, so evidence is direct but action priority is heuristic |
| Same-season historical reference | none first-class yet | insufficient data | not materially implemented | latest-batch model is not enough on its own |
| Confidence / caveat labels | `quality_checks`, source lineage, consulting basis notes | directly observed + narrative inference | insights and future confidence slots | not every payload section exposes an explicit confidence enum yet |

## Practical guidance
- Use `latest_*` views first when adding new dashboard or report metrics.
- If you need batch provenance or source metadata, join back to `import_batches` and `source_files`.
- If you need long-history analysis, query base tables across multiple `batch_id` values on purpose; do not assume `latest_*` is enough.
- Keep actual, estimated, and forecast outputs separated in downstream payload design.
- For action cards, keep the evidence line tied to a concrete SQLite or cost source even when the action itself is heuristic.
