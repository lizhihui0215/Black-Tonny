# DASHBOARD_PAYLOAD_MAP

## Contract owner
- Source function:
  - `scripts/dashboard/main.py::build_export_payload`
- Produced files:
  - `reports/dashboard-history/data/dashboard.json`
  - `reports/dashboard-history/data/details.json`
  - `reports/dashboard-history/data/monthly.json`
  - `reports/dashboard-history/data/quarterly.json`
  - `reports/dashboard-history/data/relationship.json`
  - mirrored copies under `site/dashboard/data/`
- Page variants share the same root shape.
- The current Python HTML pages are generated from the same `metrics` object as the JSON payload.

## Root contract
| Key | Type | Current value label | Purpose | Fallback behavior |
| --- | --- | --- | --- | --- |
| `meta` | object | directly observed metadata | identify page type, generation time, store, batch, pipeline labels | always present |
| `summary_cards` | object | mostly directly observed / deterministic derived, with nested estimate+forecast blocks | top-level KPI pack | always present; nested optional blocks may be `null` |
| `today_focus` | object | heuristic recommendation | short action shortlist for today | empty arrays if no actions |
| `execution_board` | object | mixed direct / estimated / forecast action pack | action-first monthly execution page content | arrays degrade to `[]`; role map degrades to empty lists |
| `health_lights` | array | derived actual + heuristic banding | color-coded health cards | empty array if source metrics missing |
| `time_strategy` | object | heuristic plan | day/week/month action guidance by season and phase | strings/lists fall back to generic wording |
| `decision` | object | heuristic conclusion with forecast-aware wording | current operating mode/headline/summary | always present if metrics build succeeds |
| `consulting_analysis` | object | mixed direct / inferred / forecast narrative | longer-form consulting diagnosis and action framing | arrays/objects degrade to empty content |
| `inventory_sales_relationship` | object | mixed direct / estimated / forecast-aware recommendation pack | dedicated inventory-vs-sales page payload | present with empty arrays / generic wording if source tables are sparse |
| `dashboard_tips` | array | explanatory glossary | non-technical meaning of core terms | empty array if not built |
| `insights` | array | mixed direct / inferred / forecast snippets | bite-sized insight cards | empty array if not built |
| `tables` | object of record arrays | mixed: factual tables + action tables | stable tabular payload for downstream pages | each table key returns an array, often `[]` |

## `meta`
### Stable keys
- `page_type`
  - one of: `dashboard`, `details`, `monthly`, `quarterly`, `relationship`
- `generated_at`
- `store_name`
- `analysis_batch_id`
- `data_capture_at`
- `pipeline`
- `sales_source_label`
- `cumulative_sales_source_label`

### Notes
- `pipeline` is display metadata, not execution control.
- `analysis_batch_id` may be absent if SQLite batch metadata is unavailable.

## `summary_cards`
### Stable top-level keys
- `store_name`
- `sales_amount`
- `sales_qty`
- `sales_orders`
- `sales_days`
- `avg_order_value`
- `items_per_order`
- `member_sales_ratio`
- `sales_detail_start`
- `sales_detail_end`
- `inventory_qty`
- `inventory_amount`
- `negative_sku_count`
- `negative_inventory_amount`
- `daily_sales_amount`
- `daily_sales_qty`
- `estimated_inventory_days`
- `props_sales_amount`
- `props_sales_qty`
- `props_sales_orders`
- `props_inventory_qty`
- `props_inventory_amount`
- `receipt_qty`
- `receipt_records`
- `member_count`
- `member_amount_sum`
- `cumulative_sales_qty`
- `cumulative_sales_amount`
- `cumulative_receipt_qty`
- `historical_stock_qty`
- `history_first_arrival`
- `history_first_sale`
- `props_cumulative_sales_qty`
- `props_cumulative_sales_amount`
- `current_season_name`
- `phase_name`
- `next_season_name`
- `sales_source_label`
- `cumulative_sales_source_label`
- `month_to_date_sales_amount`
- `month_to_date_sales_source`
- `analysis_batch_id`
- `data_capture_at`
- `profit_snapshot`
- `yeusoft_highlights`

### Current label boundary
- Directly observed or deterministic derived from observed data:
  - sales, qty, orders, member ratio, inventory totals, cumulative sales snapshot values, capture time
- Estimated:
  - `estimated_inventory_days`
- Forecast:
  - none at the top level
  - forecast lives inside `profit_snapshot`

### Fallback behavior
- Missing optional enrichments become `null`:
  - `profit_snapshot`
  - `yeusoft_highlights`
- Missing batch metadata leaves `analysis_batch_id` empty/null.

