# Yeusoft 截图 vs API 字段核对

- 核对时间：2026-03-17 19:55:22
- 已经：18
- 高度怀疑：5

## 总表

| 报表 | 状态 | JSON / 截图结论 | SQLite 落点 |
| --- | --- | --- | --- |
| 零售明细统计 | 已经 | 表格列头、动态尺码列和合计列都能和当前 JSON 的 `retdata[0].Title/Data` 对上，两张截图只是横向拆屏。 | retail_detail_snapshots、size_metric_breakdowns |
| 导购员报表 | 已经 | 截图列头与 `SelPersonSale` 返回字段能逐一对应，付款方式和会员字段也能对上。 | guide_report_summary |
| 店铺零售清单 | 已经 | 四张截图只是同一张明细表的横向切片，`ColumnsList` 与页面列头一致。 | sales_order_lines |
| 销售清单 | 已经 | 三张截图与 `ColumnsList` 一致，是当前主店销售主表。 | sales_order_lines |
| 库存明细统计 | 已经 | 截图和 JSON 的两段动态尺码头、现有库存/零售汇总列都能对齐。 | inventory_detail_snapshots、size_metric_breakdowns |
| 库存零售统计 | 已经 | 三张截图覆盖了同一张表的所有列，`StoU` 和零售合计列能和 JSON 对上。 | inventory_sales_snapshots、size_metric_breakdowns |
| 库存总和分析-按年份季节 | 已经 | 当前 capture-cache 里的 `库存综合分析.json` 请求参数是 `rtype=1`，能和这张“按年份季节”截图对上。 | 当前未单独入 SQLite，仅在字段审计和页面解释时使用。 |
| 库存总和分析-按中分类 | 高度怀疑 | 当前 capture-cache 里只有 `rtype=1` 的 JSON，没有抓到 `rtype=2` 响应，无法和这张“按中分类”截图做 1:1 对照。 | 当前未入 SQLite。 |
| 库存总和分析-按波段 | 高度怀疑 | 当前 capture-cache 里只有 `rtype=1` 的 JSON，没有抓到 `rtype=3` 响应，无法和这张“按波段”截图做 1:1 对照。 | 当前未入 SQLite。 |
| 库存多维分析 | 已经 | 五张截图共同构成一张横向超宽表，`A01~A013` 的尺码列、`AStock` 和 `AMoney` 都能和 JSON 对上。 | 当前未单独入 SQLite。 |
| 进销存统计 | 已经 | 三张截图与 `SelInSalesReport` 返回字段完全对应，数量列和分类维度都能对上。 | stock_flow_snapshots |
| 出入库单据 | 已经 | 页面列头、单据状态和首行值都能和 `SelOutInStockReport` 当前响应对上。 | movement_docs |
| 日进销存 | 高度怀疑 | 截图在，但当前 capture-cache 只有 opened-only，没有请求体和响应体，没法和 JSON 做精确对照。 | 当前无响应，也未入 SQLite。 |
| 会员总和分析 | 已经 | 截图和 `SelVipAnalysisReport` 的会员分析字段能对上，积分、储值、消费频次等字段明确。 | vip_analysis_members |
| 会员消费排行 | 已经 | 两张截图与 `SelVipSaleRank` 返回字段一致，排名、单数、款数、销量、销额和占比都能对上。 | member_sales_rank |
| 储值按店汇总 | 已经 | 截图列头与 `ColumnsList` 一致，门店级储值金额汇总没有歧义。 | 当前未入 SQLite。 |
| 储值卡汇总 | 已经 | 截图和 `ColumnsList` 一致，卡级余额/充值/消费字段都能对应。 | 当前未入 SQLite。 |
| 储值卡明细 | 已经 | 两张截图只是同一张明细表的横向拆屏，发生时间、单号、期初/期末余额与充值字段都能对上。 | 当前未入 SQLite。 |
| 商品销售情况 | 已经 | 两张截图与 `SelSaleReportData` 的字段一致，销量、销额、累销、库存和周度序列字段都在当前响应内。 | product_sales_snapshot |
| 商品品类分析 | 高度怀疑 | 截图页面同时出现了“进货/销售/库存”三段，但当前抓到的 `type=3` JSON 只明显对得上其中的库存区块，不能把三段都当成同一份响应。 | 当前未入 SQLite。 |
| 门店销售月报 | 已经 | 截图表头和 `DeptMonthSalesReport` 的 `PageData.Items` 字段一致；金额脱敏为 `****` 也是后端返回结果，不是对照异常。 | 当前未入 SQLite，仅在 `scripts.dashboard.yeusoft` 中做页面解析。 |
| 每日流水单 | 已经 | 两张截图与 `SelectRetailDocPaymentSlip` 的 `Data.Columns/List` 完整一致，支付方式列也能对上。 | daily_flow_docs |
| 会员中心 | 高度怀疑 | 表格字段本身能和 `SelVipInfoList` 对齐，但截图顶部四张统计卡片不在当前响应里，所以整屏还不能算 100% 全量确认。 | 当前未入 SQLite。 |

## 逐表说明

### 零售明细统计

