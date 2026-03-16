# 静态发布报告

- 生成时间：2026-03-17T02:02:01.502688+08:00
- 发布模式：复用本地抓取缓存
- 同步窗口：2025-03-01 -> 2026-03-17
- SQLite：/Users/lizhihui/Workspace/Black-Tony/reports/calibration/black_tony_analysis.sqlite
- 静态站点目录：/Users/lizhihui/Workspace/Black-Tony/site/dashboard
- 历史输出目录：/Users/lizhihui/Workspace/Black-Tony/reports/dashboard-history
- 结果：ok

## 步骤结果

- 抓取 JSON：skipped，已跳过抓取，沿用当前 reports/capture-cache。
- 截图字段核对：warning，已经 18 张，高度怀疑 5 张。
- 数据同步 -> SQLite：ok，批次 sales_calibration_20260317_020150，销售 9745 行，库存 983 行。
- SQLite -> 本地分析 -> 导出 Pages：ok，已生成 HTML / Markdown / CSV / JSON 到 reports/ 和 site/。
- 文档中心构建：ok，已刷新 site/manuals。
- Pages 自检：ok，site/ 静态发布目录检查通过。

## SQLite 同步摘要

- batch_id：sales_calibration_20260317_020150
- db_path：/Users/lizhihui/Workspace/Black-Tony/reports/calibration/black_tony_analysis.sqlite
- store_name：咸阳沣西吾悦专卖店
- master_row_count：9745
- validation_row_count：9326
- daily_flow_row_count：3988
- product_snapshot_row_count：1340
- movement_row_count：307
- inventory_detail_row_count：983
- inventory_sales_row_count：1340
- stock_flow_row_count：1546
- size_breakdown_row_count：11646
- vip_analysis_row_count：1182
- member_rank_row_count：1190
- guide_report_row_count：6
- retail_detail_row_count：1340
- daily_summary_row_count：365
- monthly_summary_row_count：13
- sku_summary_row_count：1218
- quality_check_count：10
- problem_order_count：0
- problem_sku_count：0

## 字段核对摘要

- audit_json：/Users/lizhihui/Workspace/Black-Tony/reports/calibration/api_field_audit.json
- audit_markdown：/Users/lizhihui/Workspace/Black-Tony/reports/calibration/api_field_audit.md
- report_samples_md：/Users/lizhihui/Workspace/Black-Tony/scripts/yeusoft/report_api_samples.md
- report_count：23
- confirmed_count：18
- high_suspicion_count：5

## 发布产物

- Pages 首页：[index.html](/Users/lizhihui/Workspace/Black-Tony/site/dashboard/index.html)
- Pages JSON 清单：[manifest.json](/Users/lizhihui/Workspace/Black-Tony/site/dashboard/data/manifest.json)
- Pages 数据包目录：[data](/Users/lizhihui/Workspace/Black-Tony/site/dashboard/data)
- 字段核对 Markdown：[api_field_audit.md](/Users/lizhihui/Workspace/Black-Tony/reports/calibration/api_field_audit.md)
- 字段核对 JSON：[api_field_audit.json](/Users/lizhihui/Workspace/Black-Tony/reports/calibration/api_field_audit.json)
- 自检脚本：[check_pages_ready.py](/Users/lizhihui/Workspace/Black-Tony/scripts/tools/check_pages_ready.py)