## `summary_cards.profit_snapshot`
### Stable keys
- `snapshot_name`
- `snapshot_datetime`
- `sales_amount`
- `purchase_cost`
- `gross_profit`
- `gross_margin_rate`
- `monthly_operating_expense`
- `salary_total`
- `total_expense`
- `operating_expense_source`
- `net_profit`
- `net_margin_rate`
- `average_daily_gross_profit`
- `expense_ratio`
- `salary_ratio`
- `operating_expense_ratio`
- `expense_coverage_ratio`
- `breakeven_sales`
- `breakeven_daily_sales`
- `breakeven_progress_ratio`
- `breakeven_available`
- `average_daily_sales`
- `remaining_days`
- `remaining_sales_to_breakeven`
- `remaining_daily_sales_needed`
- `projected_month_sales`
- `projected_remaining_sales`
- `projected_month_gross_profit`
- `projected_remaining_gross_profit`
- `projected_month_net_profit`
- `projected_monthly_status`
- `forecast_headline`
- `fixed_cost_daily_burden`
- `salary_daily_burden`
- `top_expense_item`
- `top_salary_item`
- `passed_breakeven`
- `status`
- `headline`
- `expense_items`
- `salary_items`
- `notes`
- `sales_source`
- `gross_margin_source`
- `forecast_basis`

### Current label boundary
- Directly observed:
  - only when sales and margin come from the current cost snapshot / current POS month data
- Estimated:
  - profit-to-date fields when margin or expense basis falls back to historical/default assumptions
- Forecast:
  - all `projected_*`
  - `forecast_headline`
  - `projected_monthly_status`

### Caveat
- This block depends on local cost files and fallback margin logic outside SQLite.

## `summary_cards.yeusoft_highlights`
### Nested sections
- `sales_overview`
- `product_sales`
- `member_rank`
- `stock_analysis`
- `movement`
- `daily_flow`
- `category_analysis`
- `vip_analysis`
- `guide_report`
- `store_month_report`
- `retail_detail`
- `capture_at`

### Purpose
- These enrich wording and side diagnostics.
- They do not replace the calibrated SQLite sales truth.

### Current label boundary
- Directly observed:
  - all nested POS/capture summaries
- Estimated:
  - downstream interpretation of these summaries
- Forecast:
  - none inside the raw highlight objects themselves

## `today_focus`
### Shape
- `conclusions: string[]`
- `tasks: string[]`

### Current label boundary
- Estimated / heuristic action shortlist.

## `execution_board`
### Shape
- `today_must_do: object[]`
- `weekly_strategy: object[]`
- `risk_alerts: object[]`
- `role_actions: object`
- `execution_buttons: object[]`

### `today_must_do` / `weekly_strategy` item shape
- `owner`
- `when`
- `action`
- `object`
- `goal`
- `sentence`
- `evidence`
- `value_label`
- `data_source`
- `confidence`
- `tone`

### `risk_alerts` item shape
- `title`
- `level`
- `evidence`
- `action`
- `value_label`
- `data_source`
- `confidence`

### `role_actions`
- `老板: string[]`
- `店长: string[]`
- `店员: string[]`

### `execution_buttons` item shape
- `label`
- `href`
- `status`
- `note`

### Current label boundary
- Directly observed:
  - negative inventory, member dormancy, joint-rate evidence fields
- Estimated:
  - stockout / clearance / replenishment action cards driven by rules
- Forecast:
  - risk cards or must-do actions that cite `profit_snapshot.projected_*`

### Fallback behavior
- Non-monthly pages currently return empty `today_must_do`, `weekly_strategy`, and `risk_alerts`.
- The button list may include placeholder rows where UI exists before a dedicated export is wired.

## `health_lights`
### Item shape
- `level`
- `title`
- `value`
- `note`

### Current label boundary
- Derived actual metrics mapped into heuristic traffic-light bands.

## `time_strategy`
### Stable keys
- `beijing_time`
- `season`
- `phase`
- `next_season`
- `headline`
- `inventory_days`
- `top_replenish_category`
- `top_replenish_season`
- `top_clearance_category`
- `daily_actions`
- `weekly_actions`
- `monthly_actions`

### Current label boundary
- Estimated / heuristic planning guidance.
- Not raw fact data.

## `decision`
### Stable keys
- `mode`
- `stage`
- `headline`
- `summary`
- `sales_trend`
- `season`
- `phase`
- `top_replenish`
- `top_clearance`
- `top_seasonal`

### `sales_trend` shape
- `label`
- `direction`
- `recent_avg`
- `previous_avg`
- `ratio`
- `detail`

### Current label boundary
- Mixed:
  - `sales_trend` is deterministic derived from observed sales
  - `headline` and `summary` are heuristic, sometimes forecast-aware

## `consulting_analysis`
### Stable keys
- `period_label`
- `focus_title`
- `diagnosis_summary`
- `focus_issues`
- `sales_analysis`
- `inventory_analysis`
- `category_analysis`
- `sku_analysis`
- `member_analysis`
- `rhythm_analysis`
- `replenish_advice`
- `clearance_advice`
- `category_advice`
- `weekly_actions`
- `risk_alerts`
- `if_ignore`
- `role_guidance`
- `priority_matrix`
- `basis_notes`

### Important nested contract
- `priority_matrix`
  - object with buckets:
    - `重要且紧急`
    - `重要不紧急`
    - `可观察`
    - `暂不处理`
- `basis_notes`
  - object with buckets:
    - `direct`
    - `inferred`
    - `need_more`

