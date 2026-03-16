# 主店销售数据源盘点

- 审计主店：`咸阳沣西吾悦专卖店`
- Excel 推断主店：`咸阳沣西吾悦专卖店`
- 默认输入人：`郭文攀`

## 来源清单

| 来源 | 角色 | 粒度 | 可信度 | 日期范围 | 行数 | 关键字段 | 路径 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| capture 销售清单 | 主表 | 订单行 | 高 | 2025-03-17 ~ 2026-03-16 | 9745 | 店铺名称/输入人/销售日期/零售单号/明细流水/款号/颜色/尺码/数量/金额/单据类型 | /Users/lizhihui/Workspace/Black-Tony/reports/capture-cache/销售清单.json | 单店主店全期明细，已验证无汇总行混入。 |
| capture 店铺零售清单 | 交叉校验 | 订单行 | 高（仅重叠区间） | 2025-03-17 ~ 2026-02-28 | 9326 | 店铺名称/输入人/销售日期/零售单号/明细流水/款号/颜色/尺码/数量/金额 | /Users/lizhihui/Workspace/Black-Tony/reports/capture-cache/店铺零售清单.json | 19 店混合表，过滤主店后只做校验，不并表。 |
| capture 商品销售情况 | 累计校验 | SKU+颜色 | 高（累计金额/数量） | 2025-03-01 ~ 2026-03-16 | 1340 | Specification/Color/SumSaleAmount/SumSaleMoney/SumReturn/StockNum/MType | /Users/lizhihui/Workspace/Black-Tony/reports/capture-cache/商品销售情况.json | 需用 Specification 对齐销售清单款号。 |
| capture 每日流水单 | 回款校验 | 订单 | 高（回款） | 2025-03-17 ~ 2026-03-16 | 3988 | MakeDate/DocTypeName/DocNo/ActualMoney/CashMoney/Amount/TagMoney | /Users/lizhihui/Workspace/Black-Tony/reports/capture-cache/每日流水单.json | 含 销售/换货/退货/储值，不能直接当销售主表。 |
| capture 出入库单据 | 库存动作辅助 | 单据 | 中 | 2025-03-18 ~ 2026-03-12 | 307 | DocType/DocStat/Transtat/WhID/InWhID/TN/TRP/ComeDate/ReceDate | /Users/lizhihui/Workspace/Black-Tony/reports/capture-cache/出入库单据.json | 只有单据头，无 SKU 行，不参与销售汇总。 |
| Excel 销售清单 | 短窗复核 | 订单行 | 高（2026-03-06 ~ 2026-03-13） | 2026-03-06 ~ 2026-03-13 | 212 | 店铺名称/输入人/销售日期/零售单号/明细流水/款号/颜色/尺码/数量/金额/单据类型 | /Users/lizhihui/Workspace/Black-Tony/data/imports/inventory_zip_extract/销售清单 - 【2026-03-13】.xlsx | 含合计行，已清理后再参与比对。 |
| Excel 导购员报表 | 短窗辅助 | 导购聚合 | 中高 | 文件日样本 | 3 | 导购员/销量/实收金额/现金/储值/票数 | /Users/lizhihui/Workspace/Black-Tony/data/imports/inventory_zip_extract/导购员报表 - 【2026-03-13】.xls | 适合做短窗票数/金额辅助，不适合全年主口径。 |
| Excel 商品销售情况 | 短窗辅助 | SKU+颜色 | 中高 | 2025-03-17 ~ 2026-03-13 | 1336 | 款号/颜色/累销/累销额/总到货/库存/总退货/中类 | /Users/lizhihui/Workspace/Black-Tony/data/imports/inventory_zip_extract/商品销售情况【2026-03-13】.xls | 累计口径参考，不做逐日趋势真值。 |
| Excel 出入库单据 | 库存动作辅助 | 单据 | 中 | 2025-03-18 ~ 2026-03-12 | 307 | 单据类型/单据状态/单据号/发货仓库/接收店铺/发货时间/接收时间/数量/吊牌金额 | /Users/lizhihui/Workspace/Black-Tony/data/imports/inventory_zip_extract/出入库单据【2026-03-13】.xlsx | 当前导出无 SKU 级字段，不能追到订单行。 |

## 关键字段模型

- 统一字段：`store_name, input_user, sale_date, order_no, line_no, sku, color, size, qty, sales_amount, tag_amount, unit_price, discount_rate, doc_type, member_card, guide_name, source_name`
- 主销售主键：`order_no + line_no`
- SKU 主键：`sku + color + size`
- 每日流水单主键：`DocNo + DocTypeName`

## 审计备注

- Excel 销售类样本存在合计行：销售清单移除 `1` 行，导购员报表移除 `1` 行，商品销售情况移除 `1` 行，出入库单据移除 `1` 行。
- capture 销售清单请求区间：`20250301` 到 `20260316`。
- capture 店铺零售清单过滤后只保留主店 / 输入人 `郭文攀` 相关记录。
- 商品销售情况中道具行 `122` 条，需要从核心服饰口径中剔除。
- 每日流水单 doc_type 分布：销售/换货/退货/储值 = 3,679/219/69/21。
- 出入库单据 doc_type 分布：{'店铺到货单': 151, '门店报损单': 82, '店铺退货单': 74}。