- 状态：已经
- 结论：表格列头、动态尺码列和合计列都能和当前 JSON 的 `retdata[0].Title/Data` 对上，两张截图只是横向拆屏。
- 接口：`https://erpapistaging.yeusoft.net/eposapi/YisEposReport/SelDeptSaleList`
- 请求参数：`{"bdate": "20250301", "depts": "", "edate": "20260317", "page": 0, "pagesize": 0, "spenum": "", "warecause": ""}`
- capture：`/Users/lizhihui/Workspace/Black-Tony/reports/capture-cache/零售明细统计.json`
- 截图：零售明细统计-1.png, 零售明细统计-2.png
- 抓取质量：`full-range-data`
- 响应结构：`erp-retdata-list`
- JSON 行数：`1341`
- 字段列表：DeptName, WareName, Spec, ColorName, RetailPrice, col01, col02, col03, col04, col05, col06, col07, col08, col09, col010, col011, col012, col013, col014, col015, col016, col017, col018, col019, col020, col021, col022, col023, col024, col025, col026, col027, col028, col029, col030, TotalMoney, TotalNum, TotalRetailMoney, Discount, Trade, Type, Type1, Type2, Years, Season, Pd, Sex, Img
- SQLite：retail_detail_snapshots、size_metric_breakdowns
- 动态列说明：
  - `Title` 第 1 行：col01=90/均码/均码/均码，col02=100/XXS/8-10/75A，col03=110/XS/10-12/75B，col04=120/S/12-14/80A，col05=130/M/14-16/80B，col06=140/L/16-18/85A，col07=150/XL/18-20/85B，col08=160/XXL/20-22/75C，col09=170/XXXL/22-24/80C，col010=180/ / /85C，col011=66，col012=73 等 13 列
- 备注：
  - `TotalNum` 对应零售小计，`TotalRetailMoney` 对应零售金额，`TotalMoney` 对应销售金额，`Discount` 对应折扣。
  - 尺码字段不能把 `col01~col013` 固化，必须按 `Title` 解码成 `90/均码` 这类真实尺码头。

### 导购员报表

- 状态：已经
- 结论：截图列头与 `SelPersonSale` 返回字段能逐一对应，付款方式和会员字段也能对上。
- 接口：`https://erpapistaging.yeusoft.net/eposapi/YisEposPerson/SelPersonSale`
- 请求参数：`{"bdate": "20250301", "edate": "20260317", "name": "", "page": 0, "pagesize": 0}`
- capture：`/Users/lizhihui/Workspace/Black-Tony/reports/capture-cache/导购员报表.json`
- 截图：导购员报表.png
- 抓取质量：`full-range-data`
- 响应结构：`erp-retdata-list`
- JSON 行数：`6`
- 字段列表：Num, Name, Amount, TotalRetailMoeny, DisCount, TotalMoney, Cash, CreditCard, OrderMoney, PosMoney, RetuMoney, ActivityMoeny, StockMoney, WxPayMoney, ZfbPayMoney, OddMoney, WpZeroMoney, Item1, Item2, Item3, Item4, Item5, Item6, Item7, Item8, Item9, VipAmount, VipMoney, Saleps, StockRechargeMoney, DJ, FJ, JEZB, SLZB, ssMoneyRebate
- SQLite：guide_report_summary
- 备注：
  - `Amount=销量`，`TotalRetailMoeny=吊牌金额`，`TotalMoney=销售金额`，`Saleps=票数`，`DJ=单效`，`FJ=连带`。
  - `PosMoney=储值`，`StockRechargeMoney=本期储值金额`，`ssMoneyRebate=返利金额`。

### 店铺零售清单

- 状态：已经
- 结论：四张截图只是同一张明细表的横向切片，`ColumnsList` 与页面列头一致。
- 接口：`https://erpapistaging.yeusoft.net/FxErpApi/FXDIYReport/GetDIYReportData`
- 请求参数：`{"gridid": "E004001007_main", "menuid": "E004001007", "parameter": {"BeginDate": "2025-03-01", "Depart": "  ", "EndDate": "2026-03-17", "Operater": "", "Tiem": "", "WareClause": ""}}`
- capture：`/Users/lizhihui/Workspace/Black-Tony/reports/capture-cache/店铺零售清单.json`
- 截图：店铺零售清单-1.png, 店铺零售清单-2.png, 店铺零售清单-3.png, 店铺零售清单-4.png
- 抓取质量：`full-range-data`
- 响应结构：`erp-retdata-dict`
- JSON 行数：`83877`
- 字段列表：零售单号, 明细流水, 单据类型, 店铺名称, 款号, 品名, 吊牌价, 折扣, 单价, 颜色, 尺码, 数量, 金额, 吊牌金额, 输入人, 输入时间, 销售日期, 班组, 导购员, 会员卡号, 参与活动, 商城扣点, 成本价, 所属大区, 分管业务员, 品牌, 商品大类, 商品中类, 商品小类, 波段, 年份, 季节, 性别, 主题, 系列, 款式定位, 价格段, 设计师, 单据备注, 明细备注, 客户类型, 仓库分类, 业务主管, 上级店仓名, 地理区域, 省份, 城市, 区镇, 城市等级, 店铺面积, 店铺人数, 图片
- SQLite：sales_order_lines
- 动态列说明：
  - `ColumnsList`：零售单号，明细流水，单据类型，店铺名称，款号，品名，吊牌价，折扣，单价，颜色，尺码，数量，金额，吊牌金额，输入人，输入时间，销售日期，班组，导购员，会员卡号，参与活动，商城扣点，成本价，所属大区 等 52 列
- 备注：
  - 当前表是全店铺范围的零售清单，适合拿来做主表校验和补充维度，不要和单店 `销售清单` 混用。

### 销售清单