### Current label boundary
- Mixed by design.
- Direct evidence is called out in `basis_notes.direct`.
- Inference and missing-data reminders are called out in `basis_notes.inferred` and `basis_notes.need_more`.
- Many narrative strings also embed markers such as `【直接数据】`.

## `dashboard_tips`
### Item shape
- `term`
- `meaning`
- `watch`

### Current label boundary
- Explanatory only.

## `inventory_sales_relationship`
### Stable keys
- `mode`
- `tone`
- `headline`
- `summary`
- `metric_cards`
- `findings`
- `recommendations`
- `category_matrix`
- `data_basis`

### Important nested contract
- `metric_cards`
  - array of objects:
    - `label`
    - `value`
    - `detail`
    - `value_type`
- `findings`
  - array of objects:
    - `title`
    - `conclusion`
    - `evidence`
    - `action`
- `recommendations`
  - object with buckets:
    - `today`
    - `next_7_days`
    - `next_30_days`
- `category_matrix`
  - array of category rows with:
    - `大类`
    - `零售额`
    - `库存额`
    - `库存金额/销售金额`
    - `库存量/销售量`
    - `状态`
    - `关系判断`
    - `建议动作`
- `data_basis`
  - object with buckets:
    - `direct`
    - `estimated`
    - `forecast`
    - `caveats`

### Current label boundary
- Mixed by design.
- `metric_cards.value_type` explicitly labels whether a figure is:
  - `直接观察`
  - `估算`
  - `预测`
- `category_matrix` is mostly observed facts plus heuristic interpretation.
- `recommendations` are action guidance, not raw fact tables.

## `insights`
### Item shape
- `summary`
- optional `detail`
- optional `label`

### Current label boundary
- Mixed:
  - direct metric statements
  - inferred context
  - forecast snippets when profit projection is present

## `tables`
### Factual tables
| Key | Record grain | Main fields | Current label boundary |
| --- | --- | --- | --- |
| `sales_daily` | day | `日期`, `销售额`, `销量`, `订单数` | directly observed / deterministic derived |
| `sales_by_category` | product major category | `商品大类`, `销售额`, `销量`, `订单数` | directly observed / deterministic derived |
| `sales_by_category_ex_props` | product major category excluding props | same as above | directly observed / deterministic derived |
| `inventory_by_category` | inventory major category | `大类`, `库存量`, `库存额`, `在途库存` | directly observed / deterministic derived |
| `stock_sales_ratio` | inventory major category | `大类`, `零售额`, `库存额`, `零售量`, `库存量`, ratio fields | estimated health proxy built from observed snapshots |
| `guide_perf` | guide | `导购员`, `实收金额`, `票数`, `单效`, `连带`, `会员销额` | directly observed / deterministic derived |
| `top_members` | member | `VIP姓名`, `服务导购`, `购买金额`, `购买总数`, `消费次数/年`, `平均单笔消费额`, `储值余额` | directly observed snapshot |
| `primary_reference` | input-user/store reference | `输入人`, `店铺名称`, `销售额`, `销量`, `订单数` | directly observed reference |
| `other_references` | input-user/store reference | same as above | directly observed reference |
| `negative_inventory` | SKU + size | `款号`, `品名`, `颜色`, `尺码`, `库存`, `库存额`, `大类`, `小类` | directly observed anomaly list |
| `low_stock_bestsellers` | SKU + color | `款号`, `颜色`, `销售数`, `销售金额`, `库存`, `周期售罄`, `中类`, `季节` | directly observed + heuristic filter |
| `slow_moving` | SKU + color | `商品款号`, `商品名称`, `大类`, `中类`, `小类`, `实际库存`, `近期零售`, `动销率`, `零售价` | directly observed + heuristic filter |
| `category_risks` | category | `大类`, `零售额`, `库存额`, ratio fields, `状态` | estimated risk band from observed snapshots |

### Action tables
| Key | Record grain | Main fields | Current label boundary |
| --- | --- | --- | --- |
| `replenish` | SKU + color | sales, stock, weeks-of-stock, action, replenish rule, budget hints | estimated / heuristic recommendation |
| `replenish_categories` | middle category + season strategy | SKU count, sales, stock, suggested replenish qty, rule summary | estimated / heuristic recommendation |
| `seasonal_actions` | SKU + color | season strategy, stock, sales, action | estimated / heuristic recommendation |
| `seasonal_categories` | middle category + season strategy + action | SKU count, stock, sales | estimated / heuristic recommendation |
| `clearance` | SKU + color | stock, recent retail, sell-through proxy, action | estimated / heuristic recommendation |
| `clearance_categories` | category + action | SKU count, actual stock, recent retail | estimated / heuristic recommendation |

### Fallback behavior
- Every table key should serialize to an array.
- Empty upstream DataFrames become `[]`.
- Do not change table names casually; HTML builders and downstream static copies assume these keys exist.

## Compatibility notes
- Current JSON root keys are the real contract; the older placeholder section names in previous docs were not implemented.
- Monthly and quarterly payloads keep the same root shape; they mainly differ in:
  - `meta.page_type`
  - `consulting_analysis.period_label`
- The relationship page uses the same root payload plus the additive `inventory_sales_relationship` section.
- If you add new sections, prefer additive changes under existing roots.
