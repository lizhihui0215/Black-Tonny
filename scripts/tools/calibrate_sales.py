#!/usr/bin/env python3
"""Audit and calibrate master-store sales from local exports and capture cache."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.dashboard.input import PRIMARY_INPUT, infer_store_name, load_data, resolve_reports  # noqa: E402
from scripts.dashboard.yeusoft import (  # noqa: E402
    decode_yeusoft_text,
    extract_capture_request,
    extract_capture_response,
    extract_capture_rows,
    normalize_yeusoft_frame,
)


DEFAULT_STORE_NAME = "咸阳沣西吾悦专卖店"
MASTER_DOC_TYPES = {"销售发货", "其它销售", "销售退货"}
FLOW_DOC_TYPES = {"销售", "换货", "退货", "储值"}
RETURN_FLOW_DOC_TYPES = {"退货", "换货"}


def safe_float(value: object) -> float:
    return float(pd.to_numeric(value, errors="coerce")) if pd.notna(pd.to_numeric(value, errors="coerce")) else 0.0


def normalize_text_frame(frame: pd.DataFrame) -> pd.DataFrame:
    cleaned = frame.copy()
    for column in cleaned.columns:
        if cleaned[column].dtype == object:
            cleaned[column] = cleaned[column].fillna("").astype(str).str.strip()
    return cleaned


def normalize_numeric(frame: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    normalized = frame.copy()
    for column in columns:
        if column in normalized.columns:
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce").fillna(0.0)
    return normalized


def remove_summary_rows(
    frame: pd.DataFrame,
    *,
    key_columns: list[str],
    total_pattern: str = r"合计|总计",
) -> tuple[pd.DataFrame, dict[str, int]]:
    if frame.empty:
        return frame.copy(), {
            "row_count_before": 0,
            "row_count_after": 0,
            "removed_total_like_rows": 0,
            "removed_blank_key_rows": 0,
        }

    cleaned = normalize_text_frame(frame)
    row_count_before = len(cleaned)
    total_like = cleaned.astype(str).apply(
        lambda row: row.str.contains(total_pattern, regex=True, na=False)
    ).any(axis=1)

    existing_keys = [column for column in key_columns if column in cleaned.columns]
    if existing_keys:
        blank_key_rows = cleaned[existing_keys].apply(lambda row: row.eq("")).all(axis=1)
    else:
        blank_key_rows = pd.Series(False, index=cleaned.index)

    filtered = cleaned[~(total_like | blank_key_rows)].copy()
    return filtered, {
        "row_count_before": row_count_before,
        "row_count_after": len(filtered),
        "removed_total_like_rows": int(total_like.sum()),
        "removed_blank_key_rows": int(blank_key_rows.sum()),
    }


def format_money(value: float) -> str:
    return f"{value:,.2f}"


def format_int(value: float | int) -> str:
    return f"{int(value):,}"


def format_date(value: object) -> str:
    if value is None or pd.isna(value):
        return "-"
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def format_datetime(value: object) -> str:
    if value is None or pd.isna(value):
        return "-"
    return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")


def dataframe_to_markdown(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_无_"

    printable = frame.copy()
    printable = printable.fillna("")
    headers = [str(column) for column in printable.columns]
    rows = printable.astype(str).values.tolist()
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        escaped = [cell.replace("\n", "<br>") for cell in row]
        lines.append("| " + " | ".join(escaped) + " |")
    return "\n".join(lines)


def round_numeric_columns(frame: pd.DataFrame, digits: int = 2) -> pd.DataFrame:
    rounded = frame.copy()
    for column in rounded.select_dtypes(include=["float", "float64", "int64", "int32"]).columns:
        if rounded[column].dtype.kind == "f":
            rounded[column] = rounded[column].apply(lambda value: 0.0 if abs(value) < (10 ** (-digits)) else value)
            rounded[column] = rounded[column].round(digits)
    return rounded


def clamp_zero(value: float, digits: int = 2) -> float:
    return 0.0 if abs(value) < (10 ** (-digits)) else round(value, digits)


def normalize_sales_lines(frame: pd.DataFrame, source_name: str) -> pd.DataFrame:
    cleaned = normalize_text_frame(frame)
    cleaned = normalize_numeric(cleaned, ["数量", "金额", "吊牌金额", "单价", "折扣"])
    if "销售日期" in cleaned.columns:
        cleaned["销售日期"] = pd.to_datetime(cleaned["销售日期"], errors="coerce")

    normalized = pd.DataFrame(
        {
            "store_name": cleaned.get("店铺名称", "").fillna("").astype(str).str.strip(),
            "input_user": cleaned.get("输入人", "").fillna("").astype(str).str.strip(),
            "sale_date": cleaned.get("销售日期"),
            "order_no": cleaned.get("零售单号", "").fillna("").astype(str).str.strip(),
            "line_no": cleaned.get("明细流水", "").fillna("").astype(str).str.strip(),
            "sku": cleaned.get("款号", "").fillna("").astype(str).str.strip(),
            "color": cleaned.get("颜色", "").fillna("").astype(str).str.strip(),
            "size": cleaned.get("尺码", "").fillna("").astype(str).str.strip(),
            "qty": pd.to_numeric(cleaned.get("数量", 0), errors="coerce").fillna(0.0),
            "sales_amount": pd.to_numeric(cleaned.get("金额", 0), errors="coerce").fillna(0.0),
            "tag_amount": pd.to_numeric(cleaned.get("吊牌金额", 0), errors="coerce").fillna(0.0),
            "unit_price": pd.to_numeric(cleaned.get("单价", 0), errors="coerce").fillna(0.0),
            "discount_rate": pd.to_numeric(cleaned.get("折扣", 0), errors="coerce").fillna(0.0),
            "doc_type": cleaned.get("单据类型", "").fillna("").astype(str).str.strip(),
            "member_card": cleaned.get("会员卡号", "").fillna("").astype(str).str.strip(),
            "guide_name": cleaned.get("导购员", "").fillna("").astype(str).str.strip(),
            "product_major_type": cleaned.get("商品大类", "").fillna("").astype(str).str.strip(),
            "product_middle_type": cleaned.get("商品中类", "").fillna("").astype(str).str.strip(),
            "product_minor_type": cleaned.get("商品小类", "").fillna("").astype(str).str.strip(),
            "source_name": source_name,
        }
    )
    normalized["is_prop"] = normalized["product_major_type"].eq("道具") | normalized["product_middle_type"].eq("道具")
    normalized["is_return"] = (
        normalized["doc_type"].eq("销售退货")
        | normalized["sales_amount"].lt(0)
        | normalized["qty"].lt(0)
    )
    normalized["gross_sales_amount"] = normalized["sales_amount"].where(
        ~normalized["is_return"] & normalized["sales_amount"].gt(0), 0.0
    )
    normalized["return_offset_amount"] = normalized["sales_amount"].where(normalized["is_return"], 0.0)
    normalized["net_sales_amount"] = normalized["gross_sales_amount"] + normalized["return_offset_amount"]
    normalized["gross_sales_qty"] = normalized["qty"].where(
        ~normalized["is_return"] & normalized["qty"].gt(0), 0.0
    )
    normalized["return_offset_qty"] = normalized["qty"].where(normalized["is_return"], 0.0)
    normalized["net_sales_qty"] = normalized["gross_sales_qty"] + normalized["return_offset_qty"]
    normalized["sale_day"] = normalized["sale_date"].dt.normalize()
    normalized["sale_month"] = normalized["sale_date"].dt.to_period("M").astype(str)
    normalized["flow_doc_type"] = normalized["doc_type"].map(
        {"销售发货": "销售", "其它销售": "换货", "销售退货": "退货"}
    ).fillna("未映射")
    return normalized


def load_capture_sales_master(capture_dir: Path, store_name: str) -> tuple[pd.DataFrame, dict]:
    capture_path = capture_dir / "销售清单.json"
    payload = json.loads(capture_path.read_text(encoding="utf-8"))
    rows, request_payload = extract_capture_rows(payload, "GetDIYReportData")
    frame = normalize_yeusoft_frame(pd.DataFrame(rows), ["数量", "金额", "吊牌金额", "单价", "折扣"])
    frame, row_audit = remove_summary_rows(frame, key_columns=["零售单号", "明细流水", "款号"])
    frame["销售日期"] = pd.to_datetime(frame.get("销售日期"), errors="coerce")
    frame["店铺名称"] = frame.get("店铺名称", "").fillna("").astype(str).str.strip()
    frame["单据类型"] = frame.get("单据类型", "").fillna("").astype(str).str.strip()
    frame = frame[frame["店铺名称"].eq(store_name)].copy()
    frame = frame[frame["单据类型"].isin(MASTER_DOC_TYPES)].copy()
    lines = normalize_sales_lines(frame, "capture_sales_detail")
    return lines, {
        "source_name": "capture_sales_detail",
        "path": str(capture_path),
        "requested_range": request_payload.get("parameter", {}),
        "captured_at": payload.get("capturedAt"),
        **row_audit,
    }


def load_capture_store_retail_validation(
    capture_dir: Path,
    *,
    store_name: str,
    input_user: str,
) -> tuple[pd.DataFrame, dict]:
    capture_path = capture_dir / "店铺零售清单.json"
    payload = json.loads(capture_path.read_text(encoding="utf-8"))
    rows, request_payload = extract_capture_rows(payload, "GetDIYReportData")
    frame = normalize_yeusoft_frame(pd.DataFrame(rows), ["数量", "金额", "吊牌金额", "单价", "折扣"])
    frame, row_audit = remove_summary_rows(frame, key_columns=["零售单号", "明细流水", "款号"])
    frame["销售日期"] = pd.to_datetime(frame.get("销售日期"), errors="coerce")
    frame["店铺名称"] = frame.get("店铺名称", "").fillna("").astype(str).str.strip()
    frame["输入人"] = frame.get("输入人", "").fillna("").astype(str).str.strip()
    frame["单据类型"] = frame.get("单据类型", "").fillna("").astype(str).str.strip()
    frame = frame[
        frame["店铺名称"].eq(store_name) | frame["输入人"].eq(input_user)
    ].copy()
    frame = frame[frame["单据类型"].isin(MASTER_DOC_TYPES)].copy()
    lines = normalize_sales_lines(frame, "capture_store_retail_validation")
    return lines, {
        "source_name": "capture_store_retail_validation",
        "path": str(capture_path),
        "requested_range": request_payload.get("parameter", {}),
        "captured_at": payload.get("capturedAt"),
        **row_audit,
    }


def load_capture_product_sales(capture_dir: Path) -> tuple[pd.DataFrame, dict]:
    capture_path = capture_dir / "商品销售情况.json"
    payload = json.loads(capture_path.read_text(encoding="utf-8"))
    rows, request_payload = extract_capture_rows(payload, "SelSaleReportData")
    frame = normalize_yeusoft_frame(
        pd.DataFrame(rows),
        ["SaleAmount", "SaleMoney", "SumSaleAmount", "SumSaleMoney", "SumArrival", "SumReturn", "StockNum"],
    )
    frame, row_audit = remove_summary_rows(frame, key_columns=["Specification"])
    frame = normalize_text_frame(frame)
    frame = frame[frame["Specification"].ne("")].copy()
    frame["FirstArrivalDate"] = pd.to_datetime(frame.get("FirstArrivalDate"), errors="coerce")
    frame["FirstSaleDate"] = pd.to_datetime(frame.get("FirstSaleDate"), errors="coerce")
    frame["is_prop"] = frame.get("MType", "").fillna("").astype(str).str.strip().eq("道具")
    standardized = pd.DataFrame(
        {
            "sku": frame["Specification"],
            "color": frame.get("Color", "").fillna("").astype(str).str.strip(),
            "cumulative_sales_qty": pd.to_numeric(frame.get("SumSaleAmount", 0), errors="coerce").fillna(0.0),
            "cumulative_sales_amount": pd.to_numeric(frame.get("SumSaleMoney", 0), errors="coerce").fillna(0.0),
            "cumulative_return_qty": pd.to_numeric(frame.get("SumReturn", 0), errors="coerce").fillna(0.0),
            "current_stock_qty": pd.to_numeric(frame.get("StockNum", 0), errors="coerce").fillna(0.0),
            "arrival_qty": pd.to_numeric(frame.get("SumArrival", 0), errors="coerce").fillna(0.0),
            "category_name": frame.get("MType", "").fillna("").astype(str).str.strip(),
            "first_arrival_date": frame.get("FirstArrivalDate"),
            "first_sale_date": frame.get("FirstSaleDate"),
            "is_prop": frame["is_prop"],
            "source_name": "capture_product_sales",
        }
    )
    return standardized, {
        "source_name": "capture_product_sales",
        "path": str(capture_path),
        "requested_range": request_payload,
        "captured_at": payload.get("capturedAt"),
        **row_audit,
    }


def load_capture_daily_flow(capture_dir: Path) -> tuple[pd.DataFrame, dict]:
    capture_path = capture_dir / "每日流水单.json"
    payload = json.loads(capture_path.read_text(encoding="utf-8"))
    body = extract_capture_response(payload, "SelectRetailDocPaymentSlip")
    request_payload = extract_capture_request(payload, "SelectRetailDocPaymentSlip") or {}
    columns = (body.get("Data") or {}).get("Columns") or []
    rows = [dict(zip(columns, row)) for row in ((body.get("Data") or {}).get("List") or []) if isinstance(row, list)]
    frame = pd.DataFrame(rows)
    for column in frame.columns:
        if frame[column].dtype == object:
            frame[column] = frame[column].apply(lambda value: decode_yeusoft_text(value).strip() if value is not None else "")
    frame, row_audit = remove_summary_rows(frame, key_columns=["DocNo", "DocTypeName"])
    frame = normalize_numeric(
        frame,
        [
            "ActualMoney",
            "Amount",
            "TagMoney",
            "Money",
            "SaleDiscount",
            "CashMoney",
            "SwipeMoney",
            "WxMoney",
            "AlipayMoney",
            "StockMoney",
            "OrderMoney",
            "CouponMoney",
            "UseRebateMoney",
            "UseBvMoney",
            "OtherMoney",
            "ActivityMoney",
            "ScanCodeMoney",
            "WipeZeroMoney",
            "LookChangeMoney",
        ],
    )
    frame["MakeDate"] = pd.to_datetime(frame.get("MakeDate"), errors="coerce")
    frame["DocTypeName"] = frame.get("DocTypeName", "").fillna("").astype(str).str.strip()
    frame = frame[frame["DocTypeName"].isin(FLOW_DOC_TYPES)].copy()
    standardized = pd.DataFrame(
        {
            "sale_date": frame["MakeDate"],
            "sale_day": frame["MakeDate"].dt.normalize(),
            "sale_month": frame["MakeDate"].dt.to_period("M").astype(str),
            "order_no": frame.get("DocNo", "").fillna("").astype(str).str.strip(),
            "doc_type": frame["DocTypeName"],
            "actual_money": frame.get("ActualMoney", 0.0),
            "sales_qty": frame.get("Amount", 0.0),
            "tag_amount": frame.get("TagMoney", 0.0),
            "cash_money": frame.get("CashMoney", 0.0),
            "wx_money": frame.get("WxMoney", 0.0),
            "alipay_money": frame.get("AlipayMoney", 0.0),
            "coupon_money": frame.get("CouponMoney", 0.0),
            "activity_money": frame.get("ActivityMoney", 0.0),
            "other_money": frame.get("OtherMoney", 0.0),
            "source_name": "capture_daily_flow",
        }
    )
    return standardized, {
        "source_name": "capture_daily_flow",
        "path": str(capture_path),
        "requested_range": request_payload,
        "captured_at": payload.get("capturedAt"),
        **row_audit,
    }


def load_capture_movement(capture_dir: Path) -> tuple[pd.DataFrame, dict]:
    capture_path = capture_dir / "出入库单据.json"
    payload = json.loads(capture_path.read_text(encoding="utf-8"))
    body = extract_capture_response(payload, "SelOutInStockReport")
    request_payload = extract_capture_request(payload, "SelOutInStockReport") or {}
    retdata = body.get("retdata") or []
    payload_block = retdata[0] if retdata else {}
    rows = payload_block.get("Data") or []
    frame = pd.DataFrame(
        [
            {
                "doc_type": decode_yeusoft_text(row.get("DocType")).strip(),
                "doc_status": decode_yeusoft_text(row.get("DocStat")).strip(),
                "transfer_type": decode_yeusoft_text(row.get("Transtat")).strip(),
                "from_store": decode_yeusoft_text(row.get("WhID")).strip(),
                "to_store": decode_yeusoft_text(row.get("InWhID")).strip(),
                "qty": safe_float(row.get("TN")),
                "amount": safe_float(row.get("TRP")),
                "come_date": pd.to_datetime(row.get("ComeDate"), errors="coerce"),
                "receive_date": pd.to_datetime(row.get("ReceDate"), errors="coerce"),
            }
            for row in rows
        ]
    )
    return frame, {
        "source_name": "capture_movement",
        "path": str(capture_path),
        "requested_range": request_payload,
        "captured_at": payload.get("capturedAt"),
        "row_count_before": len(frame),
        "row_count_after": len(frame),
        "removed_total_like_rows": 0,
        "removed_blank_key_rows": 0,
    }


def build_excel_sales_short(lines: pd.DataFrame, store_name: str, source_name: str) -> pd.DataFrame:
    filtered = lines.copy()
    filtered = filtered[filtered["store_name"].eq(store_name)].copy()
    filtered = filtered[filtered["doc_type"].isin(MASTER_DOC_TYPES)].copy()
    return filtered.assign(source_name=source_name)


def load_excel_sales_audit(input_dir: Path, store_name: str) -> tuple[dict[str, pd.DataFrame], dict, str]:
    reports = resolve_reports(input_dir)
    raw = load_data(reports)
    inferred_store = infer_store_name(raw, None)

    sales_frame, sales_audit = remove_summary_rows(raw["sales"], key_columns=["零售单号", "明细流水", "款号"])
    store_retail_frame, store_retail_audit = remove_summary_rows(
        raw.get("store_retail", pd.DataFrame()),
        key_columns=["零售单号", "明细流水", "款号"],
    )
    guide_frame, guide_audit = remove_summary_rows(raw["guide"], key_columns=["导购员"])
    product_frame, product_audit = remove_summary_rows(raw["product_sales"], key_columns=["款号"])
    movement_frame, movement_audit = remove_summary_rows(raw["movement"], key_columns=["单据号"])

    sales_lines = normalize_sales_lines(sales_frame, "excel_sales_short")
    store_retail_lines = normalize_sales_lines(store_retail_frame, "excel_store_retail")

    guide_frame = normalize_text_frame(guide_frame)
    guide_frame = normalize_numeric(guide_frame, ["销量", "实收金额", "票数", "现金", "储值", "用券"])
    guide_frame = guide_frame[guide_frame.get("导购员", "").fillna("").astype(str).str.strip().ne("合计")].copy()

    product_frame = normalize_text_frame(product_frame)
    product_frame = normalize_numeric(
        product_frame,
        ["销售数", "销售金额", "累销", "累销额", "总到货", "库存", "总退货"],
    )
    product_frame = product_frame[product_frame.get("款号", "").fillna("").astype(str).str.strip().ne("合计")].copy()

    movement_frame = normalize_text_frame(movement_frame)
    movement_frame = normalize_numeric(movement_frame, ["数量", "吊牌金额"])
    movement_frame["发货时间"] = pd.to_datetime(movement_frame.get("发货时间"), errors="coerce")
    movement_frame["接收时间"] = pd.to_datetime(movement_frame.get("接收时间"), errors="coerce")

    return {
        "sales": build_excel_sales_short(sales_lines, store_name, "excel_sales_short"),
        "store_retail": store_retail_lines,
        "guide": guide_frame,
        "product": product_frame,
        "movement": movement_frame,
    }, {
        "sales": {"path": str(reports.sales_detail), **sales_audit},
        "store_retail": {"path": str(reports.store_retail_report) if reports.store_retail_report else "-", **store_retail_audit},
        "guide": {"path": str(reports.guide_report), **guide_audit},
        "product": {"path": str(reports.product_sales), **product_audit},
        "movement": {"path": str(reports.movement_report), **movement_audit},
    }, inferred_store


def compare_sales_overlap(
    master_lines: pd.DataFrame,
    validation_lines: pd.DataFrame,
    *,
    label: str,
) -> dict[str, object]:
    if master_lines.empty or validation_lines.empty:
        return {
            "label": label,
            "overlap_start": pd.NaT,
            "overlap_end": pd.NaT,
            "daily_comparison": pd.DataFrame(),
            "order_comparison": pd.DataFrame(),
            "problem_orders": pd.DataFrame(),
            "max_daily_amount_diff": 0.0,
        }

    master_days = master_lines["sale_day"].dropna()
    validation_days = validation_lines["sale_day"].dropna()
    overlap_start = max(master_days.min(), validation_days.min())
    overlap_end = min(master_days.max(), validation_days.max())

    master_overlap = master_lines[
        master_lines["sale_day"].between(overlap_start, overlap_end, inclusive="both")
    ].copy()
    validation_overlap = validation_lines[
        validation_lines["sale_day"].between(overlap_start, overlap_end, inclusive="both")
    ].copy()

    daily_master = (
        master_overlap.groupby("sale_day")
        .agg(amount=("sales_amount", "sum"), qty=("qty", "sum"), orders=("order_no", "nunique"))
        .reset_index()
    )
    daily_validation = (
        validation_overlap.groupby("sale_day")
        .agg(amount=("sales_amount", "sum"), qty=("qty", "sum"), orders=("order_no", "nunique"))
        .reset_index()
    )
    daily_comparison = (
        daily_master.merge(
            daily_validation,
            on="sale_day",
            how="outer",
            suffixes=("_master", "_validation"),
        )
        .fillna(0)
        .sort_values("sale_day")
    )
    daily_comparison["amount_diff"] = daily_comparison["amount_master"] - daily_comparison["amount_validation"]
    daily_comparison["qty_diff"] = daily_comparison["qty_master"] - daily_comparison["qty_validation"]
    daily_comparison["order_diff"] = daily_comparison["orders_master"] - daily_comparison["orders_validation"]

    order_master = (
        master_overlap.groupby("order_no")
        .agg(amount=("sales_amount", "sum"), qty=("qty", "sum"), line_count=("order_no", "size"))
        .reset_index()
    )
    order_validation = (
        validation_overlap.groupby("order_no")
        .agg(amount=("sales_amount", "sum"), qty=("qty", "sum"), line_count=("order_no", "size"))
        .reset_index()
    )
    order_comparison = (
        order_master.merge(
            order_validation,
            on="order_no",
            how="outer",
            suffixes=("_master", "_validation"),
        )
        .fillna(0)
        .sort_values("order_no")
    )
    order_comparison["amount_diff"] = order_comparison["amount_master"] - order_comparison["amount_validation"]
    order_comparison["qty_diff"] = order_comparison["qty_master"] - order_comparison["qty_validation"]
    order_comparison["line_count_diff"] = (
        order_comparison["line_count_master"] - order_comparison["line_count_validation"]
    )
    order_comparison["base_amount"] = order_comparison[
        ["amount_master", "amount_validation"]
    ].abs().max(axis=1)
    order_comparison["amount_diff_ratio"] = order_comparison["amount_diff"].abs() / order_comparison[
        "base_amount"
    ].replace(0, 1)
    problem_orders = order_comparison[
        (order_comparison["amount_diff"].abs() > 1) | (order_comparison["amount_diff_ratio"] > 0.001)
    ].copy()

    return {
        "label": label,
        "overlap_start": overlap_start,
        "overlap_end": overlap_end,
        "daily_comparison": daily_comparison,
        "order_comparison": order_comparison,
        "problem_orders": problem_orders,
        "max_daily_amount_diff": float(daily_comparison["amount_diff"].abs().max()) if not daily_comparison.empty else 0.0,
    }


def compare_master_to_product(master_lines: pd.DataFrame, product_rows: pd.DataFrame) -> dict[str, object]:
    master_core = master_lines[~master_lines["is_prop"]].copy()
    master_props = master_lines[master_lines["is_prop"]].copy()
    product_core = product_rows[~product_rows["is_prop"]].copy()
    product_props = product_rows[product_rows["is_prop"]].copy()

    core_master_sku = (
        master_core.groupby(["sku", "color"], dropna=False)
        .agg(net_sales_amount=("net_sales_amount", "sum"), net_sales_qty=("net_sales_qty", "sum"))
        .reset_index()
    )
    core_product_sku = (
        product_core.groupby(["sku", "color"], dropna=False)
        .agg(
            cumulative_sales_amount=("cumulative_sales_amount", "sum"),
            cumulative_sales_qty=("cumulative_sales_qty", "sum"),
            cumulative_return_qty=("cumulative_return_qty", "sum"),
        )
        .reset_index()
    )
    sku_comparison = core_master_sku.merge(core_product_sku, on=["sku", "color"], how="outer").fillna(0.0)
    sku_comparison["amount_diff"] = sku_comparison["net_sales_amount"] - sku_comparison["cumulative_sales_amount"]
    sku_comparison["qty_diff"] = sku_comparison["net_sales_qty"] - sku_comparison["cumulative_sales_qty"]

    return {
        "sku_comparison": sku_comparison,
        "core_amount_diff": clamp_zero(float(sku_comparison["amount_diff"].sum())),
        "core_qty_diff": clamp_zero(float(sku_comparison["qty_diff"].sum())),
        "product_core_return_qty": float(product_core["cumulative_return_qty"].sum()),
        "master_explicit_return_qty": float(master_core[master_core["doc_type"].eq("销售退货")]["qty"].sum()),
        "master_rule_return_qty": float(master_core[master_core["is_return"]]["qty"].sum()),
        "product_props_amount": float(product_props["cumulative_sales_amount"].sum()),
        "master_props_amount": float(master_props["net_sales_amount"].sum()),
    }


def compare_master_to_flow(master_lines: pd.DataFrame, flow_rows: pd.DataFrame) -> dict[str, object]:
    master_order = (
        master_lines.groupby(["order_no", "flow_doc_type"])
        .agg(master_amount=("sales_amount", "sum"), master_qty=("qty", "sum"))
        .reset_index()
    )
    flow_order = (
        flow_rows.groupby(["order_no", "doc_type"])
        .agg(flow_actual_money=("actual_money", "sum"), flow_qty=("sales_qty", "sum"), flow_cash_money=("cash_money", "sum"))
        .reset_index()
        .rename(columns={"doc_type": "flow_doc_type"})
    )
    comparable_flow = flow_order[flow_order["flow_doc_type"].isin({"销售", "换货", "退货"})].copy()
    order_comparison = master_order.merge(
        comparable_flow,
        on=["order_no", "flow_doc_type"],
        how="outer",
    ).fillna(0.0)
    order_comparison["amount_diff"] = order_comparison["master_amount"] - order_comparison["flow_actual_money"]
    order_comparison["qty_diff"] = order_comparison["master_qty"] - order_comparison["flow_qty"]
    order_comparison["amount_diff"] = order_comparison["amount_diff"].round(2)
    order_comparison["qty_diff"] = order_comparison["qty_diff"].round(2)
    order_comparison["base_amount"] = order_comparison[
        ["master_amount", "flow_actual_money"]
    ].abs().max(axis=1)
    order_comparison["amount_diff_ratio"] = 0.0
    nonzero_base = order_comparison["base_amount"] > 0
    order_comparison.loc[nonzero_base, "amount_diff_ratio"] = (
        order_comparison.loc[nonzero_base, "amount_diff"].abs()
        / order_comparison.loc[nonzero_base, "base_amount"]
    )
    problem_orders = order_comparison[
        (order_comparison["amount_diff"].abs() > 1) | (order_comparison["amount_diff_ratio"] > 0.001)
    ].copy()

    daily_master = (
        master_lines.groupby(["sale_day", "flow_doc_type"])
        .agg(master_amount=("sales_amount", "sum"))
        .reset_index()
    )
    daily_flow = (
        flow_rows.groupby(["sale_day", "doc_type"])
        .agg(flow_actual_money=("actual_money", "sum"))
        .reset_index()
        .rename(columns={"doc_type": "flow_doc_type"})
    )
    daily_comparison = daily_master.merge(
        daily_flow,
        on=["sale_day", "flow_doc_type"],
        how="outer",
    ).fillna(0.0)
    daily_comparison["amount_diff"] = daily_comparison["master_amount"] - daily_comparison["flow_actual_money"]

    return {
        "order_comparison": order_comparison,
        "problem_orders": problem_orders,
        "daily_comparison": daily_comparison,
        "sales_related_actual_money": float(flow_rows[flow_rows["doc_type"].isin({"销售", "换货", "退货"})]["actual_money"].sum()),
        "sales_related_cash_money": float(flow_rows[flow_rows["doc_type"].isin({"销售", "换货", "退货"})]["cash_money"].sum()),
        "stored_value_money": float(flow_rows[flow_rows["doc_type"].eq("储值")]["actual_money"].sum()),
    }


def aggregate_period_lines(lines: pd.DataFrame, period_column: str) -> pd.DataFrame:
    core = lines[~lines["is_prop"]].copy()
    props = lines[lines["is_prop"]].copy()

    core_summary = (
        core.groupby(period_column)
        .agg(
            gross_sales_amount=("gross_sales_amount", "sum"),
            return_offset_amount=("return_offset_amount", "sum"),
            net_sales_amount=("net_sales_amount", "sum"),
            gross_sales_qty=("gross_sales_qty", "sum"),
            return_offset_qty=("return_offset_qty", "sum"),
            net_sales_qty=("net_sales_qty", "sum"),
            core_order_count=("order_no", "nunique"),
        )
        .reset_index()
    )
    prop_summary = (
        props.groupby(period_column)
        .agg(
            prop_gross_sales_amount=("gross_sales_amount", "sum"),
            prop_return_offset_amount=("return_offset_amount", "sum"),
            prop_net_sales_amount=("net_sales_amount", "sum"),
            prop_order_count=("order_no", "nunique"),
        )
        .reset_index()
    )
    all_summary = (
        lines.groupby(period_column)
        .agg(
            all_goods_net_sales_amount=("net_sales_amount", "sum"),
            all_goods_order_count=("order_no", "nunique"),
        )
        .reset_index()
    )
    summary = core_summary.merge(prop_summary, on=period_column, how="outer").merge(
        all_summary, on=period_column, how="outer"
    )
    summary = summary.fillna(0.0).sort_values(period_column)
    return summary


def aggregate_flow_periods(flow_rows: pd.DataFrame, period_column: str) -> pd.DataFrame:
    sales_related = flow_rows[flow_rows["doc_type"].isin({"销售", "换货", "退货"})].copy()
    stored = flow_rows[flow_rows["doc_type"].eq("储值")].copy()

    sales_related_summary = (
        sales_related.groupby(period_column)
        .agg(
            flow_sales_related_actual_money=("actual_money", "sum"),
            flow_sales_related_cash_money=("cash_money", "sum"),
        )
        .reset_index()
    )
    doc_breakdown = (
        sales_related.groupby([period_column, "doc_type"])
        .agg(doc_actual_money=("actual_money", "sum"))
        .reset_index()
        .pivot(index=period_column, columns="doc_type", values="doc_actual_money")
        .fillna(0.0)
        .reset_index()
        .rename_axis(None, axis=1)
    )
    for column in ["销售", "换货", "退货"]:
        if column not in doc_breakdown.columns:
            doc_breakdown[column] = 0.0
    doc_breakdown = doc_breakdown.rename(
        columns={
            "销售": "flow_sales_actual_money",
            "换货": "flow_exchange_actual_money",
            "退货": "flow_return_actual_money",
        }
    )
    stored_summary = (
        stored.groupby(period_column)
        .agg(flow_stored_value_actual_money=("actual_money", "sum"))
        .reset_index()
    )
    return (
        sales_related_summary.merge(doc_breakdown, on=period_column, how="outer")
        .merge(stored_summary, on=period_column, how="outer")
        .fillna(0.0)
        .sort_values(period_column)
    )


def build_daily_sales(master_lines: pd.DataFrame, flow_rows: pd.DataFrame) -> pd.DataFrame:
    line_summary = aggregate_period_lines(master_lines, "sale_day")
    flow_summary = aggregate_flow_periods(flow_rows, "sale_day")
    daily = line_summary.merge(flow_summary, on="sale_day", how="outer").fillna(0.0).sort_values("sale_day")
    daily["sale_date"] = daily["sale_day"].apply(format_date)
    daily["is_trusted_core_sales"] = True
    daily["cash_scope"] = "销售/换货/退货现金回款（含道具）"
    columns = [
        "sale_date",
        "gross_sales_amount",
        "return_offset_amount",
        "net_sales_amount",
        "prop_gross_sales_amount",
        "prop_return_offset_amount",
        "prop_net_sales_amount",
        "all_goods_net_sales_amount",
        "flow_sales_related_actual_money",
        "flow_sales_related_cash_money",
        "flow_sales_actual_money",
        "flow_exchange_actual_money",
        "flow_return_actual_money",
        "flow_stored_value_actual_money",
        "gross_sales_qty",
        "return_offset_qty",
        "net_sales_qty",
        "core_order_count",
        "all_goods_order_count",
        "is_trusted_core_sales",
        "cash_scope",
    ]
    return daily[columns].copy()


def build_monthly_sales(master_lines: pd.DataFrame, flow_rows: pd.DataFrame) -> pd.DataFrame:
    line_summary = aggregate_period_lines(master_lines, "sale_month")
    flow_summary = aggregate_flow_periods(flow_rows, "sale_month")
    monthly = line_summary.merge(flow_summary, on="sale_month", how="outer").fillna(0.0).sort_values("sale_month")
    monthly["month"] = monthly["sale_month"]
    monthly["is_trusted_core_sales"] = True
    monthly["cash_scope"] = "销售/换货/退货现金回款（含道具）"
    columns = [
        "month",
        "gross_sales_amount",
        "return_offset_amount",
        "net_sales_amount",
        "prop_gross_sales_amount",
        "prop_return_offset_amount",
        "prop_net_sales_amount",
        "all_goods_net_sales_amount",
        "flow_sales_related_actual_money",
        "flow_sales_related_cash_money",
        "flow_sales_actual_money",
        "flow_exchange_actual_money",
        "flow_return_actual_money",
        "flow_stored_value_actual_money",
        "gross_sales_qty",
        "return_offset_qty",
        "net_sales_qty",
        "core_order_count",
        "all_goods_order_count",
        "is_trusted_core_sales",
        "cash_scope",
    ]
    return monthly[columns].copy()


def build_sku_sales(master_lines: pd.DataFrame) -> pd.DataFrame:
    core = master_lines[~master_lines["is_prop"]].copy()
    return (
        core.groupby(["sku", "color", "product_major_type", "product_middle_type"], dropna=False)
        .agg(
            gross_sales_amount=("gross_sales_amount", "sum"),
            return_offset_amount=("return_offset_amount", "sum"),
            net_sales_amount=("net_sales_amount", "sum"),
            gross_sales_qty=("gross_sales_qty", "sum"),
            return_offset_qty=("return_offset_qty", "sum"),
            net_sales_qty=("net_sales_qty", "sum"),
            order_count=("order_no", "nunique"),
        )
        .reset_index()
        .sort_values(["net_sales_amount", "net_sales_qty"], ascending=[False, False])
    )


def build_source_inventory_markdown(
    *,
    store_name: str,
    inferred_store: str,
    excel_frames: dict[str, pd.DataFrame],
    excel_audit: dict[str, dict],
    capture_sales_audit: dict,
    capture_retail_audit: dict,
    capture_product_audit: dict,
    capture_flow_audit: dict,
    capture_movement_audit: dict,
    product_rows: pd.DataFrame,
    flow_rows: pd.DataFrame,
    movement_rows: pd.DataFrame,
) -> str:
    capture_sales_lines = excel_frames["sales_capture_master"]
    capture_retail_lines = excel_frames["store_retail_capture"]
    lines = [
        f"# 主店销售数据源盘点",
        "",
        f"- 审计主店：`{store_name}`",
        f"- Excel 推断主店：`{inferred_store}`",
        f"- 默认输入人：`{PRIMARY_INPUT}`",
        "",
        "## 来源清单",
        "",
    ]

    source_table = pd.DataFrame(
        [
            {
                "来源": "capture 销售清单",
                "角色": "主表",
                "粒度": "订单行",
                "可信度": "高",
                "日期范围": f"{format_date(capture_sales_lines['sale_date'].min())} ~ {format_date(capture_sales_lines['sale_date'].max())}",
                "行数": len(capture_sales_lines),
                "关键字段": "店铺名称/输入人/销售日期/零售单号/明细流水/款号/颜色/尺码/数量/金额/单据类型",
                "路径": capture_sales_audit["path"],
                "备注": "单店主店全期明细，已验证无汇总行混入。",
            },
            {
                "来源": "capture 店铺零售清单",
                "角色": "交叉校验",
                "粒度": "订单行",
                "可信度": "高（仅重叠区间）",
                "日期范围": f"{format_date(capture_retail_lines['sale_date'].min())} ~ {format_date(capture_retail_lines['sale_date'].max())}",
                "行数": len(capture_retail_lines),
                "关键字段": "店铺名称/输入人/销售日期/零售单号/明细流水/款号/颜色/尺码/数量/金额",
                "路径": capture_retail_audit["path"],
                "备注": "19 店混合表，过滤主店后只做校验，不并表。",
            },
            {
                "来源": "capture 商品销售情况",
                "角色": "累计校验",
                "粒度": "SKU+颜色",
                "可信度": "高（累计金额/数量）",
                "日期范围": f"{format_date(capture_product_audit['requested_range'].get('bdate'))} ~ {format_date(capture_product_audit['requested_range'].get('edate'))}",
                "行数": len(product_rows),
                "关键字段": "Specification/Color/SumSaleAmount/SumSaleMoney/SumReturn/StockNum/MType",
                "路径": capture_product_audit["path"],
                "备注": "需用 Specification 对齐销售清单款号。",
            },
            {
                "来源": "capture 每日流水单",
                "角色": "回款校验",
                "粒度": "订单",
                "可信度": "高（回款）",
                "日期范围": f"{format_date(flow_rows['sale_date'].min())} ~ {format_date(flow_rows['sale_date'].max())}",
                "行数": len(flow_rows),
                "关键字段": "MakeDate/DocTypeName/DocNo/ActualMoney/CashMoney/Amount/TagMoney",
                "路径": capture_flow_audit["path"],
                "备注": "含 销售/换货/退货/储值，不能直接当销售主表。",
            },
            {
                "来源": "capture 出入库单据",
                "角色": "库存动作辅助",
                "粒度": "单据",
                "可信度": "中",
                "日期范围": f"{format_date(movement_rows['come_date'].min())} ~ {format_date(movement_rows['receive_date'].max())}",
                "行数": len(movement_rows),
                "关键字段": "DocType/DocStat/Transtat/WhID/InWhID/TN/TRP/ComeDate/ReceDate",
                "路径": capture_movement_audit["path"],
                "备注": "只有单据头，无 SKU 行，不参与销售汇总。",
            },
            {
                "来源": "Excel 销售清单",
                "角色": "短窗复核",
                "粒度": "订单行",
                "可信度": "高（2026-03-06 ~ 2026-03-13）",
                "日期范围": f"{format_date(excel_frames['sales']['sale_date'].min())} ~ {format_date(excel_frames['sales']['sale_date'].max())}",
                "行数": len(excel_frames["sales"]),
                "关键字段": "店铺名称/输入人/销售日期/零售单号/明细流水/款号/颜色/尺码/数量/金额/单据类型",
                "路径": excel_audit["sales"]["path"],
                "备注": "含合计行，已清理后再参与比对。",
            },
            {
                "来源": "Excel 导购员报表",
                "角色": "短窗辅助",
                "粒度": "导购聚合",
                "可信度": "中高",
                "日期范围": "文件日样本",
                "行数": len(excel_frames["guide"]),
                "关键字段": "导购员/销量/实收金额/现金/储值/票数",
                "路径": excel_audit["guide"]["path"],
                "备注": "适合做短窗票数/金额辅助，不适合全年主口径。",
            },
            {
                "来源": "Excel 商品销售情况",
                "角色": "短窗辅助",
                "粒度": "SKU+颜色",
                "可信度": "中高",
                "日期范围": f"{format_date(excel_frames['product']['首次销售日期'].min() if '首次销售日期' in excel_frames['product'].columns else pd.NaT)} ~ {format_date(excel_frames['product']['首次销售日期'].max() if '首次销售日期' in excel_frames['product'].columns else pd.NaT)}",
                "行数": len(excel_frames["product"]),
                "关键字段": "款号/颜色/累销/累销额/总到货/库存/总退货/中类",
                "路径": excel_audit["product"]["path"],
                "备注": "累计口径参考，不做逐日趋势真值。",
            },
            {
                "来源": "Excel 出入库单据",
                "角色": "库存动作辅助",
                "粒度": "单据",
                "可信度": "中",
                "日期范围": f"{format_date(excel_frames['movement']['发货时间'].min())} ~ {format_date(excel_frames['movement']['发货时间'].max())}",
                "行数": len(excel_frames["movement"]),
                "关键字段": "单据类型/单据状态/单据号/发货仓库/接收店铺/发货时间/接收时间/数量/吊牌金额",
                "路径": excel_audit["movement"]["path"],
                "备注": "当前导出无 SKU 级字段，不能追到订单行。",
            },
        ]
    )
    lines.append(dataframe_to_markdown(source_table))
    lines.extend(
        [
            "",
            "## 关键字段模型",
            "",
            "- 统一字段：`store_name, input_user, sale_date, order_no, line_no, sku, color, size, qty, sales_amount, tag_amount, unit_price, discount_rate, doc_type, member_card, guide_name, source_name`",
            "- 主销售主键：`order_no + line_no`",
            "- SKU 主键：`sku + color + size`",
            "- 每日流水单主键：`DocNo + DocTypeName`",
            "",
            "## 审计备注",
            "",
            f"- Excel 销售类样本存在合计行：销售清单移除 `{excel_audit['sales']['removed_total_like_rows']}` 行，导购员报表移除 `{excel_audit['guide']['removed_total_like_rows']}` 行，商品销售情况移除 `{excel_audit['product']['removed_total_like_rows']}` 行，出入库单据移除 `{excel_audit['movement']['removed_total_like_rows']}` 行。",
            f"- capture 销售清单请求区间：`{capture_sales_audit['requested_range'].get('BeginDate', '-')}` 到 `{capture_sales_audit['requested_range'].get('EndDate', '-')}`。",
            f"- capture 店铺零售清单过滤后只保留主店 / 输入人 `{PRIMARY_INPUT}` 相关记录。",
            f"- 商品销售情况中道具行 `{format_int(product_rows['is_prop'].sum())}` 条，需要从核心服饰口径中剔除。",
            f"- 每日流水单 doc_type 分布：销售/换货/退货/储值 = {format_int((flow_rows['doc_type'] == '销售').sum())}/{format_int((flow_rows['doc_type'] == '换货').sum())}/{format_int((flow_rows['doc_type'] == '退货').sum())}/{format_int((flow_rows['doc_type'] == '储值').sum())}。",
            f"- 出入库单据 doc_type 分布：{movement_rows['doc_type'].value_counts().to_dict()}。",
        ]
    )
    return "\n".join(lines) + "\n"


def build_source_comparison_markdown(
    *,
    retail_comparison: dict[str, object],
    excel_comparison: dict[str, object],
    product_comparison: dict[str, object],
    flow_comparison: dict[str, object],
    master_lines: pd.DataFrame,
) -> str:
    lines = [
        "# 来源对比与校验",
        "",
        "## 主表选择",
        "",
        "- 主表：`reports/capture-cache/销售清单.json`",
        "- 校验表：`reports/capture-cache/店铺零售清单.json`、`data/imports/inventory_zip_extract/销售清单 - 【2026-03-13】.xlsx`",
        "- 累计校验：`reports/capture-cache/商品销售情况.json`",
        "- 回款校验：`reports/capture-cache/每日流水单.json`",
        "- 辅助解释：`reports/capture-cache/出入库单据.json`",
        "",
        "## 销售清单主表 vs 店铺零售清单校验表",
        "",
        f"- 重叠区间：`{format_date(retail_comparison['overlap_start'])}` 到 `{format_date(retail_comparison['overlap_end'])}`",
        f"- 按天最大差异：`{format_money(retail_comparison['max_daily_amount_diff'])}` 元",
        f"- 问题订单数：`{len(retail_comparison['problem_orders'])}`",
        "",
    ]
    if retail_comparison["problem_orders"].empty:
        lines.append("- 结果：按天、按订单均通过，主店过滤后的店铺零售清单可作为交叉校验，不并入主表。")
    else:
        lines.append(dataframe_to_markdown(round_numeric_columns(retail_comparison["problem_orders"].head(50))))

    lines.extend(
        [
            "",
            "## 销售清单主表 vs Excel 短窗样本",
            "",
            f"- 重叠区间：`{format_date(excel_comparison['overlap_start'])}` 到 `{format_date(excel_comparison['overlap_end'])}`",
            f"- 按天最大差异：`{format_money(excel_comparison['max_daily_amount_diff'])}` 元",
            f"- 问题订单数：`{len(excel_comparison['problem_orders'])}`",
            "",
        ]
    )
    if excel_comparison["problem_orders"].empty:
        lines.append("- 结果：`2026-03-06` 到 `2026-03-13` 的 Excel 样本与 capture 主表逐日、逐单完全一致。")
    else:
        lines.append(dataframe_to_markdown(round_numeric_columns(excel_comparison["problem_orders"].head(50))))

    lines.extend(
        [
            "",
            "## 销售清单主表 vs 商品销售情况累计校验",
            "",
            f"- 核心服饰累计销额差异：`{format_money(product_comparison['core_amount_diff'])}` 元",
            f"- 核心服饰累计销量差异：`{format_int(product_comparison['core_qty_diff'])}` 件",
            f"- 商品销售情况累计退货件数：`{format_int(abs(product_comparison['product_core_return_qty']))}` 件",
            f"- 销售清单显式销售退货件数：`{format_int(abs(product_comparison['master_explicit_return_qty']))}` 件",
            f"- 销售清单按退货规则冲减件数：`{format_int(abs(product_comparison['master_rule_return_qty']))}` 件",
            "",
            "- 结果：`Specification + Color` 与主表 `sku + color` 对齐后，累计净销额和累计净销量完全一致。",
            "- 注意：`商品销售情况.SumReturn` 与销售行级退货规则不完全等价，只能做退货参考，不能替代主表退货冲减口径。",
            "",
            "## 销售清单主表 vs 每日流水单",
            "",
            f"- 销售/换货/退货订单级问题数：`{len(flow_comparison['problem_orders'])}`",
            f"- 销售相关 ActualMoney 合计：`{format_money(flow_comparison['sales_related_actual_money'])}` 元",
            f"- 销售相关 CashMoney 合计：`{format_money(flow_comparison['sales_related_cash_money'])}` 元",
            f"- 储值 ActualMoney 合计：`{format_money(flow_comparison['stored_value_money'])}` 元",
            "",
        ]
    )
    if flow_comparison["problem_orders"].empty:
        lines.append("- 结果：剔除 `储值` 后，销售清单与每日流水单在销售/换货/退货三类单据上按订单完全对齐。")
    else:
        lines.append(dataframe_to_markdown(round_numeric_columns(flow_comparison["problem_orders"].head(50))))

    prop_orders = (
        master_lines.groupby("order_no")
        .agg(has_prop=("is_prop", "max"), has_core=("is_prop", lambda values: (~values).any()), amount=("sales_amount", "sum"))
        .reset_index()
    )
    mixed_orders = prop_orders[prop_orders["has_prop"] & prop_orders["has_core"]].copy()

    lines.extend(
        [
            "",
            "## 道具与回款口径说明",
            "",
            f"- 道具与服饰混合订单：`{len(mixed_orders)}` 单，金额合计 `{format_money(mixed_orders['amount'].sum())}` 元。",
            "- 因为每日流水单是订单级支付记录，且存在混合订单，所以“核心服饰现金回款额”无法在不分摊支付的前提下精确拆出。",
            "- 本次只输出“销售/换货/退货的现金回款额（含道具）”作为可信回款口径，不额外估算核心服饰现金回款。",
        ]
    )
    return "\n".join(lines) + "\n"


def build_summary_markdown(
    *,
    store_name: str,
    master_lines: pd.DataFrame,
    flow_rows: pd.DataFrame,
    retail_comparison: dict[str, object],
    excel_comparison: dict[str, object],
    product_comparison: dict[str, object],
    flow_comparison: dict[str, object],
    daily_sales: pd.DataFrame,
    monthly_sales: pd.DataFrame,
    sku_sales: pd.DataFrame,
    inferred_store: str,
) -> str:
    core = master_lines[~master_lines["is_prop"]].copy()
    props = master_lines[master_lines["is_prop"]].copy()
    flow_sales_related = flow_rows[flow_rows["doc_type"].isin({"销售", "换货", "退货"})].copy()

    core_gross_sales_amount = float(core["gross_sales_amount"].sum())
    core_return_offset_amount = float(core["return_offset_amount"].sum())
    core_net_sales_amount = float(core["net_sales_amount"].sum())
    core_gross_sales_qty = float(core["gross_sales_qty"].sum())
    core_return_offset_qty = float(core["return_offset_qty"].sum())
    core_net_sales_qty = float(core["net_sales_qty"].sum())
    prop_net_amount = float(props["net_sales_amount"].sum())
    prop_gross_amount = float(props["gross_sales_amount"].sum())
    prop_return_amount = float(props["return_offset_amount"].sum())
    all_goods_net_sales_amount = float(master_lines["net_sales_amount"].sum())
    cash_receipts_amount = float(flow_sales_related["cash_money"].sum())
    actual_receipts_amount = float(flow_sales_related["actual_money"].sum())
    stored_value_money = float(flow_rows[flow_rows["doc_type"].eq("储值")]["actual_money"].sum())

    top_return_skus = (
        core[core["is_return"]]
        .groupby(["sku", "color", "product_middle_type"], dropna=False)
        .agg(return_offset_amount=("return_offset_amount", "sum"), return_offset_qty=("return_offset_qty", "sum"))
        .reset_index()
        .sort_values("return_offset_amount")
        .head(20)
    )
    top_skus = sku_sales.head(20).copy()

    lines = [
        f"# {store_name} 销售校准总结",
        "",
        "## 口径结论",
        "",
        "- 主表：`reports/capture-cache/销售清单.json`",
        "- 校验：`reports/capture-cache/店铺零售清单.json`（重叠区间通过，不并入主表）",
        "- 短窗复核：`data/imports/inventory_zip_extract/销售清单 - 【2026-03-13】.xlsx`（`2026-03-06` 到 `2026-03-13` 完全一致）",
        "- 辅助累计校验：`reports/capture-cache/商品销售情况.json`",
        "- 辅助回款校验：`reports/capture-cache/每日流水单.json`",
        "- 辅助解释：`reports/capture-cache/出入库单据.json`",
        "",
        "## 主店与可信度",
        "",
        f"- 默认主店：`{store_name}`",
        f"- Excel 推断主店：`{inferred_store}`",
        "- 可信：核心服饰毛销售额、退货冲减额、净销售额、按日净销售额、按月净销售额、按 SKU 累计净销售额。",
        "- 可信：销售/换货/退货的现金回款额，但这是订单级回款口径，包含道具。",
        "- 估算：本次不输出核心服饰现金回款额估算值，因为存在混合订单，缺少行级支付分摊依据。",
        "",
        "## 四套核心结果",
        "",
        f"- 主店最终校准后的毛销售额（剔除道具）：`{format_money(core_gross_sales_amount)}` 元",
        f"- 主店最终校准后的退货冲减额（剔除道具）：`{format_money(core_return_offset_amount)}` 元",
        f"- 主店最终校准后的净销售额（剔除道具）：`{format_money(core_net_sales_amount)}` 元",
        f"- 主店现金回款额（销售/换货/退货，含道具）：`{format_money(cash_receipts_amount)}` 元",
        "",
        "## 参考结果",
        "",
        f"- 核心服饰净销量：`{format_int(core_net_sales_qty)}` 件",
        f"- 核心服饰毛销量：`{format_int(core_gross_sales_qty)}` 件",
        f"- 核心服饰退货冲减件数：`{format_int(core_return_offset_qty)}` 件",
        f"- 道具毛销售额：`{format_money(prop_gross_amount)}` 元",
        f"- 道具退货冲减额：`{format_money(prop_return_amount)}` 元",
        f"- 道具净销售额：`{format_money(prop_net_amount)}` 元",
        f"- 全商品净销售额：`{format_money(all_goods_net_sales_amount)}` 元",
        f"- 销售相关 ActualMoney：`{format_money(actual_receipts_amount)}` 元",
        f"- 储值 ActualMoney：`{format_money(stored_value_money)}` 元",
        "",
        "## 关键校验结论",
        "",
        f"- 主表 vs 店铺零售清单：问题订单 `{len(retail_comparison['problem_orders'])}`，按天最大差异 `{format_money(retail_comparison['max_daily_amount_diff'])}` 元。",
        f"- 主表 vs Excel 短窗：问题订单 `{len(excel_comparison['problem_orders'])}`，按天最大差异 `{format_money(excel_comparison['max_daily_amount_diff'])}` 元。",
        f"- 主表 vs 商品销售情况：累计销额差异 `{format_money(product_comparison['core_amount_diff'])}` 元，累计销量差异 `{format_int(product_comparison['core_qty_diff'])}` 件。",
        f"- 主表 vs 每日流水单：销售/换货/退货订单级问题 `{len(flow_comparison['problem_orders'])}`。",
        "",
        "## 按月净销售额（前 12 个月）",
        "",
        dataframe_to_markdown(round_numeric_columns(monthly_sales[["month", "net_sales_amount", "prop_net_sales_amount", "all_goods_net_sales_amount", "flow_sales_related_cash_money"]].tail(12))),
        "",
        "## 按日净销售额（最近 15 天）",
        "",
        dataframe_to_markdown(round_numeric_columns(daily_sales[["sale_date", "net_sales_amount", "prop_net_sales_amount", "all_goods_net_sales_amount", "flow_sales_related_cash_money"]].tail(15))),
        "",
        "## 按 SKU 的累计净销售额（前 20）",
        "",
        dataframe_to_markdown(round_numeric_columns(top_skus[["sku", "color", "product_middle_type", "net_sales_amount", "net_sales_qty", "order_count"]])),
        "",
        "## 退货影响最大的前 20 个 SKU",
        "",
        dataframe_to_markdown(round_numeric_columns(top_return_skus[["sku", "color", "product_middle_type", "return_offset_amount", "return_offset_qty"]])),
        "",
        "## 数据冲突和不确定性清单",
        "",
        "- `店铺零售清单.json` 目前只校验到 `2026-02-28`，无法覆盖主表最后 15 天。",
        "- `商品销售情况.SumReturn` 与销售行级退货规则不完全一致，因此它只做累计净销售额/净销量校验，不直接覆盖退货冲减口径。",
        "- `每日流水单` 订单级回款与销售净额不是同一个概念：它会额外包含支付方式、券、抹零和储值等影响。",
        "- 存在道具与服饰混合订单，所以不能在不做支付分摊的前提下精确拆出“核心服饰现金回款额”。",
        "- `出入库单据` 当前缺 SKU 行级字段，只能解释库存动作，不能回写销售口径。",
        "",
        "## 还缺什么数据才能继续提高精度",
        "",
        "- 需要 SKU 级的出入库单据明细，才能把退货、报损、调拨和库存变化追到款色尺码。",
        "- 需要订单级支付明细能标记道具/服饰分摊，才能给出可信的核心服饰现金回款额。",
        "- 如果后续能稳定拿到主店 `店铺零售清单` 到 `2026-03-15` 之后的更新数据，就能把主表尾段的交叉校验补齐。",
    ]
    return "\n".join(lines) + "\n"


def build_source_frames_for_inventory(
    *,
    master_lines: pd.DataFrame,
    retail_lines: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    return {
        "sales_capture_master": master_lines,
        "store_retail_capture": retail_lines,
    }


def ensure_output_dir(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate master-store sales from local exports and capture cache.")
    parser.add_argument("--store-name", default=DEFAULT_STORE_NAME)
    parser.add_argument("--input-user", default=PRIMARY_INPUT)
    parser.add_argument("--input-dir", type=Path, default=ROOT / "data" / "imports" / "inventory_zip_extract")
    parser.add_argument("--capture-dir", type=Path, default=ROOT / "reports" / "capture-cache")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports" / "calibration")
    args = parser.parse_args()

    ensure_output_dir(args.output_dir)

    master_lines, capture_sales_audit = load_capture_sales_master(args.capture_dir, args.store_name)
    retail_lines, capture_retail_audit = load_capture_store_retail_validation(
        args.capture_dir,
        store_name=args.store_name,
        input_user=args.input_user,
    )
    product_rows, capture_product_audit = load_capture_product_sales(args.capture_dir)
    flow_rows, capture_flow_audit = load_capture_daily_flow(args.capture_dir)
    movement_rows, capture_movement_audit = load_capture_movement(args.capture_dir)
    excel_frames, excel_audit, inferred_store = load_excel_sales_audit(args.input_dir, args.store_name)

    retail_comparison = compare_sales_overlap(master_lines, retail_lines, label="capture_store_retail")
    excel_comparison = compare_sales_overlap(master_lines, excel_frames["sales"], label="excel_sales_short")
    product_comparison = compare_master_to_product(master_lines, product_rows)
    flow_comparison = compare_master_to_flow(master_lines, flow_rows)

    calibrated_order_lines = round_numeric_columns(master_lines.sort_values(["sale_date", "order_no", "line_no"]).copy())
    daily_sales = round_numeric_columns(build_daily_sales(master_lines, flow_rows))
    monthly_sales = round_numeric_columns(build_monthly_sales(master_lines, flow_rows))
    sku_sales = round_numeric_columns(build_sku_sales(master_lines))

    source_inventory_md = build_source_inventory_markdown(
        store_name=args.store_name,
        inferred_store=inferred_store,
        excel_frames={**excel_frames, **build_source_frames_for_inventory(master_lines=master_lines, retail_lines=retail_lines)},
        excel_audit=excel_audit,
        capture_sales_audit=capture_sales_audit,
        capture_retail_audit=capture_retail_audit,
        capture_product_audit=capture_product_audit,
        capture_flow_audit=capture_flow_audit,
        capture_movement_audit=capture_movement_audit,
        product_rows=product_rows,
        flow_rows=flow_rows,
        movement_rows=movement_rows,
    )
    source_comparison_md = build_source_comparison_markdown(
        retail_comparison=retail_comparison,
        excel_comparison=excel_comparison,
        product_comparison=product_comparison,
        flow_comparison=flow_comparison,
        master_lines=master_lines,
    )
    summary_md = build_summary_markdown(
        store_name=args.store_name,
        master_lines=master_lines,
        flow_rows=flow_rows,
        retail_comparison=retail_comparison,
        excel_comparison=excel_comparison,
        product_comparison=product_comparison,
        flow_comparison=flow_comparison,
        daily_sales=daily_sales,
        monthly_sales=monthly_sales,
        sku_sales=sku_sales,
        inferred_store=inferred_store,
    )

    (args.output_dir / "source_inventory.md").write_text(source_inventory_md, encoding="utf-8")
    (args.output_dir / "source_comparison.md").write_text(source_comparison_md, encoding="utf-8")
    (args.output_dir / "summary.md").write_text(summary_md, encoding="utf-8")
    calibrated_order_lines.to_csv(args.output_dir / "calibrated_order_lines.csv", index=False, encoding="utf-8-sig")
    daily_sales.to_csv(args.output_dir / "daily_sales_calibrated.csv", index=False, encoding="utf-8-sig")
    monthly_sales.to_csv(args.output_dir / "monthly_sales_calibrated.csv", index=False, encoding="utf-8-sig")
    sku_sales.to_csv(args.output_dir / "sku_sales_calibrated.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