- 状态：已经
- 结论：三张截图与 `ColumnsList` 一致，是当前主店销售主表。
- 接口：`https://erpapistaging.yeusoft.net/FxErpApi/FXDIYReport/GetDIYReportData`
- 请求参数：`{"gridid": "E004001008_2", "menuid": "E004001008", "parameter": {"BeginDate": "20250301", "Depart": "'A0190248'", "EndDate": "20260317", "Operater": "", "Tiem": "1", "WareClause": ""}}`
- capture：`/Users/lizhihui/Workspace/Black-Tony/reports/capture-cache/销售清单.json`
- 截图：销售清单-1.png, 销售清单-2.png, 销售清单-3.png
- 抓取质量：`full-range-data`
- 响应结构：`erp-retdata-dict`
- JSON 行数：`9764`
- 字段列表：零售单号, 明细流水, 单据类型, 店铺名称, 款号, 品名, 吊牌价, 折扣, 单价, 颜色, 尺码, 数量, 金额, 吊牌金额, 输入人, 输入时间, 销售日期, 班组, 导购员, 会员卡号, 参与活动, 商城扣点, 成本价, 所属大区, 分管业务员, 品牌, 商品大类, 商品中类, 商品小类, 波段, 年份, 季节, 性别, 主题, 系列, 款式定位, 价格段, 设计师, 单据备注, 明细备注, 客户类型, 仓库分类, 业务主管, 上级店仓名, 地理区域, 省份, 城市, 区镇, 城市等级, 店铺面积, 店铺人数, 图片
- SQLite：sales_order_lines
- 动态列说明：
  - `ColumnsList`：零售单号，明细流水，单据类型，店铺名称，款号，品名，吊牌价，折扣，单价，颜色，尺码，数量，金额，吊牌金额，输入人，输入时间，销售日期，班组，导购员，会员卡号，参与活动，商城扣点，成本价，所属大区 等 52 列
- 备注：
  - 这张表是当前销售口径主来源，后续订单级校准、商品销售和回款校验都以它为锚点。

### 库存明细统计

- 状态：已经
- 结论：截图和 JSON 的两段动态尺码头、现有库存/零售汇总列都能对齐。
- 接口：`https://erpapistaging.yeusoft.net/eposapi/YisEposReport/SelDeptStockWaitList`
- 请求参数：`{"bdate": "20250301", "depts": "", "edate": "20260317", "page": 0, "pagesize": 0, "spenum": "", "stockflag": "0", "warecause": ""}`
- capture：`/Users/lizhihui/Workspace/Black-Tony/reports/capture-cache/库存明细统计.json`
- 截图：库存明细统计-1.png, 库存明细统计-2.png, 库存明细统计-3.png
- 抓取质量：`full-range-data`
- 响应结构：`erp-retdata-list`
- JSON 行数：`981`
- 字段列表：DeptName, WareName, Spec, ColorName, Type, Type1, Type2, Date1, Season, Pd, RetailPrice, Trade, Img, Sex, col01, col02, col03, col04, col05, col06, col07, col08, col09, col010, col011, col012, col013, col014, col015, col016, col017, col018, col019, col020, col021, col022, col023, col024, col025, col026, col027, col028, col029, col030, col031, col032, col033, col034, col035, NTotalNum, NTotalMoney, col036, col037, col038, col039, col040, col041, col042, col043, col044, col045, col046, col047, col048, col049, col050, col051, col052, col053, col054, col055, col056, col057, col058, col059, col060, col061, col062, col063, col064, col065, col066, col067, col068, col069, col070, STotalNum, STotalMoney
- SQLite：inventory_detail_snapshots、size_metric_breakdowns
- 动态列说明：
  - `Title` 第 1 行：col01=90/均码/均码/均码，col02=100/XXS/8-10/75A，col03=110/XS/10-12/75B，col04=120/S/12-14/80A，col05=130/M/14-16/80B，col06=140/L/16-18/85A，col07=150/XL/18-20/85B，col08=160/XXL/20-22/75C，col09=170/XXXL/22-24/80C，col010=180/ / /85C，col011=66，col012=73 等 13 列
  - `Title` 第 2 行：col036=90/均码/均码/均码，col037=100/XXS/8-10/75A，col038=110/XS/10-12/75B，col039=120/S/12-14/80A，col040=130/M/14-16/80B，col041=140/L/16-18/85A，col042=150/XL/18-20/85B，col043=160/XXL/20-22/75C，col044=170/XXXL/22-24/80C，col045=180/ / /85C，col046=66，col047=73 等 13 列
- 备注：
  - `NTotalNum/NTotalMoney` 对应现有库存数量/金额，`STotalNum/STotalMoney` 对应零售数量/金额。
  - `Title` 有两行，既包含尺码头也包含第二段动态列头，不能只读第一行。

### 库存零售统计

- 状态：已经
- 结论：三张截图覆盖了同一张表的所有列，`StoU` 和零售合计列能和 JSON 对上。
- 接口：`https://erpapistaging.yeusoft.net/eposapi/YisEposReport/SelDeptStockSaleList`
- 请求参数：`{"bdate": "20250301", "depts": "", "edate": "20260317", "page": 0, "pagesize": 0, "spenum": "", "warecause": ""}`
- capture：`/Users/lizhihui/Workspace/Black-Tony/reports/capture-cache/库存零售统计.json`
- 截图：库存零售统计-1.png, 库存零售统计-2.png, 库存零售统计-3.png
- 抓取质量：`full-range-data`
- 响应结构：`erp-retdata-list`
- JSON 行数：`1341`
- 字段列表：DeptName, WareName, Spec, ColorName, Type, Type1, Type2, Date1, Season, Pd, RetailPrice, Trade, Img, StoU, col01, col02, col03, col04, col05, col06, col07, col08, col09, col010, col011, col012, col013, col014, col015, col016, col017, col018, col019, col020, STotalNum, STotalMoney, col021, col022, col023, col024, col025, col026, col027, col028, col029, col030, col031, col032, col033, col034, col035, col036, col037, col038, col039, col040, NTotalNum, NTotalMoney
- SQLite：inventory_sales_snapshots、size_metric_breakdowns
- 动态列说明：
  - `Title` 第 1 行：col01=90/均码/均码/均码，col02=100/XXS/8-10/75A，col03=110/XS/10-12/75B，col04=120/S/12-14/80A，col05=130/M/14-16/80B，col06=140/L/16-18/85A，col07=150/XL/18-20/85B，col08=160/XXL/20-22/75C，col09=170/XXXL/22-24/80C，col010=180/ / /85C，col011=66，col012=73 等 13 列
  - `Title` 第 2 行：col021=90/均码/均码/均码，col022=100/XXS/8-10/75A，col023=110/XS/10-12/75B，col024=120/S/12-14/80A，col025=130/M/14-16/80B，col026=140/L/16-18/85A，col027=150/XL/18-20/85B，col028=160/XXL/20-22/75C，col029=170/XXXL/22-24/80C，col030=180/ / /85C，col031=66，col032=73 等 13 列
