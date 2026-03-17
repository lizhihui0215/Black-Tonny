# SQLite 分析交接说明

## 目的

这份说明用于把当前 SQLite 分析库稳定地交给下一个 agent 使用。

从这一轮开始，后续分析默认只读：

- `/Users/lizhihui/Workspace/Black-Tony/reports/calibration/black_tony_analysis.sqlite`

不要再直接读取：

- `data/imports/inventory_zip_extract/*`
- `reports/capture-cache/*.json`
- Excel 原始包

## 当前批次

- `batch_id`: `sales_calibration_20260317_020150`
- `created_at`: `2026-03-17 02:01:58`
- `store_name`: `咸阳沣西吾悦专卖店`
- `primary_input`: `郭文攀`

## 当前结论

- 这份 SQLite 已经可以作为下一步分析底座使用。
- 关键业务表已经去掉 `合计 / 小计 / 总计 / 空白主键` 这类干扰行。
- 当前批次来源全部来自 `reports/capture-cache/*.json`，没有 Excel 残留。
- 但必须按推荐视图使用，不能直接拿所有底表做汇总。

## 推荐直接使用的视图

- `latest_master_sales_order_lines`
- `latest_daily_sales_summary`
- `latest_monthly_sales_summary`
- `latest_sku_sales_summary`
- `latest_inventory_detail_snapshots`
- `latest_inventory_sales_snapshots`
- `latest_stock_flow_snapshots`
- `latest_vip_analysis_members`
- `latest_member_sales_rank`
- `latest_guide_report_summary`
- `latest_quality_checks`

## 不建议直接使用的表或视图

- `latest_sales_order_lines`
  原因：它同时包含 `master` 和 `validation` 两套来源，直接聚合会重复。
- 所有非 `latest_*` 的底表
  原因：底表保留跨批次历史，更适合审计，不适合默认单批分析。
- `movement_docs`
  原因：只有单据头，没有 SKU 行级字段，不能做 SKU 精确归因。

## 已确认可信的口径

- 核心服饰净销售额：`859,786.57`
- 含道具全货品净销售额：`901,461.00`
- 主销售明细行数：`9745`
- 按日汇总行数：`365`
- 按月汇总行数：`13`
- 按 SKU 汇总行数：`1218`

## 已确认的数据质量

- `latest_master_sales_order_lines.sale_line_key` 重复数：`0`
- `latest_master_sales_order_lines` 空 `order_no`：`0`
- `latest_master_sales_order_lines` 空 `store_name`：`0`
- `latest_master_sales_order_lines` 汇总行：`0`
- `latest_inventory_detail_snapshots` 汇总行：`0`
- `latest_inventory_sales_snapshots` 汇总行：`0`
- `latest_stock_flow_snapshots` 汇总行：`0`
- `latest_retail_detail_snapshots` 汇总行：`0`
- `latest_vip_analysis_members.vip_card_id` 空值：`0`
- `latest_member_sales_rank.vip_card_id` 空值：`0`

## 已通过的关键校验

- `master_vs_flow_orders = pass`
- `master_vs_product_core_amount = pass`
- `master_vs_product_core_qty = pass`
- `master_vs_store_retail_daily = pass`
- `master_vs_store_retail_orders = pass`

## 当前仍需保留的 warning

- `movement_has_sku_detail = warning`
  原因：出入库单据只有单据头，缺少 SKU 行级字段。
- `retail_validation_tail_gap_days = warning`
  原因：主销售比校验表尾段多 `16` 天，这是覆盖范围问题，不是主表脏数据。

## 需要明确保留的业务字段

- `is_prop = 1` 不是脏数据，表示道具。
- 当前道具销售行数：`308`
- 当前道具净销售额：`41,674.43`
- `is_return = 1` 不是脏数据，表示退货行。
- 当前退货行数：`425`

## 建议口径

- 核心服饰销售口径：
  使用 `latest_master_sales_order_lines.net_sales_amount`
- 含道具全货品口径：
  使用 `latest_daily_sales_summary.all_goods_net_sales_amount`
  或 `latest_monthly_sales_summary.all_goods_net_sales_amount`
- 回款口径：
  使用 `latest_daily_sales_summary.flow_sales_related_cash_money`
  或 `flow_sales_related_actual_money`
- 库存主链路：
  使用 `latest_inventory_detail_snapshots`、`latest_stock_flow_snapshots`
- 会员分析：
  使用 `latest_vip_analysis_members`、`latest_member_sales_rank`

## 不要误判为脏数据的情况

- 道具行需要保留，不要直接删除。
- 退货行需要保留，不要直接删除负数。
- `latest_sales_order_lines` 比 `latest_master_sales_order_lines` 多，不代表脏数据，只是含校验来源。
- `movement_docs` 字段少，不代表抓取失败，而是接口本身只给单据头。

## 最小 SQL 入口

```sql
select *
from latest_quality_checks
order by check_name;
```

```sql
select sale_date, net_sales_amount, all_goods_net_sales_amount, flow_sales_related_cash_money
from latest_daily_sales_summary
order by sale_date;
```

```sql
select month, net_sales_amount, all_goods_net_sales_amount
from latest_monthly_sales_summary
order by month;
```

```sql
select sku, color, net_sales_amount, net_sales_qty, order_count
from latest_sku_sales_summary
order by net_sales_amount desc;
```

## 交给 agent 的提示词

```text
你现在只基于 SQLite 做分析，不要再读取 Excel，也不要直接读取 reports/capture-cache 原始 JSON。

数据库路径：
/Users/lizhihui/Workspace/Black-Tony/reports/calibration/black_tony_analysis.sqlite

先遵守这些口径：
1. 销售主明细只用 latest_master_sales_order_lines，不要用 latest_sales_order_lines。
   原因：latest_sales_order_lines 同时包含 master 和 validation 两套来源，会重复。
2. 核心服饰销售口径使用 net_sales_amount。
3. 如果需要看含道具全货品口径，使用 all_goods_net_sales_amount，并明确标注“含道具”。
4. 道具不是脏数据，是保留标签。明细里用 is_prop=1 区分。
5. 退货不是脏数据，是业务标签。明细里用 is_return=1 区分。
6. 出入库单据 movement_docs 没有 SKU 行级字段，只能做背景解释，不能做 SKU 精确归因。
7. 分析前先读取 latest_quality_checks，把 warning 写进结论。

优先使用这些视图：
- latest_master_sales_order_lines
- latest_daily_sales_summary
- latest_monthly_sales_summary
- latest_sku_sales_summary
- latest_inventory_detail_snapshots
- latest_inventory_sales_snapshots
- latest_stock_flow_snapshots
- latest_vip_analysis_members
- latest_member_sales_rank
- latest_guide_report_summary
- latest_quality_checks

已确认的数据质量事实：
- latest_master_sales_order_lines 行数 9745，sale_line_key 重复 0，空 order_no 0，空 store_name 0，合计/小计/总计行 0。
- 核心净销售额汇总 = 859786.57。
- 含道具全货品净销售额汇总 = 901461.00。
- 道具销售行 308 行，道具净额 41674.43。
- 商品销售情况、每日流水单、店铺零售校验与销售主表的关键对账都已通过。
- 已知 warning：
  1. movement_has_sku_detail = warning
  2. retail_validation_tail_gap_days = warning

请先输出：
1. 你准备采用的分析口径
2. 你会读取的视图
3. 你识别到的 warning 对分析的影响
4. 再开始正式分析
```
