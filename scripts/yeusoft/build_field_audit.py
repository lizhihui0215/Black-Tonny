#!/usr/bin/env python3
"""Build a reproducible screenshot-vs-API field audit for Yeusoft report captures."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CAPTURE_DIR = ROOT / "reports" / "capture-cache"
IMAGE_DIR = ROOT / "scripts" / "yeusoft" / "API-images"
OUTPUT_DIR = ROOT / "reports" / "calibration"
OUTPUT_JSON = OUTPUT_DIR / "api_field_audit.json"
OUTPUT_MD = OUTPUT_DIR / "api_field_audit.md"
REPORT_SAMPLES_MD = ROOT / "scripts" / "yeusoft" / "report_api_samples.md"
SUMMARY_START = "<!-- FIELD_AUDIT_SUMMARY:START -->"
SUMMARY_END = "<!-- FIELD_AUDIT_SUMMARY:END -->"

import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.dashboard.yeusoft import decode_yeusoft_text, extract_capture_request, extract_capture_response  # noqa: E402


@dataclass(frozen=True)
class ReportSpec:
    display_name: str
    capture_name: str
    url_keyword: str
    image_prefixes: tuple[str, ...] = field(default_factory=tuple)
    status: str = "已经"
    reason: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)
    sqlite_targets: tuple[str, ...] = field(default_factory=tuple)
    sqlite_note: str = ""
    expected_request: dict[str, Any] = field(default_factory=dict)


REPORT_SPECS: tuple[ReportSpec, ...] = (
    ReportSpec(
        display_name="零售明细统计",
        capture_name="零售明细统计",
        url_keyword="SelDeptSaleList",
        image_prefixes=("零售明细统计",),
        status="已经",
        reason="表格列头、动态尺码列和合计列都能和当前 JSON 的 `retdata[0].Title/Data` 对上，两张截图只是横向拆屏。",
        notes=(
            "`TotalNum` 对应零售小计，`TotalRetailMoney` 对应零售金额，`TotalMoney` 对应销售金额，`Discount` 对应折扣。",
            "尺码字段不能把 `col01~col013` 固化，必须按 `Title` 解码成 `90/均码` 这类真实尺码头。",
        ),
        sqlite_targets=("retail_detail_snapshots", "size_metric_breakdowns"),
    ),
    ReportSpec(
        display_name="导购员报表",
        capture_name="导购员报表",
        url_keyword="SelPersonSale",
        image_prefixes=("导购员报表",),
        status="已经",
        reason="截图列头与 `SelPersonSale` 返回字段能逐一对应，付款方式和会员字段也能对上。",
        notes=(
            "`Amount=销量`，`TotalRetailMoeny=吊牌金额`，`TotalMoney=销售金额`，`Saleps=票数`，`DJ=单效`，`FJ=连带`。",
            "`PosMoney=储值`，`StockRechargeMoney=本期储值金额`，`ssMoneyRebate=返利金额`。",
        ),
        sqlite_targets=("guide_report_summary",),
    ),
    ReportSpec(
        display_name="店铺零售清单",
        capture_name="店铺零售清单",
        url_keyword="GetDIYReportData",
        image_prefixes=("店铺零售清单",),
        status="已经",
        reason="四张截图只是同一张明细表的横向切片，`ColumnsList` 与页面列头一致。",
        notes=(
            "当前表是全店铺范围的零售清单，适合拿来做主表校验和补充维度，不要和单店 `销售清单` 混用。",
        ),
        sqlite_targets=("sales_order_lines",),
        sqlite_note="当前以 validation 源进入 `sales_order_lines`，用于和主店销售清单交叉校验。",
    ),
    ReportSpec(
        display_name="销售清单",
        capture_name="销售清单",
        url_keyword="GetDIYReportData",
        image_prefixes=("销售清单",),
        status="已经",
        reason="三张截图与 `ColumnsList` 一致，是当前主店销售主表。",
        notes=(
            "这张表是当前销售口径主来源，后续订单级校准、商品销售和回款校验都以它为锚点。",
        ),
        sqlite_targets=("sales_order_lines",),
        sqlite_note="当前以 master 源进入 `sales_order_lines`。",
    ),
    ReportSpec(
        display_name="库存明细统计",
        capture_name="库存明细统计",
        url_keyword="SelDeptStockWaitList",
        image_prefixes=("库存明细统计",),
        status="已经",
        reason="截图和 JSON 的两段动态尺码头、现有库存/零售汇总列都能对齐。",
        notes=(
            "`NTotalNum/NTotalMoney` 对应现有库存数量/金额，`STotalNum/STotalMoney` 对应零售数量/金额。",
            "`Title` 有两行，既包含尺码头也包含第二段动态列头，不能只读第一行。",
        ),
        sqlite_targets=("inventory_detail_snapshots", "size_metric_breakdowns"),
    ),
    ReportSpec(
        display_name="库存零售统计",
        capture_name="库存零售统计",
        url_keyword="SelDeptStockSaleList",
        image_prefixes=("库存零售统计",),
        status="已经",
        reason="三张截图覆盖了同一张表的所有列，`StoU` 和零售合计列能和 JSON 对上。",
        notes=(
            "`StoU=库销比`，`STotalNum=零售小计`，`STotalMoney=零售金额`。",
        ),
        sqlite_targets=("inventory_sales_snapshots", "size_metric_breakdowns"),
    ),
    ReportSpec(
        display_name="库存总和分析-按年份季节",
        capture_name="库存综合分析",
        url_keyword="SelStockAnalysisList",
        image_prefixes=("库存综合分析-按年份季节",),
        status="已经",
        reason="当前 capture-cache 里的 `库存综合分析.json` 请求参数是 `rtype=1`，能和这张“按年份季节”截图对上。",
        notes=(
            "`SL*=数量`，`JE*=金额`，`KS*=款数`；`*PERT*` 是对应占比。",
            "`SL1/JE1/KS1` 是去年区块，`SL2/JE2/KS2` 是今年区块，`SL3/JE3/KS3` 是涨幅。",
        ),
        sqlite_note="当前未单独入 SQLite，仅在字段审计和页面解释时使用。",
        expected_request={"rtype": 1},
    ),
    ReportSpec(
        display_name="库存总和分析-按中分类",
        capture_name="库存综合分析",
        url_keyword="SelStockAnalysisList",
        image_prefixes=("库存综合分析-按中分类",),
        status="高度怀疑",
        reason="当前 capture-cache 里只有 `rtype=1` 的 JSON，没有抓到 `rtype=2` 响应，无法和这张“按中分类”截图做 1:1 对照。",
        notes=(
            "这张图先不要拿 `库存综合分析.json` 直接解释，必须补抓 `rtype=2` 的真实响应。",
        ),
        sqlite_note="当前未入 SQLite。",
        expected_request={"rtype": 2},
    ),
    ReportSpec(
        display_name="库存总和分析-按波段",
        capture_name="库存综合分析",
        url_keyword="SelStockAnalysisList",
        image_prefixes=("库存综合分析-按波段分析",),
        status="高度怀疑",
        reason="当前 capture-cache 里只有 `rtype=1` 的 JSON，没有抓到 `rtype=3` 响应，无法和这张“按波段”截图做 1:1 对照。",
        notes=(
            "这张图先不要用现有 `库存综合分析.json` 解释，必须补抓 `rtype=3`。",
        ),
        sqlite_note="当前未入 SQLite。",
        expected_request={"rtype": 3},
    ),
    ReportSpec(
        display_name="库存多维分析",
        capture_name="库存多维分析",
        url_keyword="SelDeptStockAnalysis",
        image_prefixes=("库存多维分析",),
        status="已经",
        reason="五张截图共同构成一张横向超宽表，`A01~A013` 的尺码列、`AStock` 和 `AMoney` 都能和 JSON 对上。",
        notes=(
            "`AStock=现有小计`，`AMoney=现有金额`。",
        ),
        sqlite_note="当前未单独入 SQLite。",
    ),
    ReportSpec(
        display_name="进销存统计",
        capture_name="进销存统计",
        url_keyword="SelInSalesReport",
        image_prefixes=("进销存统计",),
        status="已经",
        reason="三张截图与 `SelInSalesReport` 返回字段完全对应，数量列和分类维度都能对上。",
        notes=(
            "`LastAmount=期初数量`，`InAmount=到货数量`，`TBInAmount=调入数量`，`RetuAmount=退货数量`，`TBOutAmount=调出数量`。",
            "`ZMStockNum=账面库存`，`StockNum=实际库存`，`WaitStockNum=途库存`，`dxl=动销率`。",
        ),
        sqlite_targets=("stock_flow_snapshots",),
    ),
    ReportSpec(
        display_name="出入库单据",
        capture_name="出入库单据",
        url_keyword="SelOutInStockReport",
        image_prefixes=("出入库单据",),
        status="已经",
        reason="页面列头、单据状态和首行值都能和 `SelOutInStockReport` 当前响应对上。",
        notes=(
            "`TN=数量`，`TP=总金额`，`TRP=吊牌金额`。",
            "当前 SQLite 只保留了 `TRP/吊牌金额` 到 `movement_docs.amount`，`TP/总金额` 还没有单独入库。",
        ),
        sqlite_targets=("movement_docs",),
        sqlite_note="当前 `movement_docs` 只保留了数量与 `TRP/吊牌金额`。",
    ),
    ReportSpec(
        display_name="日进销存",
        capture_name="日进销存",
        url_keyword="SelInSalesReportByDay",
        image_prefixes=("日进销存",),
        status="高度怀疑",
        reason="截图在，但当前 capture-cache 只有 opened-only，没有请求体和响应体，没法和 JSON 做精确对照。",
        notes=(
            "这张表必须重新补抓成功响应后，才能继续做字段确认和 SQLite 同步。",
        ),
        sqlite_note="当前无响应，也未入 SQLite。",
    ),
    ReportSpec(
        display_name="会员总和分析",
        capture_name="会员综合分析",
        url_keyword="SelVipAnalysisReport",
        image_prefixes=("会员综合分析",),
        status="已经",
        reason="截图和 `SelVipAnalysisReport` 的会员分析字段能对上，积分、储值、消费频次等字段明确。",
        notes=(
            "`Point=当前积分`，`TotalPoint=总积分`，`SSMoney=储值消费`，`BVMoney=储值余额`。",
            "`EachSale=笔单价`，`SaleNumByYear=年均消费次数`，`SaleStock=消费件数`，`SaleNum=消费单数`，`TotalMoney=累计消费金额`。",
        ),
        sqlite_targets=("vip_analysis_members",),
    ),
    ReportSpec(
        display_name="会员消费排行",
        capture_name="会员消费排行",
        url_keyword="SelVipSaleRank",
        image_prefixes=("会员消费排行榜", "会员消费排行"),
        status="已经",
        reason="两张截图与 `SelVipSaleRank` 返回字段一致，排名、单数、款数、销量、销额和占比都能对上。",
        notes=(
            "`N=单数`，`WareCnt=款数`，`TN=销量`，`TM=销售金额`，`P=销售占比`。",
        ),
        sqlite_targets=("member_sales_rank",),
    ),
    ReportSpec(
        display_name="储值按店汇总",
        capture_name="储值按店汇总",
        url_keyword="GetDIYReportData",
        image_prefixes=("储值按店汇总",),
        status="已经",
        reason="截图列头与 `ColumnsList` 一致，门店级储值金额汇总没有歧义。",
        sqlite_note="当前未入 SQLite。",
    ),
    ReportSpec(
        display_name="储值卡汇总",
        capture_name="储值卡汇总",
        url_keyword="GetDIYReportData",
        image_prefixes=("储值卡汇总",),
        status="已经",
        reason="截图和 `ColumnsList` 一致，卡级余额/充值/消费字段都能对应。",
        sqlite_note="当前未入 SQLite。",
    ),
    ReportSpec(
        display_name="储值卡明细",
        capture_name="储值卡明细",
        url_keyword="GetDIYReportData",
        image_prefixes=("储值卡明细",),
        status="已经",
        reason="两张截图只是同一张明细表的横向拆屏，发生时间、单号、期初/期末余额与充值字段都能对上。",
        sqlite_note="当前未入 SQLite。",
    ),
    ReportSpec(
        display_name="商品销售情况",
        capture_name="商品销售情况",
        url_keyword="SelSaleReportData",
        image_prefixes=("商品销售情况",),
        status="已经",
        reason="两张截图与 `SelSaleReportData` 的字段一致，销量、销额、累销、库存和周度序列字段都在当前响应内。",
        notes=(
            "`SaleAmount=销量`，`SaleMoney=销售金额`，`SumSaleAmount=累销`，`SumSaleMoney=累销额`，`StockNum=库存`。",
        ),
        sqlite_targets=("product_sales_snapshot",),
    ),
    ReportSpec(
        display_name="商品品类分析",
        capture_name="商品品类分析",
        url_keyword="SelWareTypeAnalysisList",
        image_prefixes=("商品品类分析",),
        status="高度怀疑",
        reason="截图页面同时出现了“进货/销售/库存”三段，但当前抓到的 `type=3` JSON 只明显对得上其中的库存区块，不能把三段都当成同一份响应。",
        notes=(
            "当前 `retdata[0].Data` 的值和截图底部“库存”区块一致；上方“进货/销售”需要继续补抓对应响应再确认。",
        ),
        sqlite_note="当前未入 SQLite。",
        expected_request={"type": 3},
    ),
    ReportSpec(
        display_name="门店销售月报",
        capture_name="门店销售月报",
        url_keyword="DeptMonthSalesReport",
        image_prefixes=("门店销售月报",),
        status="已经",
        reason="截图表头和 `DeptMonthSalesReport` 的 `PageData.Items` 字段一致；金额脱敏为 `****` 也是后端返回结果，不是对照异常。",
        notes=(
            "`SalePNum=销售票数`，`SaleAmount=销售数`，`SaleMoney=销售金额`，`Jointandseveral=连带`。",
            "`Discountamount=折扣金额`，`Actualsales=实际销额`，`CustomerSale=客单价`，`RetailMoney=吊牌额`，`VipSaleMoney=会员金额`。",
        ),
        sqlite_note="当前未入 SQLite，仅在 `scripts.dashboard.yeusoft` 中做页面解析。",
    ),
    ReportSpec(
        display_name="每日流水单",
        capture_name="每日流水单",
        url_keyword="SelectRetailDocPaymentSlip",
        image_prefixes=("每日流水单",),
        status="已经",
        reason="两张截图与 `SelectRetailDocPaymentSlip` 的 `Data.Columns/List` 完整一致，支付方式列也能对上。",
        notes=(
            "这张表是订单级支付流水，和销售净额不是同一个口径，后面做回款校验时要单独看。",
        ),
        sqlite_targets=("daily_flow_docs",),
    ),
    ReportSpec(
        display_name="会员中心",
        capture_name="会员中心",
        url_keyword="SelVipInfoList",
        image_prefixes=("会员中心",),
        status="高度怀疑",
        reason="表格字段本身能和 `SelVipInfoList` 对齐，但截图顶部四张统计卡片不在当前响应里，所以整屏还不能算 100% 全量确认。",
        notes=(
            "当前表格里的“会员卡号”实际对应 `VipCardID`，`VipCode` 更像内部会员编码，并没有显示在当前列表列头里。",
            "`AttributionGuideName=归属导购`，`AttributionDeptName=归属店铺`，`StockCardMoney=储值卡金额`，`StockCardBv=储值卡赠送金额`，`CanUsePosNum=可用券数量`。",
        ),
        sqlite_note="当前未入 SQLite。",
    ),
)


def normalize_label(value: object) -> str:
    decoded = decode_yeusoft_text(value)
    decoded = re.sub(r"<br\s*/?>", "/", decoded, flags=re.IGNORECASE)
    decoded = decoded.replace("\u3000", " ")
    decoded = re.sub(r"\\s+", " ", decoded).strip(" /")
    return decoded


def stringify_payload(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def discover_images(prefixes: tuple[str, ...]) -> list[str]:
    matches: list[Path] = []
    for prefix in prefixes:
        matches.extend(sorted(IMAGE_DIR.glob(f"{prefix}*.png")))
    ordered: list[str] = []
    for path in matches:
        path_str = str(path.resolve())
        if path_str not in ordered:
            ordered.append(path_str)
    return ordered


def decode_columns(columns: list[object]) -> list[str]:
    return [normalize_label(column) for column in columns]


def extract_payload_rows(payload: dict[str, Any], shape: str) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    columns: list[str] = []
    metadata: dict[str, Any] = {"shape": shape}

    data_rows = payload.get("Data") or []
    raw_columns = payload.get("ColumnsList") or []
    if raw_columns and data_rows and isinstance(data_rows[0], list):
        columns = decode_columns(raw_columns)
        rows = [dict(zip(columns, row)) for row in data_rows if isinstance(row, list)]
    elif data_rows and isinstance(data_rows[0], dict):
        rows = data_rows
        columns = decode_columns(raw_columns) if raw_columns else [normalize_label(key) for key in rows[0].keys()]
    else:
        columns = decode_columns(raw_columns)

    title_rows = payload.get("Title") or []
    if title_rows:
        metadata["title_rows"] = extract_title_rows(title_rows)
    grid_header = payload.get("GridHeader") or []
    if grid_header:
        metadata["grid_header"] = extract_grid_headers(grid_header)
    grid_header_list = payload.get("GridHeaderList") or []
    if grid_header_list:
        metadata["grid_header_list"] = extract_grid_headers(grid_header_list)
    if payload.get("ColumnsList"):
        metadata["columns_list"] = decode_columns(payload.get("ColumnsList") or [])
    return rows, columns, metadata


def extract_rows_and_metadata(body: dict[str, Any] | None) -> tuple[list[dict[str, Any]], list[str], str, dict[str, Any]]:
    if not body:
        return [], [], "missing-response", {}

    if body.get("Success") is True:
        data_payload = body.get("Data") or {}
        if isinstance(data_payload, dict):
            columns = data_payload.get("Columns") or []
            rows = data_payload.get("List") or []
            if columns and rows and isinstance(rows[0], list):
                decoded_columns = decode_columns(columns)
                normalized_rows = [dict(zip(decoded_columns, row)) for row in rows if isinstance(row, list)]
                return normalized_rows, decoded_columns, "jyapi-columns-list", {
                    "columns_list": decoded_columns,
                }
            page_data = data_payload.get("PageData") or {}
            items = page_data.get("Items") or []
            if items and isinstance(items[0], dict):
                return items, [normalize_label(key) for key in items[0].keys()], "jyapi-page-items", {
                    "page_index": page_data.get("PageIndex"),
                    "page_size": page_data.get("PageSize"),
                    "total_count": page_data.get("TotalCount"),
                }
        return [], [], "jyapi-unknown", {}

    retdata = body.get("retdata")
    if isinstance(retdata, dict):
        rows, columns, metadata = extract_payload_rows(retdata, "erp-retdata-dict")
        return rows, columns, "erp-retdata-dict", metadata
    if isinstance(retdata, list) and retdata and isinstance(retdata[0], dict):
        rows, columns, metadata = extract_payload_rows(retdata[0], "erp-retdata-list")
        return rows, columns, "erp-retdata-list", metadata
    return [], [], "unknown", {}


def extract_title_rows(title_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for row_index, row in enumerate(title_rows):
        if not isinstance(row, dict):
            continue
        columns: list[dict[str, str]] = []
        for key, value in row.items():
            if not str(key).startswith("col"):
                continue
            label = normalize_label(value)
            if not label:
                continue
            columns.append({"column": str(key), "label": label})
        if columns:
            groups.append({"row_index": row_index, "columns": columns})
    return groups


def extract_grid_headers(headers: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in headers:
        if not isinstance(item, dict):
            continue
        code = normalize_label(item.get("gcode"))
        label = normalize_label(item.get("gname"))
        parent = normalize_label(item.get("gparentcode"))
        if not code and not label:
            continue
        rows.append({"code": code, "label": label, "parent": parent})
    return rows


def collect_report_audits() -> list[dict[str, Any]]:
    audits: list[dict[str, Any]] = []
    for spec in REPORT_SPECS:
        capture_path = CAPTURE_DIR / f"{spec.capture_name}.json"
        capture_payload = json.loads(capture_path.read_text(encoding="utf-8")) if capture_path.exists() else {}
        request_payload = extract_capture_request(capture_payload, spec.url_keyword) or {}
        response_body = extract_capture_response(capture_payload, spec.url_keyword)
        response_rows, columns, response_shape, response_meta = extract_rows_and_metadata(response_body)
        capture_summary = capture_payload.get("captureSummary") or {}
        request_url = ""
        request_method = ""
        for item in capture_payload.get("requests", []):
            url = str(item.get("url", ""))
            if spec.url_keyword in url:
                request_url = url
                request_method = str(item.get("method") or "POST")
                break
        expected_matches = all(request_payload.get(key) == value for key, value in spec.expected_request.items())
        auto_notes: list[str] = []
        if spec.expected_request and not expected_matches:
            auto_notes.append(
                f"当前抓到的请求参数是 {stringify_payload(request_payload)}，没有满足预期 {stringify_payload(spec.expected_request)}。"
            )
        if not response_body:
            auto_notes.append("当前 capture-cache 没有抓到这个接口的响应体。")
        audit = {
            "display_name": spec.display_name,
            "capture_name": spec.capture_name,
            "status": spec.status,
            "reason": spec.reason,
            "notes": [*spec.notes, *auto_notes],
            "capture_path": str(capture_path.resolve()) if capture_path.exists() else "",
            "image_paths": discover_images(spec.image_prefixes or (spec.display_name,)),
            "url_keyword": spec.url_keyword,
            "request_url": request_url,
            "request_method": request_method or "POST",
            "request_payload": request_payload,
            "expected_request": spec.expected_request,
            "expected_request_matched": expected_matches,
            "capture_quality": capture_summary.get("captureQuality"),
            "report_mode": capture_summary.get("reportMode"),
            "capture_record_count": capture_summary.get("recordCount"),
            "requested_range": capture_summary.get("requestedRange"),
            "request_range": capture_summary.get("requestRange"),
            "range_matched": capture_summary.get("rangeMatched"),
            "response_found": bool(response_body),
            "response_shape": response_shape,
            "row_count": len(response_rows),
            "columns": columns,
            "response_meta": response_meta,
            "sqlite_targets": list(spec.sqlite_targets),
            "sqlite_note": spec.sqlite_note,
        }
        audits.append(audit)
    return audits


def render_summary_table(audits: list[dict[str, Any]]) -> str:
    lines = [
        "| 报表 | 状态 | JSON / 截图结论 | SQLite 落点 |",
        "| --- | --- | --- | --- |",
    ]
    for audit in audits:
        sqlite_text = "、".join(audit["sqlite_targets"]) if audit["sqlite_targets"] else (audit["sqlite_note"] or "未入 SQLite")
        lines.append(
            f"| {audit['display_name']} | {audit['status']} | {audit['reason']} | {sqlite_text} |"
        )
    return "\n".join(lines)


def render_response_meta(response_meta: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    title_rows = response_meta.get("title_rows") or []
    for item in title_rows:
        preview = "，".join(
            f"{column['column']}={column['label']}" for column in item["columns"][:12]
        )
        more = "" if len(item["columns"]) <= 12 else f" 等 {len(item['columns'])} 列"
        lines.append(f"`Title` 第 {item['row_index'] + 1} 行：{preview}{more}")

    grid_header = response_meta.get("grid_header") or []
    if grid_header:
        preview = "，".join(f"{item['code']}={item['label']}" for item in grid_header[:12])
        more = "" if len(grid_header) <= 12 else f" 等 {len(grid_header)} 项"
        lines.append(f"`GridHeader`：{preview}{more}")

    grid_header_list = response_meta.get("grid_header_list") or []
    if grid_header_list:
        preview = "，".join(
            f"{item['code']}={item['label']}" for item in grid_header_list[:16]
        )
        more = "" if len(grid_header_list) <= 16 else f" 等 {len(grid_header_list)} 项"
        lines.append(f"`GridHeaderList`：{preview}{more}")

    columns_list = response_meta.get("columns_list") or []
    if columns_list:
        preview = "，".join(columns_list[:24])
        more = "" if len(columns_list) <= 24 else f" 等 {len(columns_list)} 列"
        lines.append(f"`ColumnsList`：{preview}{more}")
    return lines


def render_markdown(audits: list[dict[str, Any]]) -> str:
    confirmed_count = sum(1 for audit in audits if audit["status"] == "已经")
    suspicious_count = sum(1 for audit in audits if audit["status"] == "高度怀疑")
    lines = [
        "# Yeusoft 截图 vs API 字段核对",
        "",
        f"- 核对时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 已经：{confirmed_count}",
        f"- 高度怀疑：{suspicious_count}",
        "",
        "## 总表",
        "",
        render_summary_table(audits),
        "",
        "## 逐表说明",
        "",
    ]
    for audit in audits:
        lines.extend(
            [
                f"### {audit['display_name']}",
                "",
                f"- 状态：{audit['status']}",
                f"- 结论：{audit['reason']}",
                f"- 接口：`{audit['request_url'] or audit['url_keyword']}`",
                f"- 请求参数：`{stringify_payload(audit['request_payload'])}`",
                f"- capture：`{audit['capture_path'] or '未抓到 capture json'}`",
                f"- 截图：{', '.join(Path(path).name for path in audit['image_paths']) or '未找到截图'}",
                f"- 抓取质量：`{audit['capture_quality'] or 'unknown'}`",
                f"- 响应结构：`{audit['response_shape']}`",
                f"- JSON 行数：`{audit['row_count']}`",
                f"- 字段列表：{', '.join(audit['columns']) if audit['columns'] else '当前没有可用字段列表'}",
                f"- SQLite：{'、'.join(audit['sqlite_targets']) if audit['sqlite_targets'] else (audit['sqlite_note'] or '未入 SQLite')}",
            ]
        )
        extra_lines = render_response_meta(audit["response_meta"])
        if extra_lines:
            lines.append("- 动态列说明：")
            for item in extra_lines:
                lines.append(f"  - {item}")
        if audit["notes"]:
            lines.append("- 备注：")
            for note in audit["notes"]:
                lines.append(f"  - {note}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_embedded_summary(audits: list[dict[str, Any]]) -> str:
    confirmed_count = sum(1 for audit in audits if audit["status"] == "已经")
    suspicious_count = sum(1 for audit in audits if audit["status"] == "高度怀疑")
    lines = [
        SUMMARY_START,
        "## 字段核对状态（自动生成）",
        "",
        f"- 已经：{confirmed_count}",
        f"- 高度怀疑：{suspicious_count}",
        f"- 详细字段说明：`{OUTPUT_MD}`",
        "",
        "> 说明：只有截图和当前 JSON 能 100% 对上的标记为 `已经`；存在缺响应、请求类型不一致、或整屏包含当前 API 未覆盖区域的统一标记为 `高度怀疑`。",
        "",
        render_summary_table(audits),
        "",
        SUMMARY_END,
    ]
    return "\n".join(lines)


def update_report_samples_summary(audits: list[dict[str, Any]]) -> None:
    if not REPORT_SAMPLES_MD.exists():
        return
    content = REPORT_SAMPLES_MD.read_text(encoding="utf-8")
    block = render_embedded_summary(audits)
    if SUMMARY_START in content and SUMMARY_END in content:
        content = re.sub(
            rf"{re.escape(SUMMARY_START)}.*?{re.escape(SUMMARY_END)}",
            block,
            content,
            flags=re.S,
        )
    else:
        content = f"{block}\n\n{content}"
    REPORT_SAMPLES_MD.write_text(content, encoding="utf-8")


def build_outputs() -> dict[str, Any]:
    audits = collect_report_audits()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(audits, ensure_ascii=False, indent=2), encoding="utf-8")
    OUTPUT_MD.write_text(render_markdown(audits), encoding="utf-8")
    update_report_samples_summary(audits)
    confirmed_count = sum(1 for audit in audits if audit["status"] == "已经")
    suspicious_count = sum(1 for audit in audits if audit["status"] == "高度怀疑")
    return {
        "audit_json": str(OUTPUT_JSON.resolve()),
        "audit_markdown": str(OUTPUT_MD.resolve()),
        "report_samples_md": str(REPORT_SAMPLES_MD.resolve()),
        "report_count": len(audits),
        "confirmed_count": confirmed_count,
        "high_suspicion_count": suspicious_count,
    }


def main() -> None:
    print(json.dumps(build_outputs(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