- 备注：
  - `StoU=库销比`，`STotalNum=零售小计`，`STotalMoney=零售金额`。

### 库存总和分析-按年份季节

- 状态：已经
- 结论：当前 capture-cache 里的 `库存综合分析.json` 请求参数是 `rtype=1`，能和这张“按年份季节”截图对上。
- 接口：`https://erpapistaging.yeusoft.net/eposapi/YisEposReport/SelStockAnalysisList`
- 请求参数：`{"rtype": 1, "spenum": "", "warecause": ""}`
- capture：`/Users/lizhihui/Workspace/Black-Tony/reports/capture-cache/库存综合分析.json`
- 截图：库存综合分析-按年份季节.png
- 抓取质量：`snapshot-data`
- 响应结构：`erp-retdata-list`
- JSON 行数：`14`
- 字段列表：Num, Year, Season, SL1, SLPERT1, JE1, JEPERT1, KS1, KSPERT1, SL2, SLPERT2, JE2, JEPERT2, KS2, KSPERT2, SL3, JE3, KS3
- SQLite：当前未单独入 SQLite，仅在字段审计和页面解释时使用。
- 备注：
  - `SL*=数量`，`JE*=金额`，`KS*=款数`；`*PERT*` 是对应占比。
  - `SL1/JE1/KS1` 是去年区块，`SL2/JE2/KS2` 是今年区块，`SL3/JE3/KS3` 是涨幅。

### 库存总和分析-按中分类

- 状态：高度怀疑
- 结论：当前 capture-cache 里只有 `rtype=1` 的 JSON，没有抓到 `rtype=2` 响应，无法和这张“按中分类”截图做 1:1 对照。
- 接口：`https://erpapistaging.yeusoft.net/eposapi/YisEposReport/SelStockAnalysisList`
- 请求参数：`{"rtype": 1, "spenum": "", "warecause": ""}`
- capture：`/Users/lizhihui/Workspace/Black-Tony/reports/capture-cache/库存综合分析.json`
- 截图：库存综合分析-按中分类.png
- 抓取质量：`snapshot-data`
- 响应结构：`erp-retdata-list`
- JSON 行数：`14`
- 字段列表：Num, Year, Season, SL1, SLPERT1, JE1, JEPERT1, KS1, KSPERT1, SL2, SLPERT2, JE2, JEPERT2, KS2, KSPERT2, SL3, JE3, KS3
- SQLite：当前未入 SQLite。
- 备注：
  - 这张图先不要拿 `库存综合分析.json` 直接解释，必须补抓 `rtype=2` 的真实响应。
  - 当前抓到的请求参数是 {"rtype": 1, "spenum": "", "warecause": ""}，没有满足预期 {"rtype": 2}。

### 库存总和分析-按波段

- 状态：高度怀疑
- 结论：当前 capture-cache 里只有 `rtype=1` 的 JSON，没有抓到 `rtype=3` 响应，无法和这张“按波段”截图做 1:1 对照。
- 接口：`https://erpapistaging.yeusoft.net/eposapi/YisEposReport/SelStockAnalysisList`
- 请求参数：`{"rtype": 1, "spenum": "", "warecause": ""}`
- capture：`/Users/lizhihui/Workspace/Black-Tony/reports/capture-cache/库存综合分析.json`
- 截图：库存综合分析-按波段分析.png
- 抓取质量：`snapshot-data`
- 响应结构：`erp-retdata-list`
- JSON 行数：`14`
- 字段列表：Num, Year, Season, SL1, SLPERT1, JE1, JEPERT1, KS1, KSPERT1, SL2, SLPERT2, JE2, JEPERT2, KS2, KSPERT2, SL3, JE3, KS3
- SQLite：当前未入 SQLite。
- 备注：
  - 这张图先不要用现有 `库存综合分析.json` 解释，必须补抓 `rtype=3`。
  - 当前抓到的请求参数是 {"rtype": 1, "spenum": "", "warecause": ""}，没有满足预期 {"rtype": 3}。

### 库存多维分析

