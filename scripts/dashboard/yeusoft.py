#!/usr/bin/env python3
"""Yeusoft capture loading and parsing helpers for the inventory dashboard."""

from __future__ import annotations

import json
import re
import urllib.parse
from pathlib import Path
from typing import Iterable

import pandas as pd


def safe_ratio(num: float, denom: float) -> float:
    if not denom:
        return 0.0
    return float(num) / float(denom)


def decode_yeusoft_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    text = re.sub(r"%u([0-9A-Fa-f]{4})", lambda match: chr(int(match.group(1), 16)), text)
    return urllib.parse.unquote(text)


def safe_float(value: object) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def extract_capture_response(capture_payload: dict | None, url_keyword: str) -> dict | None:
    if not capture_payload:
        return None
    for response in capture_payload.get("responses", []):
        if url_keyword in response.get("url", ""):
            return response.get("body")
    return None


def extract_capture_request(capture_payload: dict | None, url_keyword: str) -> dict | None:
    if not capture_payload:
        return None
    for request in capture_payload.get("requests", []):
        if url_keyword in request.get("url", ""):
            return request.get("postData")
    return None


def load_yeusoft_capture_bundle(capture_dir: Path | None) -> dict[str, dict]:
    if not capture_dir or not capture_dir.exists():
        return {}

    bundle: dict[str, dict] = {}
    for report_name in (
        "销售清单",
        "商品销售情况",
        "会员消费排行",
        "库存综合分析",
        "出入库单据",
        "每日流水单",
        "商品品类分析",
        "会员综合分析",
        "导购员报表",
        "门店销售月报",
        "零售明细统计",
    ):
        capture_path = capture_dir / f"{report_name}.json"
        if capture_path.exists():
            try:
                bundle[report_name] = json.loads(capture_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
    return bundle


def extract_capture_rows(capture_payload: dict | None, url_keyword: str) -> tuple[list[dict], dict]:
    body = extract_capture_response(capture_payload, url_keyword)
    request_payload = extract_capture_request(capture_payload, url_keyword) or {}
    if not body:
        return [], request_payload

    retdata = body.get("retdata")
    if isinstance(retdata, dict):
        data_rows = retdata.get("Data") or []
        columns = retdata.get("ColumnsList") or []
        if columns and data_rows and isinstance(data_rows[0], list):
            return [dict(zip(columns, row)) for row in data_rows], request_payload
        if data_rows and isinstance(data_rows[0], dict):
            return data_rows, request_payload
        return [], request_payload

    if isinstance(retdata, list) and retdata:
        payload = retdata[0] if isinstance(retdata[0], dict) else {}
        data_rows = payload.get("Data") or []
        columns = payload.get("ColumnsList") or []
        if columns and data_rows and isinstance(data_rows[0], list):
            return [dict(zip(columns, row)) for row in data_rows], request_payload
        if data_rows and isinstance(data_rows[0], dict):
            return data_rows, request_payload
    return [], request_payload


def normalize_yeusoft_frame(frame: pd.DataFrame, numeric_columns: Iterable[str]) -> pd.DataFrame:
    if frame.empty:
        return frame

    cleaned = frame.copy()
    for column in cleaned.columns:
        if cleaned[column].dtype == object:
            cleaned[column] = cleaned[column].apply(lambda value: decode_yeusoft_text(value).strip())
    for column in numeric_columns:
        if column in cleaned.columns:
            cleaned[column] = pd.to_numeric(cleaned[column], errors="coerce").fillna(0.0)
    return cleaned


def parse_yeusoft_request_date(value: object) -> pd.Timestamp:
    if value in (None, ""):
        return pd.NaT
    text = str(value).strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        parsed = pd.to_datetime(text, format=fmt, errors="coerce")
        if pd.notna(parsed):
            return parsed
    return pd.to_datetime(text, errors="coerce")


def extract_yeusoft_period_headers(payload: dict) -> list[tuple[str, str]]:
    headers = payload.get("GridHeader") or []
    amount_columns: list[tuple[str, str]] = []
    for item in headers:
        gcode = decode_yeusoft_text(item.get("gcode"))
        if not gcode or not gcode.isdigit() or len(gcode) != 5:
            continue
        amount_code = f"{gcode}Money"
        label = decode_yeusoft_text(item.get("gname"))
        amount_columns.append((amount_code, label or gcode))
    return amount_columns


def parse_yeusoft_sales_overview(capture_payload: dict | None) -> dict | None:
    rows, request_payload = extract_capture_rows(capture_payload, "GetDIYReportData")
    if not rows:
        return None

    df = normalize_yeusoft_frame(
        pd.DataFrame(rows),
        ["数量", "金额", "单价", "吊牌价", "吊牌金额", "折扣"],
    )
    if df.empty:
        return None

    if "销售日期" in df.columns:
        df["销售日期"] = pd.to_datetime(df["销售日期"], errors="coerce")
    if "会员卡号" in df.columns:
        df["是否会员"] = df["会员卡号"].astype(str).str.strip().ne("")
    else:
        df["是否会员"] = False

    non_props = df.copy()
    if "商品大类" in non_props.columns:
        non_props = non_props[non_props["商品大类"].ne("道具")]
    if "商品中类" in non_props.columns:
        non_props = non_props[non_props["商品中类"].ne("道具")]

    if non_props.empty:
        return None

    dated = non_props[non_props["销售日期"].notna()].copy() if "销售日期" in non_props.columns else pd.DataFrame()
    monthly_rows: list[dict[str, object]] = []
    quarterly_rows: list[dict[str, object]] = []
    if not dated.empty:
        dated["month_period"] = dated["销售日期"].dt.to_period("M")
        dated["quarter_period"] = dated["销售日期"].dt.to_period("Q")

        monthly_group = (
            dated.groupby("month_period")
            .agg(
                销售额=("金额", "sum"),
                销量=("数量", "sum"),
                单数=("零售单号", "nunique"),
                会员销额=("金额", lambda series: series[dated.loc[series.index, "是否会员"]].sum()),
            )
            .reset_index()
            .sort_values("month_period")
        )
        monthly_cat = (
            dated.groupby(["month_period", "商品中类"], dropna=False)
            .agg(销售额=("金额", "sum"))
            .reset_index()
            .sort_values(["month_period", "销售额"], ascending=[True, False])
            .drop_duplicates("month_period")
        )
        monthly_group = monthly_group.merge(monthly_cat[["month_period", "商品中类", "销售额"]].rename(columns={"商品中类": "主销中类", "销售额": "主销中类销售额"}), on="month_period", how="left")
        for _, row in monthly_group.iterrows():
            period = row["month_period"]
            monthly_rows.append(
                {
                    "label": period.strftime("%Y-%m"),
                    "sales_amount": float(row["销售额"]),
                    "sales_qty": float(row["销量"]),
                    "order_count": int(row["单数"]),
                    "avg_order_value": safe_ratio(row["销售额"], row["单数"]),
                    "member_ratio": safe_ratio(row["会员销额"], row["销售额"]),
                    "top_category": row.get("主销中类") or "未标记中类",
                    "top_category_sales": float(row.get("主销中类销售额") or 0),
                }
            )

        quarterly_group = (
            dated.groupby("quarter_period")
            .agg(
                销售额=("金额", "sum"),
                销量=("数量", "sum"),
                单数=("零售单号", "nunique"),
                会员销额=("金额", lambda series: series[dated.loc[series.index, "是否会员"]].sum()),
            )
            .reset_index()
            .sort_values("quarter_period")
        )
        quarterly_cat = (
            dated.groupby(["quarter_period", "商品中类"], dropna=False)
            .agg(销售额=("金额", "sum"))
            .reset_index()
            .sort_values(["quarter_period", "销售额"], ascending=[True, False])
            .drop_duplicates("quarter_period")
        )
        quarterly_group = quarterly_group.merge(
            quarterly_cat[["quarter_period", "商品中类", "销售额"]].rename(columns={"商品中类": "主销中类", "销售额": "主销中类销售额"}),
            on="quarter_period",
            how="left",
        )
        for _, row in quarterly_group.iterrows():
            period = row["quarter_period"]
            quarterly_rows.append(
                {
                    "label": f"{period.year}Q{period.quarter}",
                    "sales_amount": float(row["销售额"]),
                    "sales_qty": float(row["销量"]),
                    "order_count": int(row["单数"]),
                    "avg_order_value": safe_ratio(row["销售额"], row["单数"]),
                    "member_ratio": safe_ratio(row["会员销额"], row["销售额"]),
                    "top_category": row.get("主销中类") or "未标记中类",
                    "top_category_sales": float(row.get("主销中类销售额") or 0),
                }
            )

    top_categories_df = (
        non_props.groupby("商品中类", dropna=False)
        .agg(销售额=("金额", "sum"), 销量=("数量", "sum"), 单数=("零售单号", "nunique"))
        .reset_index()
        .sort_values(["销售额", "销量"], ascending=[False, False])
    )
    top_categories = [
        {
            "name": row["商品中类"] or "未标记中类",
            "sales_amount": float(row["销售额"]),
            "sales_qty": float(row["销量"]),
            "order_count": int(row["单数"]),
        }
        for _, row in top_categories_df.head(3).iterrows()
    ]

    top_guides = []
    if "导购员" in non_props.columns:
        guide_df = (
            non_props.groupby("导购员", dropna=False)
            .agg(销售额=("金额", "sum"), 单数=("零售单号", "nunique"))
            .reset_index()
            .sort_values(["销售额", "单数"], ascending=[False, False])
        )
        top_guides = [
            {
                "name": row["导购员"] or "未标记导购",
                "sales_amount": float(row["销售额"]),
                "order_count": int(row["单数"]),
            }
            for _, row in guide_df.head(3).iterrows()
            if str(row["导购员"]).strip()
        ]

    top_category_labels = "、".join(item["name"] for item in top_categories) if top_categories else "暂无明显主力中类"
    top_guide_name = top_guides[0]["name"] if top_guides else ""
    store_name = ""
    if "店铺名称" in non_props.columns and not non_props["店铺名称"].dropna().empty:
        store_name = str(non_props["店铺名称"].mode().iloc[0]).strip()

    return {
        "capture_at": pd.to_datetime(capture_payload.get("capturedAt"), errors="coerce"),
        "window_start": pd.to_datetime(request_payload.get("parameter", {}).get("BeginDate"), format="%Y%m%d", errors="coerce"),
        "window_end": pd.to_datetime(request_payload.get("parameter", {}).get("EndDate"), format="%Y%m%d", errors="coerce"),
        "store_name": store_name,
        "sales_amount": float(non_props["金额"].sum()),
        "sales_qty": float(non_props["数量"].sum()),
        "order_count": int(non_props["零售单号"].nunique()) if "零售单号" in non_props.columns else int(len(non_props)),
        "avg_order_value": safe_ratio(non_props["金额"].sum(), non_props["零售单号"].nunique()) if "零售单号" in non_props.columns else 0.0,
        "member_sales_ratio": safe_ratio(non_props.loc[non_props["是否会员"], "金额"].sum(), non_props["金额"].sum()),
        "top_categories": top_categories,
        "top_category_labels": top_category_labels,
        "top_guides": top_guides,
        "top_guide_name": top_guide_name,
        "monthly_rows": monthly_rows,
        "quarterly_rows": quarterly_rows,
        "latest_month": monthly_rows[-1] if monthly_rows else None,
        "previous_month": monthly_rows[-2] if len(monthly_rows) >= 2 else None,
        "latest_quarter": quarterly_rows[-1] if quarterly_rows else None,
        "previous_quarter": quarterly_rows[-2] if len(quarterly_rows) >= 2 else None,
    }


def parse_yeusoft_product_sales(capture_payload: dict | None, current_season: str, next_season: str) -> dict | None:
    rows, request_payload = extract_capture_rows(capture_payload, "SelSaleReportData")
    if not rows:
        return None

    df = normalize_yeusoft_frame(
        pd.DataFrame(rows),
        ["SaleAmount", "SaleMoney", "SumSaleAmount", "SumSaleMoney", "SumArrival", "WeekSellOut", "SumSellOut", "StockNum", "SumReturn"],
    )
    if df.empty:
        return None

    df = df[df["WareCode"].astype(str).str.strip().ne("")]
    non_props = df[df["MType"].ne("道具")].copy() if "MType" in df.columns else df.copy()
    if non_props.empty:
        return None

    non_props["Season"] = non_props["Season"].apply(normalize_product_season)
    non_props["season_strategy"] = non_props["Season"].apply(
        lambda season: classify_season_action(current_season, next_season, season)
    )
    non_props["season_label"] = (
        non_props["Year"].astype(str).str.strip().replace({"": "未标记年份"}) + non_props["Season"].replace({"": "未标记季节"})
    )

    season_stock_df = (
        non_props.groupby("season_label", dropna=False)
        .agg(库存件数=("StockNum", "sum"), 累计销额=("SumSaleMoney", "sum"))
        .reset_index()
        .sort_values(["库存件数", "累计销额"], ascending=[False, False])
    )
    top_stock_labels = "、".join(
        row["season_label"] for _, row in season_stock_df.head(3).iterrows() if str(row["season_label"]).strip()
    ) or "暂无明显库存季节结构"

    current_rows = non_props[non_props["Season"].eq(current_season)]
    next_rows = non_props[non_props["Season"].eq(next_season)]
    cross_rows = non_props[non_props["season_strategy"].isin({"跨季去化", "暂缓补货"})]

    fast_sellout_count = int(((non_props["SumSellOut"] >= 0.8) & (non_props["StockNum"] <= 2)).sum())
    backlog_count = int(((non_props["SumSellOut"] <= 0.35) & (non_props["StockNum"] >= 5)).sum())
    current_stock_qty = float(non_props["StockNum"].sum())
    current_sellout_rate = safe_ratio(non_props["SumSaleAmount"].sum(), non_props["SumArrival"].sum())

    return {
        "capture_at": pd.to_datetime(capture_payload.get("capturedAt"), errors="coerce"),
        "window_start": pd.to_datetime(request_payload.get("bdate"), format="%Y%m%d", errors="coerce"),
        "window_end": pd.to_datetime(request_payload.get("edate"), format="%Y%m%d", errors="coerce"),
        "style_count": int(len(non_props)),
        "cumulative_sales_qty": float(non_props["SumSaleAmount"].sum()),
        "cumulative_sales_amount": float(non_props["SumSaleMoney"].sum()),
        "cumulative_arrival_qty": float(non_props["SumArrival"].sum()),
        "current_stock_qty": current_stock_qty,
        "sellout_rate": current_sellout_rate,
        "current_season_stock_share": safe_ratio(current_rows["StockNum"].sum(), current_stock_qty),
        "next_season_stock_share": safe_ratio(next_rows["StockNum"].sum(), current_stock_qty),
        "cross_season_stock_share": safe_ratio(cross_rows["StockNum"].sum(), current_stock_qty),
        "top_stock_labels": top_stock_labels,
        "fast_sellout_count": fast_sellout_count,
        "backlog_count": backlog_count,
    }


def parse_yeusoft_member_rank(capture_payload: dict | None) -> dict | None:
    rows, request_payload = extract_capture_rows(capture_payload, "SelVipSaleRank")
    if not rows:
        return None

    df = normalize_yeusoft_frame(pd.DataFrame(rows), ["TM", "TN", "WareCnt", "N", "P"])
    if df.empty:
        return None

    # 第一行通常是合计行，用户名和卡号都为空。
    members = df[(df["UserName"].astype(str).str.strip().ne("")) | (df["VipCardID"].astype(str).str.strip().ne(""))].copy()
    if members.empty:
        return None

    members = members.sort_values(["TM", "TN"], ascending=[False, False]).reset_index(drop=True)
    total_amount = float(members["TM"].sum())
    top_members = [
        {
            "name": row["UserName"] or "未命名会员",
            "vip_card": row["VipCardID"],
            "amount": float(row["TM"]),
        }
        for _, row in members.head(5).iterrows()
    ]
    top_names = "、".join(item["name"] for item in top_members[:3]) if top_members else "暂无高价值会员"
    top10_amount = float(members.head(10)["TM"].sum())

    return {
        "capture_at": pd.to_datetime(capture_payload.get("capturedAt"), errors="coerce"),
        "window_start": pd.to_datetime(request_payload.get("bdate"), format="%Y%m%d", errors="coerce"),
        "window_end": pd.to_datetime(request_payload.get("edate"), format="%Y%m%d", errors="coerce"),
        "member_count": int(len(members)),
        "total_amount": total_amount,
        "top10_amount": top10_amount,
        "top10_share": safe_ratio(top10_amount, total_amount),
        "top_members": top_members,
        "top_names": top_names,
    }


def parse_yeusoft_stock_analysis(capture_payload: dict | None, current_season: str, next_season: str) -> dict | None:
    body = extract_capture_response(capture_payload, "SelStockAnalysisList")
    if not body or body.get("errcode") != "1000":
        return None

    retdata = body.get("retdata") or []
    if not retdata:
        return None
    payload = retdata[0]
    summary_rows = payload.get("HJ") or []
    detail_rows = payload.get("Data") or []
    if not summary_rows:
        return None

    total_row = summary_rows[0]
    parsed_rows = []
    for row in detail_rows:
        season = decode_yeusoft_text(row.get("Season"))
        year = decode_yeusoft_text(row.get("Year"))
        inventory_qty = safe_float(row.get("SL2"))
        inventory_amount = safe_float(row.get("JE2"))
        style_count = safe_float(row.get("KS2"))
        season_strategy = classify_season_action(current_season, next_season, season)
        parsed_rows.append(
            {
                "label": f"{year}{season}" if year or season else "未标记季节",
                "year": year,
                "season": season,
                "inventory_qty": inventory_qty,
                "inventory_amount": inventory_amount,
                "style_count": style_count,
                "season_strategy": season_strategy,
            }
        )

    inventory_rows = [row for row in parsed_rows if row["inventory_amount"] > 0 or row["inventory_qty"] > 0]
    inventory_rows.sort(key=lambda row: row["inventory_amount"], reverse=True)

    total_inventory_qty = safe_float(total_row.get("SL2"))
    total_inventory_amount = safe_float(total_row.get("JE2"))
    total_style_count = safe_float(total_row.get("KS2"))
    for row in inventory_rows:
        row["inventory_amount_share"] = safe_ratio(row["inventory_amount"], total_inventory_amount)
        row["inventory_qty_share"] = safe_ratio(row["inventory_qty"], total_inventory_qty)

    current_rows = [row for row in inventory_rows if row["season"] == current_season]
    cross_season_rows = [
        row for row in inventory_rows if row["season_strategy"] in {"跨季去化", "暂缓补货"}
    ]
    next_season_rows = [row for row in inventory_rows if row["season"] == next_season]
    top_rows = inventory_rows[:3]
    top_labels = "、".join(row["label"] for row in top_rows) if top_rows else "暂无明显库存结构"

    return {
        "capture_at": pd.to_datetime(capture_payload.get("capturedAt"), errors="coerce"),
        "last_year_label": decode_yeusoft_text(payload.get("LastYDate")),
        "current_year_label": decode_yeusoft_text(payload.get("LastNYDate")),
        "total_inventory_qty": total_inventory_qty,
        "total_inventory_amount": total_inventory_amount,
        "total_style_count": total_style_count,
        "current_season_inventory_share": safe_ratio(
            sum(row["inventory_amount"] for row in current_rows), total_inventory_amount
        ),
        "next_season_inventory_share": safe_ratio(
            sum(row["inventory_amount"] for row in next_season_rows), total_inventory_amount
        ),
        "cross_season_inventory_share": safe_ratio(
            sum(row["inventory_amount"] for row in cross_season_rows), total_inventory_amount
        ),
        "top_rows": top_rows,
        "top_labels": top_labels,
    }


def parse_yeusoft_movement_report(capture_payload: dict | None) -> dict | None:
    body = extract_capture_response(capture_payload, "SelOutInStockReport")
    if not body or body.get("errcode") != "1000":
        return None

    retdata = body.get("retdata") or []
    if not retdata:
        return None

    request_payload = extract_capture_request(capture_payload, "SelOutInStockReport") or {}
    payload = retdata[0]
    rows = payload.get("Data") or []
    decoded_rows = []
    for row in rows:
        decoded_rows.append(
            {
                "doc_type": decode_yeusoft_text(row.get("DocType")),
                "doc_status": decode_yeusoft_text(row.get("DocStat")),
                "transfer_type": decode_yeusoft_text(row.get("Transtat")),
                "from_store": decode_yeusoft_text(row.get("WhID")),
                "to_store": decode_yeusoft_text(row.get("InWhID")),
                "come_date": pd.to_datetime(row.get("ComeDate"), errors="coerce"),
                "receive_date": pd.to_datetime(row.get("ReceDate"), errors="coerce"),
                "qty": safe_float(row.get("TN")),
                "amount": safe_float(row.get("TRP")),
            }
        )

    inbound_rows = [row for row in decoded_rows if "入库" in row["doc_status"]]
    outbound_rows = [row for row in decoded_rows if "出库" in row["doc_status"]]
    latest_doc_time = max(
        [row["receive_date"] for row in decoded_rows if pd.notna(row["receive_date"])]
        + [row["come_date"] for row in decoded_rows if pd.notna(row["come_date"])],
        default=pd.NaT,
    )

    return {
        "capture_at": pd.to_datetime(capture_payload.get("capturedAt"), errors="coerce"),
        "window_start": pd.to_datetime(request_payload.get("bdate"), format="%Y%m%d", errors="coerce"),
        "window_end": pd.to_datetime(request_payload.get("edate"), format="%Y%m%d", errors="coerce"),
        "record_count": int(payload.get("Count") or len(decoded_rows)),
        "inbound_count": len(inbound_rows),
        "inbound_qty": sum(row["qty"] for row in inbound_rows),
        "inbound_amount": sum(row["amount"] for row in inbound_rows),
        "outbound_count": len(outbound_rows),
        "outbound_qty": sum(row["qty"] for row in outbound_rows),
        "outbound_amount": sum(row["amount"] for row in outbound_rows),
        "net_qty": sum(row["qty"] for row in inbound_rows) - sum(row["qty"] for row in outbound_rows),
        "net_amount": sum(row["amount"] for row in inbound_rows) - sum(row["amount"] for row in outbound_rows),
        "latest_doc_time": latest_doc_time,
    }


def parse_yeusoft_daily_flow(capture_payload: dict | None) -> dict | None:
    body = extract_capture_response(capture_payload, "SelectRetailDocPaymentSlip")
    if not body or not body.get("Success"):
        return None

    payload = body.get("Data") or {}
    columns = payload.get("Columns") or []
    rows = payload.get("List") or []
    if not columns:
        return None

    normalized_rows = [dict(zip(columns, row)) for row in rows if isinstance(row, list)]
    request_payload = extract_capture_request(capture_payload, "SelectRetailDocPaymentSlip") or {}
    payment_labels = {
        "CashMoney": "现金",
        "SwipeMoney": "刷卡",
        "WxMoney": "微信",
        "AlipayMoney": "支付宝",
        "CouponMoney": "券",
        "ActivityMoney": "活动优惠",
        "ScanCodeMoney": "扫码",
        "WipeZeroMoney": "抹零",
        "OtherMoney": "其他",
    }
    payment_breakdown = []
    total_actual_money = 0.0
    total_sales_qty = 0.0
    total_tag_money = 0.0
    total_discount = 0.0
    latest_make_date = pd.NaT

    payment_totals = {key: 0.0 for key in payment_labels}
    for row in normalized_rows:
        total_actual_money += safe_float(row.get("ActualMoney"))
        total_sales_qty += safe_float(row.get("Amount"))
        total_tag_money += safe_float(row.get("TagMoney"))
        total_discount += safe_float(row.get("SaleDiscount"))
        make_date = pd.to_datetime(row.get("MakeDate"), errors="coerce")
        if pd.notna(make_date):
            latest_make_date = make_date if pd.isna(latest_make_date) else max(latest_make_date, make_date)
        for key in payment_labels:
            payment_totals[key] += safe_float(row.get(key))

    for key, label in payment_labels.items():
        amount = payment_totals[key]
        if amount > 0:
            payment_breakdown.append(
                {
                    "label": label,
                    "amount": amount,
                    "share": safe_ratio(amount, total_actual_money),
                }
            )
    payment_breakdown.sort(key=lambda item: item["amount"], reverse=True)
    dominant_payment = payment_breakdown[0] if payment_breakdown else None

    return {
        "capture_at": pd.to_datetime(capture_payload.get("capturedAt"), errors="coerce"),
        "window_start": parse_yeusoft_request_date(request_payload.get("BeginDate")),
        "window_end": parse_yeusoft_request_date(request_payload.get("EndDate")),
        "order_count": len(normalized_rows),
        "sales_qty": total_sales_qty,
        "tag_money": total_tag_money,
        "actual_money": total_actual_money,
        "average_discount": safe_ratio(total_discount, len(normalized_rows)),
        "payment_breakdown": payment_breakdown,
        "dominant_payment": dominant_payment,
        "latest_make_date": latest_make_date,
    }


def parse_yeusoft_category_analysis(capture_payload: dict | None) -> dict | None:
    body = extract_capture_response(capture_payload, "SelWareTypeAnalysisList")
    if not body or body.get("errcode") != "1000":
        return None

    payload = (body.get("retdata") or [{}])[0]
    rows = payload.get("Data") or []
    if not rows:
        return None

    amount_columns = extract_yeusoft_period_headers(payload)
    numeric_columns = [column for column, _ in amount_columns]
    frame = normalize_yeusoft_frame(pd.DataFrame(rows), numeric_columns)
    if frame.empty or "Category" not in frame.columns:
        return None

    frame["Category"] = frame["Category"].replace("", "未标记品类")
    available_periods = [
        (column, label)
        for column, label in amount_columns
        if column in frame.columns and float(frame[column].sum()) > 0
    ]
    if not available_periods:
        return None

    frame["total_period_sales"] = frame[[column for column, _ in available_periods]].sum(axis=1)
    total_sales = float(frame["total_period_sales"].sum())
    top_categories_df = (
        frame[["Category", "total_period_sales"]]
        .groupby("Category", dropna=False)
        .sum()
        .reset_index()
        .sort_values("total_period_sales", ascending=False)
    )
    top_categories = [
        {
            "name": row["Category"],
            "sales_amount": float(row["total_period_sales"]),
            "share": safe_ratio(row["total_period_sales"], total_sales),
        }
        for _, row in top_categories_df.head(5).iterrows()
    ]

    period_rows: list[dict[str, object]] = []
    for column, label in available_periods:
        period_total = float(frame[column].sum())
        if period_total <= 0:
            continue
        top_row = frame.sort_values(column, ascending=False).iloc[0]
        period_rows.append(
            {
                "label": label,
                "sales_amount": period_total,
                "top_category": top_row["Category"] or "未标记品类",
                "top_category_sales": float(top_row[column]),
            }
        )

    latest_period = period_rows[-1] if period_rows else None
    previous_period = period_rows[-2] if len(period_rows) >= 2 else None
    latest_column = available_periods[-1][0]
    previous_column = available_periods[-2][0] if len(available_periods) >= 2 else None
    growth_rows: list[dict[str, object]] = []
    decline_rows: list[dict[str, object]] = []
    if previous_column:
        comparison = frame[["Category", latest_column, previous_column]].copy()
        comparison["delta_sales"] = comparison[latest_column] - comparison[previous_column]
        growth_rows = [
            {
                "name": row["Category"],
                "delta_sales": float(row["delta_sales"]),
                "latest_sales": float(row[latest_column]),
            }
            for _, row in comparison.sort_values("delta_sales", ascending=False).head(3).iterrows()
            if float(row["delta_sales"]) > 0
        ]
        decline_rows = [
            {
                "name": row["Category"],
                "delta_sales": float(row["delta_sales"]),
                "latest_sales": float(row[latest_column]),
            }
            for _, row in comparison.sort_values("delta_sales", ascending=True).head(3).iterrows()
            if float(row["delta_sales"]) < 0
        ]

    request_payload = extract_capture_request(capture_payload, "SelWareTypeAnalysisList") or {}
    top_category_names = "、".join(item["name"] for item in top_categories[:3]) if top_categories else "暂无明显主力品类"
    return {
        "capture_at": pd.to_datetime(capture_payload.get("capturedAt"), errors="coerce"),
        "window_start": parse_yeusoft_request_date(request_payload.get("bdate")),
        "window_end": parse_yeusoft_request_date(request_payload.get("edate")),
        "top_categories": top_categories,
        "top_category_names": top_category_names,
        "top1_share": top_categories[0]["share"] if top_categories else 0.0,
        "top2_share": safe_ratio(sum(item["sales_amount"] for item in top_categories[:2]), total_sales),
        "period_rows": period_rows,
        "latest_period": latest_period,
        "previous_period": previous_period,
        "growth_rows": growth_rows,
        "decline_rows": decline_rows,
    }


def parse_yeusoft_vip_analysis(capture_payload: dict | None) -> dict | None:
    body = extract_capture_response(capture_payload, "SelVipAnalysisReport")
    if not body or body.get("errcode") != "1000":
        return None

    payload = (body.get("retdata") or [{}])[0]
    rows = payload.get("Data") or []
    if not rows:
        return None

    numeric_columns = [
        "Point",
        "TotalPoint",
        "RetuMoney",
        "SSMoney",
        "BVMoney",
        "VipPosCardNum",
        "EachSale",
        "SaleNumByYear",
        "SaleStock",
        "SaleNum",
        "TotalMoney",
        "SaleWeek",
        "SaleSpace",
    ]
    frame = normalize_yeusoft_frame(pd.DataFrame(rows), numeric_columns)
    if frame.empty:
        return None

    if "LastSaleDate" in frame.columns:
        frame["LastSaleDate"] = pd.to_datetime(frame["LastSaleDate"], errors="coerce")
    frame = frame[frame["VipCardID"].astype(str).str.strip().ne("")].copy()
    if frame.empty:
        return None

    frame = frame.sort_values(["TotalMoney", "SaleNum"], ascending=[False, False]).reset_index(drop=True)
    summary_row = ((payload.get("HJ") or [{}])[0]) if (payload.get("HJ") or []) else {}
    total_member_sales = safe_float(summary_row.get("TotalMoney")) or float(frame["TotalMoney"].sum())
    avg_member_sale = safe_float(summary_row.get("EachSale")) or safe_ratio(total_member_sales, len(frame))
    total_member_orders = safe_float(summary_row.get("SaleNum")) or float(frame["SaleNum"].sum())
    vip_card_count = safe_float(summary_row.get("VipPosCardNum")) or float(len(frame))
    request_payload = extract_capture_request(capture_payload, "SelVipAnalysisReport") or {}
    window_end = parse_yeusoft_request_date(request_payload.get("saleedate"))

    active_recent_count = 0
    dormant_count = 0
    if pd.notna(window_end) and "LastSaleDate" in frame.columns:
        active_recent_count = int((frame["LastSaleDate"] >= (window_end - pd.Timedelta(days=60))).sum())
        dormant_count = int(
            frame["LastSaleDate"].isna().sum()
            + (frame["LastSaleDate"] < (window_end - pd.Timedelta(days=120))).sum()
        )

    top_members = [
        {
            "name": row["VipName"] or "未命名会员",
            "vip_card": row["VipCardID"],
            "total_money": float(row["TotalMoney"]),
            "sale_count": float(row["SaleNum"]),
            "last_sale_date": row["LastSaleDate"],
        }
        for _, row in frame.head(5).iterrows()
    ]

    return {
        "capture_at": pd.to_datetime(capture_payload.get("capturedAt"), errors="coerce"),
        "window_start": parse_yeusoft_request_date(request_payload.get("salebdate")),
        "window_end": window_end,
        "member_count": int(len(frame)),
        "vip_card_count": int(vip_card_count),
        "total_member_sales": total_member_sales,
        "avg_member_sale": avg_member_sale,
        "total_member_orders": total_member_orders,
        "active_recent_count": active_recent_count,
        "dormant_count": dormant_count,
        "dormant_ratio": safe_ratio(dormant_count, len(frame)),
        "top_members": top_members,
        "top_member_names": "、".join(item["name"] for item in top_members[:3]) if top_members else "暂无高价值会员",
    }


def parse_yeusoft_guide_report(capture_payload: dict | None) -> dict | None:
    body = extract_capture_response(capture_payload, "SelPersonSale")
    if not body or body.get("errcode") != "1000":
        return None

    payload = (body.get("retdata") or [{}])[0]
    rows = payload.get("Data") or []
    if not rows:
        return None

    numeric_columns = [
        "Amount",
        "TotalRetailMoeny",
        "DisCount",
        "TotalMoney",
        "Cash",
        "CreditCard",
        "OrderMoney",
        "PosMoney",
        "RetuMoney",
        "ActivityMoeny",
        "StockMoney",
        "WxPayMoney",
        "ZfbPayMoney",
        "OddMoney",
        "WpZeroMoney",
        "VipAmount",
        "VipMoney",
        "Saleps",
        "StockRechargeMoney",
        "DJ",
        "FJ",
        "JEZB",
        "SLZB",
        "ssMoneyRebate",
    ]
    frame = normalize_yeusoft_frame(pd.DataFrame(rows), numeric_columns)
    if frame.empty:
        return None

    frame = frame[frame["Name"].astype(str).str.strip().ne("")].copy()
    if frame.empty:
        return None

    frame = frame.sort_values(["TotalMoney", "Amount"], ascending=[False, False]).reset_index(drop=True)
    total_sales = float(frame["TotalMoney"].sum())
    top_guides = [
        {
            "name": row["Name"],
            "sales_amount": float(row["TotalMoney"]),
            "sales_qty": float(row["Amount"]),
            "vip_money": float(row["VipMoney"]),
            "discount_rate": float(row["DisCount"]),
        }
        for _, row in frame.head(5).iterrows()
    ]
    request_payload = extract_capture_request(capture_payload, "SelPersonSale") or {}
    top_guide_sales = top_guides[0]["sales_amount"] if top_guides else 0.0
    return {
        "capture_at": pd.to_datetime(capture_payload.get("capturedAt"), errors="coerce"),
        "window_start": parse_yeusoft_request_date(request_payload.get("bdate")),
        "window_end": parse_yeusoft_request_date(request_payload.get("edate")),
        "guide_count": int(len(frame)),
        "total_sales": total_sales,
        "vip_sales_share": safe_ratio(frame["VipMoney"].sum(), total_sales),
        "top_guides": top_guides,
        "top_guide_name": top_guides[0]["name"] if top_guides else "暂无主力导购",
        "top_guide_share": safe_ratio(top_guide_sales, total_sales),
    }


def parse_yeusoft_monthly_sales_report(capture_payload: dict | None) -> dict | None:
    body = extract_capture_response(capture_payload, "DeptMonthSalesReport")
    if not body or not body.get("Success"):
        return None

    payload = body.get("Data") or {}
    page_data = payload.get("PageData") or {}
    rows = page_data.get("Items") or []
    if not rows:
        return None

    numeric_columns = ["SalePNum", "SaleAmount", "Jointandseveral"]
    frame = normalize_yeusoft_frame(pd.DataFrame(rows), numeric_columns)
    if frame.empty or "Date" not in frame.columns:
        return None

    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    frame = frame[frame["Date"].notna()].copy()
    if frame.empty:
        return None

    frame["month_period"] = frame["Date"].dt.to_period("M")
    frame["quarter_period"] = frame["Date"].dt.to_period("Q")
    monthly_rows = []
    for period, chunk in frame.groupby("month_period"):
        monthly_rows.append(
            {
                "label": period.strftime("%Y-%m"),
                "order_count": float(chunk["SalePNum"].sum()),
                "sales_qty": float(chunk["SaleAmount"].sum()),
                "joint_rate": safe_ratio(chunk["SaleAmount"].sum(), chunk["SalePNum"].sum()),
                "avg_joint_rate": float(chunk["Jointandseveral"].mean()),
            }
        )
    quarterly_rows = []
    for period, chunk in frame.groupby("quarter_period"):
        quarterly_rows.append(
            {
                "label": f"{period.year}Q{period.quarter}",
                "order_count": float(chunk["SalePNum"].sum()),
                "sales_qty": float(chunk["SaleAmount"].sum()),
                "joint_rate": safe_ratio(chunk["SaleAmount"].sum(), chunk["SalePNum"].sum()),
                "avg_joint_rate": float(chunk["Jointandseveral"].mean()),
            }
        )

    request_payload = extract_capture_request(capture_payload, "DeptMonthSalesReport") or {}
    low_joint_days = int((frame["Jointandseveral"] < 1.1).sum())
    return {
        "capture_at": pd.to_datetime(capture_payload.get("capturedAt"), errors="coerce"),
        "window_start": parse_yeusoft_request_date(request_payload.get("BeginDate")),
        "window_end": parse_yeusoft_request_date(request_payload.get("EndDate")),
        "row_count": int(len(frame)),
        "monthly_rows": monthly_rows,
        "quarterly_rows": quarterly_rows,
        "latest_month": monthly_rows[-1] if monthly_rows else None,
        "latest_quarter": quarterly_rows[-1] if quarterly_rows else None,
        "low_joint_days": low_joint_days,
    }


def extract_retail_detail_size_labels(payload: dict) -> dict[str, str]:
    title_rows = payload.get("Title") or []
    if not title_rows or not isinstance(title_rows[0], dict):
        return {}

    mapping: dict[str, str] = {}
    for column, raw_label in title_rows[0].items():
        if not str(column).startswith("col"):
            continue
        decoded = decode_yeusoft_text(raw_label)
        parts = [
            part.strip()
            for part in re.split(r"<br\s*/?>", decoded, flags=re.IGNORECASE)
            if part and part.strip() and part.strip() != "\u3000"
        ]
        deduped: list[str] = []
        for part in parts:
            if part not in deduped:
                deduped.append(part)
        if deduped:
            mapping[column] = "/".join(deduped[:2])
    return mapping


def parse_yeusoft_retail_detail(capture_payload: dict | None) -> dict | None:
    body = extract_capture_response(capture_payload, "SelDeptSaleList")
    if not body or body.get("errcode") != "1000":
        return None

    payload = (body.get("retdata") or [{}])[0]
    rows = payload.get("Data") or []
    if not rows:
        return None

    numeric_columns = ["RetailPrice", "TotalMoney", "TotalNum", "TotalRetailMoney", "Discount"]
    numeric_columns.extend(column for column in rows[0].keys() if str(column).startswith("col"))
    frame = normalize_yeusoft_frame(pd.DataFrame(rows), numeric_columns)
    if frame.empty or "TotalMoney" not in frame.columns:
        return None

    for column in ("Type", "Type1", "Type2", "Years", "Season", "WareName", "Spec", "ColorName"):
        if column in frame.columns:
            frame[column] = frame[column].replace("", "未标记").fillna("未标记")

    props = frame[frame["Type"].eq("道具")].copy() if "Type" in frame.columns else pd.DataFrame()
    normal = frame[frame["Type"].ne("道具")].copy() if "Type" in frame.columns else frame.copy()
    normal = normal[normal["TotalMoney"] > 0].copy()
    if normal.empty:
        return None

    total_sales = float(normal["TotalMoney"].sum())
    total_retail = float(normal["TotalRetailMoney"].sum())
    weighted_discount = safe_ratio(total_sales, total_retail)
    normal["deep_discount_sales"] = normal["TotalMoney"].where(normal["Discount"] < 0.75, 0.0)
    deep_discount_sales_share = safe_ratio(normal["deep_discount_sales"].sum(), total_sales)

    category_frame = (
        normal.groupby("Type1", dropna=False)
        .agg(
            sales_amount=("TotalMoney", "sum"),
            retail_amount=("TotalRetailMoney", "sum"),
            deep_discount_sales=("deep_discount_sales", "sum"),
        )
        .reset_index()
    )
    category_frame = category_frame[category_frame["sales_amount"] > 0].copy()
    if category_frame.empty:
        return None
    category_frame["discount_rate"] = category_frame.apply(
        lambda row: safe_ratio(row["sales_amount"], row["retail_amount"]), axis=1
    )
    category_frame["deep_discount_share"] = category_frame.apply(
        lambda row: safe_ratio(row["deep_discount_sales"], row["sales_amount"]), axis=1
    )
    category_frame = category_frame.sort_values(["deep_discount_share", "sales_amount"], ascending=[False, False])
    top_discount_categories = [
        {
            "name": row["Type1"] or "未标记中类",
            "sales_amount": float(row["sales_amount"]),
            "discount_rate": float(row["discount_rate"]),
            "deep_discount_share": float(row["deep_discount_share"]),
        }
        for _, row in category_frame.head(5).iterrows()
        if float(row["sales_amount"]) >= 10000
    ]

    size_labels = extract_retail_detail_size_labels(payload)
    size_columns = [column for column in frame.columns if str(column).startswith("col")]
    size_rows: list[dict[str, object]] = []
    total_size_qty = 0.0
    if size_columns:
        size_totals = normal[size_columns].sum().sort_values(ascending=False)
        total_size_qty = float(size_totals.sum())
        for column, qty in size_totals.items():
            if qty <= 0:
                continue
            size_rows.append(
                {
                    "name": size_labels.get(column, column),
                    "qty": float(qty),
                    "share": safe_ratio(qty, total_size_qty),
                }
            )
    core_size_names = "、".join(row["name"] for row in size_rows[:3]) if size_rows else "主销尺码待确认"

    price_band_rows: list[dict[str, object]] = []
    if "RetailPrice" in normal.columns:
        price_frame = normal[normal["RetailPrice"] > 0].copy()
        if not price_frame.empty:
            price_bins = [0, 39, 59, 79, 99, 149, float("inf")]
            price_labels = ["39元以下", "40-59元", "60-79元", "80-99元", "100-149元", "150元以上"]
            price_frame["price_band"] = pd.cut(
                price_frame["RetailPrice"],
                bins=price_bins,
                labels=price_labels,
                include_lowest=True,
                right=True,
            )
            grouped = (
                price_frame.groupby("price_band", dropna=False, observed=False)["TotalMoney"]
                .sum()
                .sort_values(ascending=False)
            )
            price_band_rows = [
                {
                    "name": str(index),
                    "sales_amount": float(value),
                    "share": safe_ratio(value, total_sales),
                }
                for index, value in grouped.items()
                if pd.notna(index) and float(value) > 0
            ]

    request_payload = extract_capture_request(capture_payload, "SelDeptSaleList") or {}
    discount_category_names = (
        "、".join(item["name"] for item in top_discount_categories[:3])
        if top_discount_categories
        else "暂无明显折扣依赖中类"
    )
    top_price_band = price_band_rows[0]["name"] if price_band_rows else "主价格带待确认"
    markdown_pressure_high = weighted_discount < 0.78 or deep_discount_sales_share >= 0.45

    return {
        "capture_at": pd.to_datetime(capture_payload.get("capturedAt"), errors="coerce"),
        "window_start": parse_yeusoft_request_date(request_payload.get("bdate")),
        "window_end": parse_yeusoft_request_date(request_payload.get("edate")),
        "row_count": int(len(normal)),
        "sales_amount": total_sales,
        "retail_amount": total_retail,
        "weighted_discount_rate": weighted_discount,
        "deep_discount_sales_share": deep_discount_sales_share,
        "markdown_pressure_high": markdown_pressure_high,
        "top_discount_categories": top_discount_categories,
        "discount_category_names": discount_category_names,
        "size_rows": size_rows[:6],
        "core_size_names": core_size_names,
        "top_size_share": size_rows[0]["share"] if size_rows else 0.0,
        "price_band_rows": price_band_rows[:6],
        "top_price_band": top_price_band,
        "props_sales_amount": float(props["TotalMoney"].sum()) if not props.empty else 0.0,
        "props_sales_share": safe_ratio(float(props["TotalMoney"].sum()), float(frame["TotalMoney"].sum())),
    }


def build_yeusoft_report_highlights(
    capture_bundle: dict[str, dict], current_season: str, next_season: str
) -> dict | None:
    if not capture_bundle:
        return None

    sales_overview = parse_yeusoft_sales_overview(capture_bundle.get("销售清单"))
    product_sales = parse_yeusoft_product_sales(
        capture_bundle.get("商品销售情况"), current_season, next_season
    )
    member_rank = parse_yeusoft_member_rank(capture_bundle.get("会员消费排行"))
    stock_analysis = parse_yeusoft_stock_analysis(
        capture_bundle.get("库存综合分析"), current_season, next_season
    )
    movement = parse_yeusoft_movement_report(capture_bundle.get("出入库单据"))
    daily_flow = parse_yeusoft_daily_flow(capture_bundle.get("每日流水单"))
    category_analysis = parse_yeusoft_category_analysis(capture_bundle.get("商品品类分析"))
    vip_analysis = parse_yeusoft_vip_analysis(capture_bundle.get("会员综合分析"))
    guide_report = parse_yeusoft_guide_report(capture_bundle.get("导购员报表"))
    store_month_report = parse_yeusoft_monthly_sales_report(capture_bundle.get("门店销售月报"))
    retail_detail = parse_yeusoft_retail_detail(capture_bundle.get("零售明细统计"))

    capture_dates = [
        value.get("capture_at")
        for value in (
            sales_overview,
            product_sales,
            member_rank,
            stock_analysis,
            movement,
            daily_flow,
            category_analysis,
            vip_analysis,
            guide_report,
            store_month_report,
            retail_detail,
        )
        if value and pd.notna(value.get("capture_at"))
    ]

    return {
        "sales_overview": sales_overview,
        "product_sales": product_sales,
        "member_rank": member_rank,
        "stock_analysis": stock_analysis,
        "movement": movement,
        "daily_flow": daily_flow,
        "category_analysis": category_analysis,
        "vip_analysis": vip_analysis,
        "guide_report": guide_report,
        "store_month_report": store_month_report,
        "retail_detail": retail_detail,
        "capture_at": max(capture_dates) if capture_dates else pd.NaT,
    }



def normalize_product_season(value: object) -> str:
    text = str(value or "").strip()
    for season in ("春", "夏", "秋", "冬"):
        if season in text:
            return season
    return "未知"


def classify_season_action(current_season: str, next_season: str, product_season: str) -> str:
    if product_season == current_season:
        return "当季主推"
    if product_season == next_season:
        return "下一季试补"

    clear_map = {
        "春": {"冬"},
        "夏": {"冬", "春"},
        "秋": {"春", "夏"},
        "冬": {"夏", "秋"},
    }
    if product_season in clear_map.get(current_season, set()):
        return "跨季去化"
    return "暂缓补货"