- 状态：已经
- 结论：五张截图共同构成一张横向超宽表，`A01~A013` 的尺码列、`AStock` 和 `AMoney` 都能和 JSON 对上。
- 接口：`https://erpapistaging.yeusoft.net/eposapi/YisEposReport/SelDeptStockAnalysis`
- 请求参数：`{"bdate": "20250301", "depts": "", "edate": "20260317", "page": 0, "pagesize": 0, "spenum": "", "stockflag": "0", "warecause": ""}`
- capture：`/Users/lizhihui/Workspace/Black-Tony/reports/capture-cache/库存多维分析.json`
- 截图：库存多维分析-1.png, 库存多维分析-2.png, 库存多维分析-3.png, 库存多维分析-4.png, 库存多维分析-5.png
- 抓取质量：`full-range-data`
- 响应结构：`erp-retdata-list`
- JSON 行数：`981`
- 字段列表：Num, DeptName, WareName, Spec, ColorName, Type, Type1, Type2, Date1, Season, Pd, RetailPrice, Trade, Img, WareCode, DeptCode, A01, A02, A03, A04, A05, A06, A07, A08, A09, A010, A011, A012, A013, A014, A015, A016, A017, A018, A019, A020, AStock, AMoney, B01, B02, B03, B04, B05, B06, B07, B08, B09, B010, B011, B012, B013, B014, B015, B016, B017, B018, B019, B020, BStock, BMoney, D01, D02, D03, D04, D05, D06, D07, D08, D09, D010, D011, D012, D013, D014, D015, D016, D017, D018, D019, D020, DStock, DMoney, C01, C02, C03, C04, C05, C06, C07, C08, C09, C010, C011, C012, C013, C014, C015, C016, C017, C018, C019, C020, CStock, CMoney, F01, F02, F03, F04, F05, F06, F07, F08, F09, F010, F011, F012, F013, F014, F015, F016, F017, F018, F019, F020, FStock, FMoney
- SQLite：当前未单独入 SQLite。
- 备注：
  - `AStock=现有小计`，`AMoney=现有金额`。

### 进销存统计

- 状态：已经
- 结论：三张截图与 `SelInSalesReport` 返回字段完全对应，数量列和分类维度都能对上。
- 接口：`https://erpapistaging.yeusoft.net/eposapi/YisEposReport/SelInSalesReport`
- 请求参数：`{"bdate": "20250301", "edate": "20260317", "page": 0, "pagesize": 0, "sort": "", "spenum": "", "warecause": ""}`
- capture：`/Users/lizhihui/Workspace/Black-Tony/reports/capture-cache/进销存统计.json`
- 截图：进销存统计-1.png, 进销存统计-2.png, 进销存统计-3.png
- 抓取质量：`full-range-data`
- 响应结构：`erp-retdata-list`
- JSON 行数：`1546`
- 字段列表：TrademarkName, dl, zl, xl, SpeNum, WareName, RetailPrice, LastAmount, InAmount, TBInAmount, RetuAmount, TBOutAmount, SaleAmount, ZMStockNum, BSOutAmount, StockNum, WaitStockNum, dxl, Year, Season, PdName, Sex, ColorName, ColorCode, Img
- SQLite：stock_flow_snapshots
- 备注：
  - `LastAmount=期初数量`，`InAmount=到货数量`，`TBInAmount=调入数量`，`RetuAmount=退货数量`，`TBOutAmount=调出数量`。
  - `ZMStockNum=账面库存`，`StockNum=实际库存`，`WaitStockNum=途库存`，`dxl=动销率`。

### 出入库单据

- 状态：已经
- 结论：页面列头、单据状态和首行值都能和 `SelOutInStockReport` 当前响应对上。
- 接口：`https://erpapistaging.yeusoft.net/eposapi/YisEposReport/SelOutInStockReport`
- 请求参数：`{"bdate": "20250301", "datetype": "1", "doctype": "1,2,3,4,5,6,7", "edate": "20260317", "page": 0, "pagesize": 0, "spenum": "", "type": "已出库,已入库,在途", "warecause": ""}`
- capture：`/Users/lizhihui/Workspace/Black-Tony/reports/capture-cache/出入库单据.json`
- 截图：出入库单据-1.png
- 抓取质量：`full-range-data`
- 响应结构：`erp-retdata-list`
- JSON 行数：`307`
- 字段列表：DocType, SeasonType, DocStat, DocNo, WhID, InWhID, ComeDate, ReceDate, TN, Transtat, TP, TRP, Remark
- SQLite：movement_docs
- 备注：
  - `TN=数量`，`TP=总金额`，`TRP=吊牌金额`。
  - 当前 SQLite 只保留了 `TRP/吊牌金额` 到 `movement_docs.amount`，`TP/总金额` 还没有单独入库。

### 日进销存

- 状态：高度怀疑
- 结论：截图在，但当前 capture-cache 只有 opened-only，没有请求体和响应体，没法和 JSON 做精确对照。
- 接口：`https://erpapistaging.yeusoft.net/eposapi/YisEposReport/SelInSalesReportByDay`
- 请求参数：`{"bdate": "20250301", "edate": "20250331", "page": 0, "pagesize": 0, "spenum": "", "warecause": ""}`
- capture：`/Users/lizhihui/Workspace/Black-Tony/reports/capture-cache/日进销存.json`
- 截图：日进销存.png
- 抓取质量：`full-range-data`
- 响应结构：`erp-retdata-dict`
- JSON 行数：`31`
- 字段列表：Num, Date, DeptName, DeptCode, LastAmount, LastAmountPrice, InAmount, InAmountPrice, TBInAmount, TBInAmountPrice, RetuAmount, RetuAmountPrice, TBOutAmount, TBOutAmountPrice, SaleAmount, SaleAmountPrice, BSOutAmount, BSOutAmountPrice, ZMStockNum, ZMStockNumPrice, StockNum, StockNumPrice, WaitStockNum, WaitStockNumPrice
- SQLite：当前无响应，也未入 SQLite。
- 备注：
  - 这张表必须重新补抓成功响应后，才能继续做字段确认和 SQLite 同步。

### 会员总和分析

- 状态：已经
- 结论：截图和 `SelVipAnalysisReport` 的会员分析字段能对上，积分、储值、消费频次等字段明确。
- 接口：`https://erpapistaging.yeusoft.net/eposapi/YisEposReport/SelVipAnalysisReport`
- 请求参数：`{"birthbdate": "", "birthedate": "", "page": 0, "pagesize": 0, "salebdate": "20250301", "saleedate": "20260317", "salemoney1": "0", "salemoney2": "0", "tag": "", "type": ""}`
- capture：`/Users/lizhihui/Workspace/Black-Tony/reports/capture-cache/会员综合分析.json`
- 截图：会员综合分析.png
- 抓取质量：`full-range-data`
- 响应结构：`erp-retdata-list`
- JSON 行数：`1184`
- 字段列表：Num, OperName, VipName, VipCardID, VipGrade, VipCardType, BirthDate, Point, TotalPoint, RetuMoney, SSMoney, BVMoney, VipPosCardNum, InputDate, LastSaleDate, EachSale, SaleNumByYear, SaleStock, SaleNum, TotalMoney, SaleWeek, SaleSpace, VipType, VipTag
- SQLite：vip_analysis_members
- 备注：
  - `Point=当前积分`，`TotalPoint=总积分`，`SSMoney=储值消费`，`BVMoney=储值余额`。
  - `EachSale=笔单价`，`SaleNumByYear=年均消费次数`，`SaleStock=消费件数`，`SaleNum=消费单数`，`TotalMoney=累计消费金额`。

### 会员消费排行

- 状态：已经
- 结论：两张截图与 `SelVipSaleRank` 返回字段一致，排名、单数、款数、销量、销额和占比都能对上。
- 接口：`https://erpapistaging.yeusoft.net/eposapi/YisEposReport/SelVipSaleRank`
- 请求参数：`{"bdate": "20250301", "edate": "20260317", "page": 0, "pagesize": 0}`
- capture：`/Users/lizhihui/Workspace/Black-Tony/reports/capture-cache/会员消费排行.json`
- 截图：会员消费排行榜-1.png, 会员消费排行榜-2.png
- 抓取质量：`full-range-data`
- 响应结构：`erp-retdata-dict`
- JSON 行数：`1193`
- 字段列表：Num, UserName, VipCardID, N, WareCnt, TN, TM, P, Img
- SQLite：member_sales_rank
- 备注：
  - `N=单数`，`WareCnt=款数`，`TN=销量`，`TM=销售金额`，`P=销售占比`。

### 储值按店汇总

- 状态：已经
- 结论：截图列头与 `ColumnsList` 一致，门店级储值金额汇总没有歧义。
- 接口：`https://erpapistaging.yeusoft.net/FxErpApi/FXDIYReport/GetDIYReportData`
- 请求参数：`{"gridid": "E004004003_main", "menuid": "E004004003", "parameter": {"BeginDate": "2025-03-01", "EndDate": "2026-03-17"}}`
- capture：`/Users/lizhihui/Workspace/Black-Tony/reports/capture-cache/储值按店汇总.json`
- 截图：储值按店汇总.png
- 抓取质量：`full-range-data`
- 响应结构：`erp-retdata-dict`
- JSON 行数：`1`
- 字段列表：Area, Organization, OrganizationName, Customer, CustomerName, Type, TypeName, VipCount, RechargeVipCount, RechargeVipCountRate, StockUseMoney, StockRechargeMoney, StockGiveMoney, StockMoney, BvGiveMoney, BvMoney, RebateMoney, UsePoint
- SQLite：当前未入 SQLite。
- 动态列说明：
  - `ColumnsList`：Area，Organization，OrganizationName，Customer，CustomerName，Type，TypeName，VipCount，RechargeVipCount，RechargeVipCountRate，StockUseMoney，StockRechargeMoney，StockGiveMoney，StockMoney，BvGiveMoney，BvMoney，RebateMoney，UsePoint

### 储值卡汇总

- 状态：已经
- 结论：截图和 `ColumnsList` 一致，卡级余额/充值/消费字段都能对应。
- 接口：`https://erpapistaging.yeusoft.net/FxErpApi/FXDIYReport/GetDIYReportData`
- 请求参数：`{"gridid": "E004004004_main", "menuid": "E004004004", "parameter": {"BeginDate": "2025-03-01", "EndDate": "2026-03-17", "Search": ""}}`
- capture：`/Users/lizhihui/Workspace/Black-Tony/reports/capture-cache/储值卡汇总.json`
- 截图：储值卡汇总.png
- 抓取质量：`full-range-data`
- 响应结构：`erp-retdata-dict`
- JSON 行数：`19`
- 字段列表：Area, Organization, OrganizationName, Customer, CustomerName, Type, TypeName, VipCardId, VipCode, VipName, BeginMoney, AdjustmentMoney, CashRechargeMoney, SwipeCardRechargeMoney, AlipayRechargeMoney, WechatRechargeMoney, OtherRechargeMoney, ScanCodeRechargeMoney, StockUseMoney, EndMoney, NowMoney
- SQLite：当前未入 SQLite。
- 动态列说明：
  - `ColumnsList`：Area，Organization，OrganizationName，Customer，CustomerName，Type，TypeName，VipCardId，VipCode，VipName，BeginMoney，AdjustmentMoney，CashRechargeMoney，SwipeCardRechargeMoney，AlipayRechargeMoney，WechatRechargeMoney，OtherRechargeMoney，ScanCodeRechargeMoney，StockUseMoney，EndMoney，NowMoney

### 储值卡明细

- 状态：已经
- 结论：两张截图只是同一张明细表的横向拆屏，发生时间、单号、期初/期末余额与充值字段都能对上。
- 接口：`https://erpapistaging.yeusoft.net/FxErpApi/FXDIYReport/GetDIYReportData`
- 请求参数：`{"gridid": "E004004005_main", "menuid": "E004004005", "parameter": {"BeginDate": "2025-03-01", "EndDate": "2026-03-17", "Search": ""}}`
- capture：`/Users/lizhihui/Workspace/Black-Tony/reports/capture-cache/储值卡明细.json`
- 截图：储值卡明细-2.png, 储值卡明细.png
- 抓取质量：`full-range-data`
- 响应结构：`erp-retdata-dict`
- JSON 行数：`78`
- 字段列表：Area, Organization, OrganizationName, Customer, CustomerName, Type, TypeName, HappenDate, HappenCustomer, HappenNo, VipCardId, VipName, BeginMoney, AdjustmentMoney, CashRechargeMoney, SwipeCardRechargeMoney, AlipayRechargeMoney, WechatRechargeMoney, OtherRechargeMoney, ScanCodeRechargeMoney, StockUseMoney, EndMoney, OperName
- SQLite：当前未入 SQLite。
- 动态列说明：
  - `ColumnsList`：Area，Organization，OrganizationName，Customer，CustomerName，Type，TypeName，HappenDate，HappenCustomer，HappenNo，VipCardId，VipName，BeginMoney，AdjustmentMoney，CashRechargeMoney，SwipeCardRechargeMoney，AlipayRechargeMoney，WechatRechargeMoney，OtherRechargeMoney，ScanCodeRechargeMoney，StockUseMoney，EndMoney，OperName

### 商品销售情况

- 状态：已经
- 结论：两张截图与 `SelSaleReportData` 的字段一致，销量、销额、累销、库存和周度序列字段都在当前响应内。
- 接口：`https://erpapistaging.yeusoft.net/eposapi/YisEposReport/SelSaleReportData`
- 请求参数：`{"bdate": "20250301", "edate": "20260317", "spenum": "", "warecause": ""}`
- capture：`/Users/lizhihui/Workspace/Black-Tony/reports/capture-cache/商品销售情况.json`
- 截图：商品销售情况-1.png, 商品销售情况-2.png
- 抓取质量：`full-range-data`
- 响应结构：`erp-retdata-dict`
- JSON 行数：`1341`
- 字段列表：Num, WareCode, ColorCode, Specification, Img, Color, SaleAmount, SaleMoney, SumSaleAmount, SumSaleMoney, SumArrival, WeekSellOut, SumSellOut, StockNum, FirstArrivalDate, FirstSaleDate, DaysSold, Week1, Week2, Week3, Week4, Week5, Week6, Week7, Week8, Trade, Year, Season, BD, MType, SumReturn
- SQLite：product_sales_snapshot
- 备注：
  - `SaleAmount=销量`，`SaleMoney=销售金额`，`SumSaleAmount=累销`，`SumSaleMoney=累销额`，`StockNum=库存`。

### 商品品类分析

- 状态：高度怀疑
- 结论：截图页面同时出现了“进货/销售/库存”三段，但当前抓到的 `type=3` JSON 只明显对得上其中的库存区块，不能把三段都当成同一份响应。
- 接口：`https://erpapistaging.yeusoft.net/eposapi/YisEposWareTypeAnalysis/SelWareTypeAnalysisList`
- 请求参数：`{"bdate": "20250301", "edate": "20260317", "gridid": "E004005002_1", "menuid": "E004005002", "type": 3, "warecause": ""}`
- capture：`/Users/lizhihui/Workspace/Black-Tony/reports/capture-cache/商品品类分析.json`
- 截图：商品品类分析-1.png, 商品品类分析-2.png, 商品品类分析-3.png
- 抓取质量：`full-range-data`
- 响应结构：`erp-retdata-list`
- JSON 行数：`13`
- 字段列表：DeptName, Category, TypeCode, 20232SpeNums, 20232Amount, 20232Money, 20232Ratio, 20233SpeNums, 20233Amount, 20233Money, 20233Ratio, 20234SpeNums, 20234Amount, 20234Money, 20234Ratio, 20241SpeNums, 20241Amount, 20241Money, 20241Ratio, 20242SpeNums, 20242Amount, 20242Money, 20242Ratio, 20243SpeNums, 20243Amount, 20243Money, 20243Ratio, 20244SpeNums, 20244Amount, 20244Money, 20244Ratio, 20251SpeNums, 20251Amount, 20251Money, 20251Ratio, 20252SpeNums, 20252Amount, 20252Money, 20252Ratio, 20253SpeNums, 20253Amount, 20253Money, 20253Ratio, 20254SpeNums, 20254Amount, 20254Money, 20254Ratio, 2026SpeNums, 2026Amount, 2026Money, 2026Ratio, 20261SpeNums, 20261Amount, 20261Money, 20261Ratio, 20262SpeNums, 20262Amount, 20262Money, 20262Ratio, 20264SpeNums, 20264Amount, 20264Money, 20264Ratio
- SQLite：当前未入 SQLite。
- 动态列说明：
  - `GridHeader`：DeptName=店铺名称，Category=品类，TypeCode=品类代码，20232=23夏，20233=23秋，20234=23冬，20241=24春，20242=24夏，20243=24秋，20244=24冬，20251=25春，20252=25夏 等 18 项
  - `GridHeaderList`：20232SpeNums=款数，20232Amount=数量，20232Money=金额，20232Ratio=金额占比(%)，20233SpeNums=款数，20233Amount=数量，20233Money=金额，20233Ratio=金额占比(%)，20234SpeNums=款数，20234Amount=数量，20234Money=金额，20234Ratio=金额占比(%)，20241SpeNums=款数，20241Amount=数量，20241Money=金额，20241Ratio=金额占比(%) 等 60 项
- 备注：
  - 当前 `retdata[0].Data` 的值和截图底部“库存”区块一致；上方“进货/销售”需要继续补抓对应响应再确认。

### 门店销售月报

- 状态：已经
- 结论：截图表头和 `DeptMonthSalesReport` 的 `PageData.Items` 字段一致；金额脱敏为 `****` 也是后端返回结果，不是对照异常。
- 接口：`https://jyapistaging.yeusoft.net/JyApi/DeptMonthSalesReport/DeptMonthSalesReport`
- 请求参数：`{"BeginDate": "2025-03-01", "EndDate": "2026-03-17", "MBeginDate": "2025-01-31", "MEndDate": "2026-02-16", "PageIndex": 1, "PageSize": 2000, "Type": "1", "YBeginDate": "2024-02-29", "YEndDate": "2025-03-16"}`
- capture：`/Users/lizhihui/Workspace/Black-Tony/reports/capture-cache/门店销售月报.json`
- 截图：门店销售月报.png
- 抓取质量：`full-range-data`
- 响应结构：`jyapi-page-items`
- JSON 行数：`366`
- 字段列表：DeptName, Date, Week, Numberofweeks, SalePNum, SaleAmount, SaleMoney, Jointandseveral, Discountamount, Actualsales, CustomerSale, Retailcost, Retailgrossmargin, Grossprofitmargin, RetailMoney, VipSaleMoney, ProportionOfSales, YoY, MoM
- SQLite：当前未入 SQLite，仅在 `scripts.dashboard.yeusoft` 中做页面解析。
- 备注：
  - `SalePNum=销售票数`，`SaleAmount=销售数`，`SaleMoney=销售金额`，`Jointandseveral=连带`。
  - `Discountamount=折扣金额`，`Actualsales=实际销额`，`CustomerSale=客单价`，`RetailMoney=吊牌额`，`VipSaleMoney=会员金额`。

### 每日流水单

- 状态：已经
- 结论：两张截图与 `SelectRetailDocPaymentSlip` 的 `Data.Columns/List` 完整一致，支付方式列也能对上。
- 接口：`https://jyapistaging.yeusoft.net/JyApi/ReconciliationAnalysis/SelectRetailDocPaymentSlip`
- 请求参数：`{"BeginDate": "2025-03-01", "EndDate": "2026-03-17", "LastDate": "", "MenuID": "E004006001", "Search": "", "SearchType": "1"}`
- capture：`/Users/lizhihui/Workspace/Black-Tony/reports/capture-cache/每日流水单.json`
- 截图：每日流水单-1.png, 每日流水单-2.png
- 抓取质量：`full-range-data`
- 响应结构：`jyapi-columns-list`
- JSON 行数：`3996`
- 字段列表：Area, Organization, OrganizationName, Customer, CustomerName, Type, TypeName, MakeDate, DocType, DocTypeName, DocNo, Guide, TagMoney, Amount, Money, ActualMoney, SaleDiscount, UnitPrice, VipMovePhone, VipName, Remark, SourceNo, CashMoney, SwipeMoney, WxMoney, AlipayMoney, StockMoney, OrderMoney, CouponMoney, UseRebateMoney, UseBvMoney, OtherMoney, ActivityMoney, ScanCodeMoney, WipeZeroMoney, LookChangeMoney
- SQLite：daily_flow_docs
- 动态列说明：
  - `ColumnsList`：Area，Organization，OrganizationName，Customer，CustomerName，Type，TypeName，MakeDate，DocType，DocTypeName，DocNo，Guide，TagMoney，Amount，Money，ActualMoney，SaleDiscount，UnitPrice，VipMovePhone，VipName，Remark，SourceNo，CashMoney，SwipeMoney 等 36 列
- 备注：
  - 这张表是订单级支付流水，和销售净额不是同一个口径，后面做回款校验时要单独看。

### 会员中心

- 状态：高度怀疑
- 结论：表格字段本身能和 `SelVipInfoList` 对齐，但截图顶部四张统计卡片不在当前响应里，所以整屏还不能算 100% 全量确认。
- 接口：`https://erpapistaging.yeusoft.net/eposapi/YisEposVipManage/SelVipInfoList`
- 请求参数：`{"VolumeNumber": "", "condition": "", "searchval": ""}`
- capture：`/Users/lizhihui/Workspace/Black-Tony/reports/capture-cache/会员中心.json`
- 截图：会员中心-1.png, 会员中心-2.png
- 抓取质量：`snapshot-data`
- 响应结构：`erp-retdata-dict`
- JSON 行数：`1300`
- 字段列表：Num, VipCode, VipCardID, Name, MobliePhone, Birthday, Grade, GradeName, TotalPoint, ValidPoint, ValidStore, ValidUMoney, nsMoney, AttributionGuideName, AttributionDept, AttributionDeptName, PlatSet, LastSaleDate, RegisterDate, EndDate, TotalSaleFrequency, TotalSaleAmount, TotalSaleMoney, Label, Img, CheckStatus, StockCardMoney, StockCardBv, CanUsePosNum, SolarLunarCalendar, ssMoneyRebate, NickName, JtkhName
- SQLite：当前未入 SQLite。
- 备注：
  - 当前表格里的“会员卡号”实际对应 `VipCardID`，`VipCode` 更像内部会员编码，并没有显示在当前列表列头里。
  - `AttributionGuideName=归属导购`，`AttributionDeptName=归属店铺`，`StockCardMoney=储值卡金额`，`StockCardBv=储值卡赠送金额`，`CanUsePosNum=可用券数量`。
