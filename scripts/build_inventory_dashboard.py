#!/usr/bin/env python3
"""Build a non-technical inventory and sales dashboard from exported reports."""

from __future__ import annotations

import argparse
import math
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = ROOT / "data" / "inventory_zip_extract"
DEFAULT_OUTPUT_DIR = ROOT / "reports" / "inventory_dashboard"
BEIJING_TZ = ZoneInfo("Asia/Shanghai")


@dataclass
class ReportFiles:
    sales_detail: Path
    inventory_detail: Path
    inventory_sales: Path
    stock_flow: Path
    guide_report: Path
    member_report: Path
    product_sales: Path
    movement_report: Path
    store_retail_report: Path | None = None


def pick_file(input_dir: Path, exact_name: str) -> Path:
    exact = input_dir / exact_name
    if exact.exists():
        return exact

    stem = Path(exact_name).stem
    suffix = Path(exact_name).suffix
    candidates = sorted(input_dir.glob(f"{stem}*{suffix}"))
    if not candidates:
        raise FileNotFoundError(f"Missing required file for pattern: {exact_name}")
    return candidates[0]


def choose_preferred(candidates: list[Path]) -> Path:
    unsuffixed = [p for p in candidates if " (" not in p.stem]
    pool = unsuffixed or candidates
    return sorted(pool, key=lambda p: (len(p.name), p.name))[0]


def pick_by_keywords(
    input_dir: Path,
    *,
    keywords: list[str],
    suffixes: tuple[str, ...] = (".xlsx", ".xls"),
    required_columns: list[str] | None = None,
) -> Path:
    candidates = []
    for path in input_dir.iterdir():
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        if all(keyword in path.name for keyword in keywords):
            candidates.append(path)

    if not candidates:
        raise FileNotFoundError(f"Missing required file for keywords: {keywords}")

    if required_columns:
        matched = []
        for path in candidates:
            try:
                sample = pd.read_excel(path, nrows=2)
                if all(column in sample.columns for column in required_columns):
                    matched.append(path)
            except Exception:
                continue
        if matched:
            candidates = matched

    return choose_preferred(candidates)


def resolve_reports(input_dir: Path) -> ReportFiles:
    store_retail_report = None
    try:
        store_retail_report = pick_by_keywords(input_dir, keywords=["店铺零售清单"])
    except FileNotFoundError:
        store_retail_report = None

    return ReportFiles(
        sales_detail=pick_by_keywords(input_dir, keywords=["销售清单"]),
        inventory_detail=pick_by_keywords(
            input_dir,
            keywords=["库存明细统计"],
            required_columns=["店铺", "款号", "颜色", "尺码", "库存", "库存额"],
        ),
        inventory_sales=pick_by_keywords(input_dir, keywords=["库存零售统计"]),
        stock_flow=pick_by_keywords(input_dir, keywords=["进销存统计"]),
        guide_report=pick_by_keywords(input_dir, keywords=["导购员报表"]),
        member_report=pick_by_keywords(input_dir, keywords=["会员综合分析"]),
        product_sales=pick_by_keywords(input_dir, keywords=["商品销售情况"]),
        movement_report=pick_by_keywords(input_dir, keywords=["出入库单据"]),
        store_retail_report=store_retail_report,
    )


def to_numeric(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    for col in columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df


def load_data(files: ReportFiles) -> dict[str, pd.DataFrame]:
    sales = pd.read_excel(files.sales_detail)
    inventory_detail = pd.read_excel(files.inventory_detail)
    inventory_sales = pd.read_excel(files.inventory_sales)
    stock_flow = pd.read_excel(files.stock_flow)
    guide = pd.read_excel(files.guide_report)
    members = pd.read_excel(files.member_report)
    product_sales = pd.read_excel(files.product_sales)
    movement = pd.read_excel(files.movement_report)
    store_retail = pd.read_excel(files.store_retail_report) if files.store_retail_report else pd.DataFrame()

    sales["销售日期"] = pd.to_datetime(sales["销售日期"], errors="coerce")
    sales = to_numeric(sales, ["数量", "金额", "吊牌金额", "单价", "折扣"])

    inventory_detail = to_numeric(
        inventory_detail, ["库存", "库存额", "在途库存", "在途库存额", "零售价"]
    )
    inventory_sales = to_numeric(
        inventory_sales, ["零售小计", "零售金额", "库存小计", "库存金额", "存销比", "零售价"]
    )
    stock_flow = to_numeric(
        stock_flow,
        [
            "期初数量",
            "到货数量",
            "调入数量",
            "退货数量",
            "调出数量",
            "零售数量",
            "报损数量",
            "在途库存",
            "实际库存",
            "账面库存",
            "动销率",
            "零售价",
        ],
    )
    guide = to_numeric(
        guide, ["销量", "实收金额", "票数", "单效", "连带", "会员销额", "会员销量"]
    )
    members = to_numeric(
        members, ["购买金额", "购买总数", "消费次数/年", "平均单笔消费额", "储值余额"]
    )
    product_sales = to_numeric(
        product_sales,
        ["销售数", "销售金额", "累销", "累销额", "总到货", "周期售罄", "总售罄", "库存", "总退货", "已销天"],
    )
    for col in ["首次到货日期", "首次销售日期"]:
        if col in product_sales.columns:
            product_sales[col] = pd.to_datetime(product_sales[col], errors="coerce")
    movement["发货时间"] = pd.to_datetime(movement["发货时间"], errors="coerce")
    movement = to_numeric(movement, ["数量", "吊牌金额"])
    if not store_retail.empty:
        if "销售日期" in store_retail.columns:
            store_retail["销售日期"] = pd.to_datetime(store_retail["销售日期"], errors="coerce")
        store_retail = to_numeric(store_retail, ["数量", "金额", "吊牌金额", "单价", "折扣"])

    return {
        "sales": sales,
        "inventory_detail": inventory_detail,
        "inventory_sales": inventory_sales,
        "stock_flow": stock_flow,
        "guide": guide,
        "members": members,
        "product_sales": product_sales,
        "movement": movement,
        "store_retail": store_retail,
    }


def infer_store_name(data: dict[str, pd.DataFrame], preferred_store: str | None) -> str:
    if preferred_store:
        return preferred_store

    sales = data["sales"]
    if "店铺名称" in sales.columns and not sales["店铺名称"].dropna().empty:
        return sales["店铺名称"].dropna().mode().iloc[0]

    inventory_detail = data["inventory_detail"]
    return inventory_detail["店铺"].dropna().mode().iloc[0]


def clean_data(data: dict[str, pd.DataFrame], store_name: str) -> dict[str, pd.DataFrame]:
    cleaned = dict(data)
    cleaned["sales"] = data["sales"][data["sales"]["店铺名称"].eq(store_name)].copy()
    cleaned["inventory_detail"] = data["inventory_detail"][
        data["inventory_detail"]["店铺"].eq(store_name)
    ].copy()
    cleaned["inventory_sales"] = data["inventory_sales"][
        data["inventory_sales"]["店铺名称"].eq(store_name)
    ].copy()
    cleaned["guide"] = data["guide"][data["guide"]["导购员"].ne("合计")].copy()
    cleaned["members"] = data["members"][
        data["members"]["VIP姓名"].notna() & data["members"]["VIP姓名"].ne("合计")
    ].copy()
    cleaned["movement"] = data["movement"][
        data["movement"]["接收店铺"].eq(store_name)
    ].copy()
    if "store_retail" in data and not data["store_retail"].empty:
        store_retail = data["store_retail"].copy()
        if "输入人" in store_retail.columns:
            store_retail["输入人"] = store_retail["输入人"].fillna("未标记").astype(str).str.strip()
        if "店铺名称" in store_retail.columns:
            store_retail["店铺名称"] = store_retail["店铺名称"].fillna("未标记店铺").astype(str).str.strip()
        cleaned["store_retail"] = store_retail
    else:
        cleaned["store_retail"] = pd.DataFrame()
    return cleaned


def safe_ratio(num: float, denom: float) -> float:
    if not denom:
        return 0.0
    return float(num) / float(denom)


def format_num(value: float | int, digits: int = 0) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    return f"{value:,.{digits}f}"


def find_week_columns(df: pd.DataFrame) -> list[str]:
    preferred = [f"{i}周" for i in range(1, 9)]
    return [col for col in preferred if col in df.columns]


def get_beijing_now() -> datetime:
    return datetime.now(BEIJING_TZ)


def infer_season(now: datetime) -> tuple[str, str, str]:
    month = now.month
    day = now.day

    if month in (3, 4, 5):
        if day <= 10:
            return "春季", "春季上新期", "夏季"
        if day <= 20:
            return "春季", "春夏换季期", "夏季"
        return "春季", "夏季预热期", "夏季"
    if month in (6, 7, 8):
        if day <= 10:
            return "夏季", "夏季起量期", "秋季"
        if day <= 20:
            return "夏季", "夏季主销期", "秋季"
        return "夏季", "秋季预热期", "秋季"
    if month in (9, 10, 11):
        if day <= 10:
            return "秋季", "秋季上新期", "冬季"
        if day <= 20:
            return "秋季", "秋冬换季期", "冬季"
        return "秋季", "冬季预热期", "冬季"
    if day <= 10:
        return "冬季", "冬季起量期", "春季"
    if day <= 20:
        return "冬季", "冬季主销期", "春季"
    return "冬季", "春季预热期", "春季"


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


def label_category_health(ratio: float) -> str:
    if ratio >= 3:
        return "高压货"
    if ratio >= 1.5:
        return "需关注"
    return "相对健康"


def metric_health(level: str, title: str, value: str, note: str) -> dict[str, str]:
    return {"level": level, "title": title, "value": value, "note": note}


def build_health_lights(cards: dict, actions: dict) -> list[dict[str, str]]:
    inventory_days = cards["estimated_inventory_days"]
    negative_sku = cards["negative_sku_count"]
    high_risk_categories = actions["high_risk_category_count"]
    replenish_count = actions["replenish_count"]
    member_ratio = cards["member_sales_ratio"]

    if inventory_days >= 180:
        inventory_level = metric_health("red", "库存压力", f"{format_num(inventory_days, 1)} 天", "库存覆盖偏长，先控补货再做去化")
    elif inventory_days >= 90:
        inventory_level = metric_health("yellow", "库存压力", f"{format_num(inventory_days, 1)} 天", "库存偏重，建议控制进货节奏")
    else:
        inventory_level = metric_health("green", "库存压力", f"{format_num(inventory_days, 1)} 天", "库存覆盖相对健康")

    if negative_sku >= 50:
        accuracy_level = metric_health("red", "库存准确性", format_num(negative_sku), "负库存较多，先校库存再做经营判断")
    elif negative_sku > 0:
        accuracy_level = metric_health("yellow", "库存准确性", format_num(negative_sku), "有负库存异常，建议尽快纠偏")
    else:
        accuracy_level = metric_health("green", "库存准确性", format_num(negative_sku), "库存口径较干净")

    if high_risk_categories >= 2:
        category_level = metric_health("red", "压货风险", format_num(high_risk_categories), "高压货品类较多，先看去化和停补")
    elif high_risk_categories == 1:
        category_level = metric_health("yellow", "压货风险", format_num(high_risk_categories), "已有压货品类，建议重点跟踪")
    else:
        category_level = metric_health("green", "压货风险", format_num(high_risk_categories), "压货品类数量可控")

    if replenish_count >= 200:
        replenish_level = metric_health("red", "缺货风险", format_num(replenish_count), "建议补货 SKU 偏多，畅销货有断货风险")
    elif replenish_count >= 80:
        replenish_level = metric_health("yellow", "缺货风险", format_num(replenish_count), "部分畅销款补货压力较高")
    else:
        replenish_level = metric_health("green", "缺货风险", format_num(replenish_count), "补货压力相对可控")

    if member_ratio >= 0.7:
        member_level = metric_health("green", "会员经营", f"{format_num(member_ratio * 100, 1)}%", "会员贡献高，适合继续做复购经营")
    elif member_ratio >= 0.4:
        member_level = metric_health("yellow", "会员经营", f"{format_num(member_ratio * 100, 1)}%", "会员贡献中等，还有提升空间")
    else:
        member_level = metric_health("red", "会员经营", f"{format_num(member_ratio * 100, 1)}%", "会员贡献偏低，建议加强沉淀和复购")

    return [inventory_level, accuracy_level, category_level, replenish_level, member_level]


def build_metrics(data: dict[str, pd.DataFrame], store_name: str) -> dict:
    now = get_beijing_now()
    current_season_name, phase_name, next_season_name = infer_season(now)
    current_season_key = current_season_name[0]
    next_season_key = next_season_name[0]

    sales = data["sales"].copy()
    inventory_detail = data["inventory_detail"].copy()
    inventory_sales = data["inventory_sales"].copy()
    stock_flow = data["stock_flow"].copy()
    guide = data["guide"].copy()
    members = data["members"].copy()
    product_sales = data["product_sales"].copy()
    movement = data["movement"].copy()
    store_retail = data.get("store_retail", pd.DataFrame()).copy()
    stock_flow = stock_flow[stock_flow["商品款号"].notna()].copy()
    stock_flow["近期零售"] = stock_flow["零售数量"].abs()
    stock_flow["动销率"] = stock_flow.apply(
        lambda row: safe_ratio(row["近期零售"], row["实际库存"]) if row["实际库存"] > 0 else 0.0,
        axis=1,
    )

    sales_no_props = sales[sales["商品大类"].ne("道具")].copy()
    sales_props = sales[sales["商品大类"].eq("道具")].copy()
    inventory_no_props = inventory_detail[inventory_detail["大类"].ne("道具")].copy()
    inventory_props = inventory_detail[inventory_detail["大类"].eq("道具")].copy()
    inventory_sales_no_props = inventory_sales[inventory_sales["大类"].ne("道具")].copy()
    product_sales = product_sales[product_sales["款号"].notna()].copy()
    product_sales = product_sales[product_sales["款号"].astype(str).str.strip().ne("合计")].copy()
    product_sales_no_props = product_sales[product_sales["中类"].ne("道具")].copy()
    product_sales_props = product_sales[product_sales["中类"].eq("道具")].copy()
    sales_no_props["导购员"] = sales_no_props["导购员"].fillna("未分配").astype(str).str.strip()
    product_sales_no_props["季节归一"] = product_sales_no_props["季节"].apply(normalize_product_season)
    product_sales_no_props["季节策略"] = product_sales_no_props["季节归一"].apply(
        lambda season: classify_season_action(current_season_key, next_season_key, season)
    )

    sales_orders = sales_no_props["零售单号"].nunique()
    member_sales_no_props = sales_no_props.loc[sales_no_props["会员卡号"].notna(), "金额"].sum()

    sales_days = (
        (sales_no_props["销售日期"].max().normalize() - sales_no_props["销售日期"].min().normalize()).days + 1
        if not sales_no_props.empty
        else 0
    )

    summary_cards = {
        "store_name": store_name,
        "sales_amount": float(sales_no_props["金额"].sum()),
        "sales_qty": float(sales_no_props["数量"].sum()),
        "sales_orders": int(sales_orders),
        "sales_days": int(sales_days),
        "avg_order_value": safe_ratio(sales_no_props["金额"].sum(), sales_orders),
        "items_per_order": safe_ratio(sales_no_props["数量"].sum(), sales_orders),
        "member_sales_ratio": safe_ratio(member_sales_no_props, sales_no_props["金额"].sum()),
        "sales_detail_start": sales_no_props["销售日期"].min(),
        "sales_detail_end": sales_no_props["销售日期"].max(),
        "inventory_qty": float(inventory_no_props["库存"].sum()),
        "inventory_amount": float(inventory_no_props["库存额"].sum()),
        "negative_sku_count": int((inventory_no_props["库存"] < 0).sum()),
        "negative_inventory_amount": float(
            inventory_no_props.loc[inventory_no_props["库存"] < 0, "库存额"].sum()
        ),
        "daily_sales_amount": safe_ratio(sales_no_props["金额"].sum(), sales_days),
        "daily_sales_qty": safe_ratio(sales_no_props["数量"].sum(), sales_days),
        "estimated_inventory_days": safe_ratio(
            inventory_no_props["库存"].sum(),
            safe_ratio(sales_no_props["数量"].sum(), sales_days),
        ),
        "props_sales_amount": float(sales_props["金额"].sum()),
        "props_sales_qty": float(sales_props["数量"].sum()),
        "props_sales_orders": int(sales_props["零售单号"].nunique()),
        "props_inventory_qty": float(inventory_props["库存"].sum()),
        "props_inventory_amount": float(inventory_props["库存额"].sum()),
        "receipt_qty": float(movement["数量"].sum()),
        "receipt_records": int(len(movement)),
        "member_count": int(len(members)),
        "member_amount_sum": float(members["购买金额"].sum()),
        "cumulative_sales_qty": float(product_sales_no_props["累销"].sum()),
        "cumulative_sales_amount": float(product_sales_no_props["累销额"].sum()),
        "cumulative_receipt_qty": float(product_sales_no_props["总到货"].sum()),
        "historical_stock_qty": float(product_sales_no_props["库存"].sum()),
        "history_first_arrival": product_sales_no_props["首次到货日期"].min(),
        "history_first_sale": product_sales_no_props["首次销售日期"].min(),
        "props_cumulative_sales_qty": float(product_sales_props["累销"].sum()),
        "props_cumulative_sales_amount": float(product_sales_props["累销额"].sum()),
        "current_season_name": current_season_name,
        "phase_name": phase_name,
        "next_season_name": next_season_name,
    }

    sales_daily = (
        sales_no_props.groupby(sales_no_props["销售日期"].dt.date)
        .agg(销售额=("金额", "sum"), 销量=("数量", "sum"), 订单数=("零售单号", "nunique"))
        .reset_index()
        .rename(columns={"销售日期": "日期"})
    )

    sales_by_category = (
        sales.groupby("商品大类")
        .agg(销售额=("金额", "sum"), 销量=("数量", "sum"), 订单数=("零售单号", "nunique"))
        .sort_values("销售额", ascending=False)
        .reset_index()
    )

    sales_by_category_ex_props = (
        sales_no_props.groupby("商品大类")
        .agg(销售额=("金额", "sum"), 销量=("数量", "sum"), 订单数=("零售单号", "nunique"))
        .sort_values("销售额", ascending=False)
        .reset_index()
    )

    inventory_by_category = (
        inventory_no_props.groupby("大类")
        .agg(库存量=("库存", "sum"), 库存额=("库存额", "sum"), 在途库存=("在途库存", "sum"))
        .sort_values("库存额", ascending=False)
        .reset_index()
    )

    stock_sales_ratio = (
        inventory_sales_no_props.groupby("大类")
        .agg(零售额=("零售金额", "sum"), 库存额=("库存金额", "sum"), 零售量=("零售小计", "sum"), 库存量=("库存小计", "sum"))
        .reset_index()
    )
    stock_sales_ratio["库存金额/销售金额"] = stock_sales_ratio.apply(
        lambda row: safe_ratio(row["库存额"], row["零售额"]), axis=1
    )
    stock_sales_ratio["库存量/销售量"] = stock_sales_ratio.apply(
        lambda row: safe_ratio(row["库存量"], row["零售量"]), axis=1
    )
    stock_sales_ratio = stock_sales_ratio.sort_values("库存额", ascending=False)

    guide_perf = (
        sales_no_props.groupby("导购员")
        .agg(实收金额=("金额", "sum"), 票数=("零售单号", "nunique"), 销量=("数量", "sum"))
        .reset_index()
    )
    guide_member = (
        sales_no_props[sales_no_props["会员卡号"].notna()]
        .groupby("导购员")
        .agg(会员销额=("金额", "sum"))
        .reset_index()
    )
    guide_perf = guide_perf.merge(guide_member, on="导购员", how="left").fillna({"会员销额": 0})
    guide_perf["单效"] = guide_perf.apply(lambda row: safe_ratio(row["实收金额"], row["票数"]), axis=1)
    guide_perf["连带"] = guide_perf.apply(lambda row: safe_ratio(row["销量"], row["票数"]), axis=1)
    guide_perf = guide_perf[["导购员", "实收金额", "票数", "单效", "连带", "会员销额"]].sort_values(
        "实收金额", ascending=False
    )

    top_members = members[
        ["VIP姓名", "服务导购", "购买金额", "购买总数", "消费次数/年", "平均单笔消费额", "储值余额"]
    ].sort_values("购买金额", ascending=False)

    primary_input = "郭文攀"
    if not store_retail.empty and {"输入人", "店铺名称", "零售单号", "金额", "数量"}.issubset(store_retail.columns):
        retail_reference = (
            store_retail[store_retail["输入人"].ne("未标记")]
            .groupby(["输入人", "店铺名称"])
            .agg(
                销售额=("金额", "sum"),
                销量=("数量", "sum"),
                订单数=("零售单号", "nunique"),
            )
            .reset_index()
            .sort_values(["销售额", "订单数"], ascending=[False, False])
        )
        primary_reference = retail_reference[retail_reference["输入人"].eq(primary_input)].head(1)
        other_references = retail_reference[retail_reference["输入人"].ne(primary_input)].head(8)
    else:
        retail_reference = pd.DataFrame()
        primary_reference = pd.DataFrame()
        other_references = pd.DataFrame()

    negative_inventory = inventory_no_props[inventory_no_props["库存"] < 0][
        ["款号", "品名", "颜色", "尺码", "库存", "库存额", "大类", "小类"]
    ].sort_values("库存额")

    low_stock_bestsellers = product_sales_no_props[
        (product_sales_no_props["销售数"] >= 3) & (product_sales_no_props["库存"] <= 2)
    ][["款号", "颜色", "销售数", "销售金额", "库存", "周期售罄", "中类", "季节"]].sort_values(
        ["销售金额", "周期售罄"], ascending=[False, False]
    )

    slow_moving = stock_flow[
        (stock_flow["大类"].ne("道具")) & (stock_flow["实际库存"] >= 10) & (stock_flow["近期零售"] <= 1)
    ][["商品款号", "商品名称", "大类", "中类", "小类", "实际库存", "近期零售", "动销率", "零售价"]].sort_values(
        ["实际库存", "零售价"], ascending=[False, False]
    )

    category_risks = stock_sales_ratio[
        ["大类", "零售额", "库存额", "库存金额/销售金额", "库存量/销售量"]
    ].sort_values("库存金额/销售金额", ascending=False)
    category_risks["状态"] = category_risks["库存金额/销售金额"].apply(label_category_health)

    week_cols = find_week_columns(product_sales_no_props)
    if week_cols:
        product_sales_no_props["近8周销量"] = product_sales_no_props[week_cols].sum(axis=1)
        product_sales_no_props["周均销量"] = product_sales_no_props["近8周销量"] / len(week_cols)
    else:
        product_sales_no_props["近8周销量"] = product_sales_no_props["销售数"]
        product_sales_no_props["周均销量"] = product_sales_no_props["销售数"]

    product_sales_no_props["库存周数"] = product_sales_no_props.apply(
        lambda row: safe_ratio(row["库存"], row["周均销量"]), axis=1
    )
    product_sales_no_props["建议补货量"] = (
        (product_sales_no_props["周均销量"] * 4).round().clip(lower=0) - product_sales_no_props["库存"]
    ).clip(lower=0)
    product_sales_no_props["补货候选"] = (
        (product_sales_no_props["销售数"] >= 3)
        & (product_sales_no_props["周均销量"] >= 0.5)
        & (product_sales_no_props["建议补货量"] >= 1)
        & ((product_sales_no_props["库存"] <= 2) | (product_sales_no_props["库存周数"] <= 2))
    )

    replenish = product_sales_no_props[
        product_sales_no_props["补货候选"]
        & (product_sales_no_props["季节策略"].isin(["当季主推", "下一季试补"]))
    ][
        ["款号", "颜色", "中类", "季节", "季节策略", "销售数", "销售金额", "库存", "周均销量", "库存周数", "建议补货量"]
    ].copy()
    replenish["建议动作"] = replenish.apply(
        lambda row: (
            "小量试补"
            if row["季节策略"] == "下一季试补"
            else ("立即补货" if row["库存周数"] <= 1 else "优先补货")
        ),
        axis=1,
    )
    replenish.loc[replenish["库存"] < 0, "建议动作"] = "先校库存再补货"
    replenish = replenish.sort_values(
        ["销售金额", "库存周数", "库存"], ascending=[False, True, True]
    )

    seasonal_actions = product_sales_no_props[
        (product_sales_no_props["季节策略"].isin(["跨季去化", "暂缓补货"]))
        & (product_sales_no_props["补货候选"] | (product_sales_no_props["库存"] >= 10))
    ][
        ["款号", "颜色", "中类", "季节", "季节策略", "销售数", "销售金额", "库存", "周均销量", "库存周数"]
    ].copy()
    seasonal_actions["建议动作"] = seasonal_actions.apply(
        lambda row: (
            "优先去化"
            if row["季节策略"] == "跨季去化" and row["库存"] > 0
            else ("跨季不补货" if row["季节策略"] == "跨季去化" else "暂缓补货")
        ),
        axis=1,
    )
    seasonal_actions["季节策略优先级"] = seasonal_actions["季节策略"].map(
        {"跨季去化": 0, "暂缓补货": 1}
    ).fillna(9)
    seasonal_actions = seasonal_actions.sort_values(
        ["季节策略优先级", "库存", "销售金额"], ascending=[True, False, False]
    ).drop(columns=["季节策略优先级"])

    clearance = stock_flow[
        (stock_flow["商品款号"].notna())
        & (stock_flow["大类"].ne("道具"))
        & (stock_flow["实际库存"] >= 10)
        & ((stock_flow["近期零售"] <= 1) | (stock_flow["动销率"] <= 0.1))
    ][
        ["商品款号", "商品名称", "大类", "中类", "小类", "实际库存", "近期零售", "动销率", "零售价"]
    ].copy()
    clearance["建议动作"] = clearance["实际库存"].apply(
        lambda x: "先停补再去化" if x >= 20 else "观察并做组合去化"
    )
    clearance = clearance.sort_values(["实际库存", "零售价"], ascending=[False, False])

    action_summary = {
        "replenish_count": int(len(replenish)),
        "seasonal_hold_count": int(len(seasonal_actions)),
        "clearance_count": int(len(clearance)),
        "high_risk_category_count": int((category_risks["状态"] == "高压货").sum()),
    }

    insights = [
        f"近 {summary_cards['sales_days']} 天门店经营销售额为 {format_num(summary_cards['sales_amount'], 2)} 元，"
        f"客单价约 {format_num(summary_cards['avg_order_value'], 2)} 元。",
        f"当前日销趋势来自销售清单，时间范围是 {summary_cards['sales_detail_start'].strftime('%Y-%m-%d')} 到 "
        f"{summary_cards['sales_detail_end'].strftime('%Y-%m-%d')}；所以趋势图只反映最近 {summary_cards['sales_days']} 天。",
        f"历史累计口径在商品销售情况里可以看到，自 {summary_cards['history_first_sale'].strftime('%Y-%m-%d')} 以来累计销售额约 "
        f"{format_num(summary_cards['cumulative_sales_amount'], 2)} 元。",
        f"当前账面库存 {format_num(summary_cards['inventory_qty'])} 件，零售价口径库存额约 {format_num(summary_cards['inventory_amount'], 2)} 元；"
        f"库存覆盖天数约 {format_num(summary_cards['estimated_inventory_days'], 1)} 天。",
        f"会员销售额占比约 {format_num(summary_cards['member_sales_ratio'] * 100, 1)}%，说明会员经营已经是核心收入来源。",
        f"存在 {summary_cards['negative_sku_count']} 个负库存 SKU，负库存金额合计 {format_num(summary_cards['negative_inventory_amount'], 2)} 元，"
        "这部分需要优先纠偏，不然补货和动销判断会失真。",
        f"道具已从主经营口径里单独剥离；当前仅作为参考值显示，道具销售额约 {format_num(summary_cards['props_sales_amount'], 2)} 元，"
        f"道具库存额约 {format_num(summary_cards['props_inventory_amount'], 2)} 元。",
        f"当前筛出 {action_summary['replenish_count']} 个建议优先补货的 SKU，"
        f"{action_summary['seasonal_hold_count']} 个跨季不建议补货、应转去化或暂缓的 SKU，"
        f"{action_summary['clearance_count']} 个建议先去化的高库存低动销 SKU。",
    ]
    if not primary_reference.empty:
        row = primary_reference.iloc[0]
        insights.append(
            f"店铺零售清单已按输入人区分参考店铺；主逻辑只关注 {primary_input} / {row['店铺名称']}，"
            f"其余输入人仅作为参考对比。"
        )

    return {
        "summary_cards": summary_cards,
        "sales_daily": sales_daily,
        "sales_by_category": sales_by_category,
        "sales_by_category_ex_props": sales_by_category_ex_props,
        "inventory_by_category": inventory_by_category,
        "stock_sales_ratio": stock_sales_ratio,
        "guide_perf": guide_perf,
        "top_members": top_members,
        "primary_input": primary_input,
        "primary_reference": primary_reference,
        "other_references": other_references,
        "negative_inventory": negative_inventory,
        "low_stock_bestsellers": low_stock_bestsellers,
        "slow_moving": slow_moving,
        "category_risks": category_risks,
        "replenish": replenish,
        "seasonal_actions": seasonal_actions,
        "clearance": clearance,
        "action_summary": action_summary,
        "insights": insights,
    }


def fig_to_html(fig: go.Figure, include_js: bool = False) -> str:
    return fig.to_html(full_html=False, include_plotlyjs="cdn" if include_js else False)


def build_charts(metrics: dict) -> list[str]:
    charts: list[str] = []

    daily = metrics["sales_daily"]
    if not daily.empty:
        fig = px.line(
            daily,
            x="日期",
            y="销售额",
            markers=True,
            title="每日经营销售额走势（已剔除道具）",
            text="订单数",
        )
        fig.update_traces(textposition="top center")
        fig.update_layout(height=420, margin=dict(l=20, r=20, t=60, b=20))
        charts.append(fig_to_html(fig, include_js=True))

    cat_sales = metrics["sales_by_category_ex_props"].head(8)
    if not cat_sales.empty:
        fig = px.bar(
            cat_sales,
            x="商品大类",
            y="销售额",
            color="销量",
            title="经营销售额最高的品类（已剔除道具）",
            text_auto=".2s",
        )
        fig.update_layout(height=420, margin=dict(l=20, r=20, t=60, b=20))
        charts.append(fig_to_html(fig))

    cat_inv = metrics["inventory_by_category"].head(10)
    if not cat_inv.empty:
        fig = px.bar(
            cat_inv,
            x="大类",
            y="库存额",
            color="库存量",
            title="经营库存金额最高的品类（已剔除道具）",
            text_auto=".2s",
        )
        fig.update_layout(height=420, margin=dict(l=20, r=20, t=60, b=20))
        charts.append(fig_to_html(fig))

    ratio = metrics["category_risks"].head(10)
    if not ratio.empty:
        fig = px.scatter(
            ratio,
            x="零售额",
            y="库存额",
            size="库存金额/销售金额",
            color="大类",
            hover_data=["库存金额/销售金额", "库存量/销售量"],
            title="经营品类库存额 vs 销售额（已剔除道具）",
        )
        fig.update_layout(height=440, margin=dict(l=20, r=20, t=60, b=20))
        charts.append(fig_to_html(fig))

    guide = metrics["guide_perf"]
    if not guide.empty:
        fig = px.bar(
            guide,
            x="导购员",
            y="实收金额",
            color="连带",
            title="导购业绩对比",
            text_auto=".2s",
            hover_data=["票数", "单效", "会员销额"],
        )
        fig.update_layout(height=420, margin=dict(l=20, r=20, t=60, b=20))
        charts.append(fig_to_html(fig))

    return charts


def format_badge(value: str, level: str) -> str:
    return f"<span class='badge badge-{level}'>{value}</span>"


def decorate_table(df: pd.DataFrame) -> pd.DataFrame:
    decorated = df.copy()
    if "季节策略" in decorated.columns:
        decorated["季节策略"] = decorated["季节策略"].map(
            {
                "当季主推": format_badge("当季主推", "green"),
                "下一季试补": format_badge("下一季试补", "yellow"),
                "跨季去化": format_badge("跨季去化", "red"),
                "暂缓补货": format_badge("暂缓补货", "yellow"),
            }
        ).fillna(decorated["季节策略"])
    if "状态" in decorated.columns:
        decorated["状态"] = decorated["状态"].map(
            {
                "高压货": format_badge("高压货", "red"),
                "需关注": format_badge("需关注", "yellow"),
                "相对健康": format_badge("相对健康", "green"),
            }
        ).fillna(decorated["状态"])
    if "建议动作" in decorated.columns:
        decorated["建议动作"] = decorated["建议动作"].astype(str).map(
            {
                "立即补货": format_badge("立即补货", "red"),
                "优先补货": format_badge("优先补货", "yellow"),
                "先校库存再补货": format_badge("先校库存再补货", "red"),
                "小量试补": format_badge("小量试补", "yellow"),
                "先停补再去化": format_badge("先停补再去化", "red"),
                "观察并做组合去化": format_badge("观察并做组合去化", "yellow"),
                "优先去化": format_badge("优先去化", "red"),
                "跨季不补货": format_badge("跨季不补货", "red"),
                "暂缓补货": format_badge("暂缓补货", "yellow"),
            }
        ).fillna(decorated["建议动作"])
    return decorated


def build_dashboard_tips(cards: dict, actions: dict) -> list[dict[str, str]]:
    return [
        {
            "term": "经营销售额",
            "meaning": "只看正常商品销售，不包含道具，更接近门店真实营业额。",
            "watch": "先看这个数，再看客单价和订单数有没有一起增长。",
        },
        {
            "term": "客单价",
            "meaning": "平均每一单花了多少钱，公式是经营销售额 / 订单数。",
            "watch": "客单价低，优先查连带推荐和组合销售做得够不够。",
        },
        {
            "term": "库存覆盖天数",
            "meaning": "按最近销售速度估算，现有库存大约还能卖多少天。",
            "watch": "天数越高，压货越重；天数太低，容易断货。",
        },
        {
            "term": "负库存 SKU",
            "meaning": "系统里库存小于 0 的商品数量，说明账和货对不上。",
            "watch": "这个数不先处理，补货和去化判断都会失真。",
        },
        {
            "term": "建议补货 SKU",
            "meaning": "最近卖得不差、但库存偏低的商品数。",
            "watch": "先看销售金额高、库存接近 0、库存周数短的款。",
        },
        {
            "term": "建议去化 SKU",
            "meaning": "库存较高、近期卖得慢的商品数。",
            "watch": "先停补，再做搭配、组合或清货动作。",
        },
        {
            "term": "跨季处理 SKU",
            "meaning": "当前时间点不适合补货的商品数，包括跨季去化和暂缓补货。",
            "watch": "先看季节策略，冬款临近夏天不要直接补，优先去化或等待下季。",
        },
        {
            "term": "高压货品类",
            "meaning": "库存金额相对销售金额明显偏高的品类数量。",
            "watch": "高压货品类多，说明进货节奏和去化节奏都要收紧。",
        },
        {
            "term": "会员销售额占比",
            "meaning": "会员顾客贡献了多少经营销售额。",
            "watch": "占比越高，越值得做回访、复购提醒和老客经营。",
        },
        {
            "term": "道具参考",
            "meaning": "单独展示道具相关金额和库存，只作参考，不参与主经营判断。",
            "watch": "不要拿道具数值去判断真实商品卖得好不好。",
        },
    ]


def top_label_from_series(series: pd.Series, fallback: str) -> str:
    clean = series.dropna()
    if clean.empty:
        return fallback
    return str(clean.iloc[0])


def build_time_strategy(metrics: dict, now: datetime | None = None) -> dict:
    now = now or get_beijing_now()
    season, phase, next_season = infer_season(now)
    replenish = metrics["replenish"]
    clearance = metrics["clearance"]
    cards = metrics["summary_cards"]

    replenish_by_season = (
        replenish.groupby("季节")
        .agg(SKU=("款号", "count"), 销售额=("销售金额", "sum"), 建议补货量=("建议补货量", "sum"))
        .sort_values(["销售额", "SKU"], ascending=[False, False])
        if not replenish.empty
        else pd.DataFrame()
    )
    replenish_by_category = (
        replenish.groupby("中类")
        .agg(SKU=("款号", "count"), 销售额=("销售金额", "sum"))
        .sort_values(["销售额", "SKU"], ascending=[False, False])
        if not replenish.empty
        else pd.DataFrame()
    )
    clearance_by_category = (
        clearance.groupby("大类")
        .agg(SKU=("商品款号", "count"), 库存=("实际库存", "sum"))
        .sort_values(["库存", "SKU"], ascending=[False, False])
        if not clearance.empty
        else pd.DataFrame()
    )

    top_replenish_season = top_label_from_series(replenish_by_season.index.to_series(), "当前季节")
    top_replenish_category = top_label_from_series(replenish_by_category.index.to_series(), "基础品类")
    top_clearance_category = top_label_from_series(clearance_by_category.index.to_series(), "高库存品类")

    season_copy = {
        "春季": {
            "headline": "春夏换季，重心是薄款起量、冬款不深补。",
            "daily": [
                "今天先查负库存和断码，避免春夏补货判断失真。",
                f"今天补货优先看 {top_replenish_category}，但冬季类补货先人工复核，不做深补。",
                f"今天去化先盯 {top_clearance_category}，先停补再想组合去化。",
            ],
            "weekly": [
                f"本周把补货重心转到 {next_season}，尤其是 {top_replenish_category} 这类能直接起量的商品。",
                "本周减少厚款和冬款的新进货，旧货先靠搭配和小组合去化。",
                "本周检查门店陈列，让春款在前，夏款预热，厚款退到后区。",
            ],
            "monthly": [
                "本月经营目标不是压更多货，而是把春款卖动、为夏款腾货位。",
                "本月把高压货品类做成专项表，先控进货，再安排去化节奏。",
                "本月会员触达重点围绕换季、开学、出游、早晚温差场景去做。",
            ],
        },
        "夏季": {
            "headline": "夏季主销，重心是快补畅销、防止断码、控制秋装上量节奏。",
            "daily": [
                f"今天先看 {top_replenish_category} 的低库存款，优先保住畅销不断货。",
                "今天把夏季主销款摆到最前，非主销和慢销款压缩陈列面。",
                f"今天去化继续盯 {top_clearance_category}，防止旧压货挤占夏季主销空间。",
            ],
            "weekly": [
                "本周补货以快反为主，不做大批量压货。",
                f"本周把 {next_season} 预热款先小量试，不要一次性压太深。",
                "本周重点看会员复购和连带，放大客单价而不是只追客流。",
            ],
            "monthly": [
                "本月目标是把夏季主销卖透，同时为秋季试水留空间。",
                "本月每周复盘一次断码和补货速度，优先看卖得快的颜色尺码。",
                "本月对高库存慢销款做组合价或搭配推荐，别继续补。",
            ],
        },
        "秋季": {
            "headline": "秋冬换季，重心是基础打底起量、冬款试补、夏款快速收尾。",
            "daily": [
                f"今天先查 {top_clearance_category} 去化进度，夏季尾货别再压陈列面。",
                f"今天补货优先看 {top_replenish_category}，但冬款仍然先小量试补。",
                "今天把秋装主销、冬装预热的货架顺序重新排一遍。",
            ],
            "weekly": [
                "本周重点看秋款成交和冬款试销反馈，再决定是否加深补货。",
                "本周把夏季尾货做收尾，不要拖到冬季还占货位。",
                "本周会员话题围绕换季保暖、开学、居家场景来做。",
            ],
            "monthly": [
                "本月经营重点是秋款卖动、冬款试销、夏款清尾。",
                "本月高压货类目先停补，等秋冬主销稳定后再决定结构。",
                "本月把基础内裤、袜品、家居打底作为连带重点。",
            ],
        },
        "冬季": {
            "headline": "冬季主销，重心是保暖主力款不断货，同时为春季轻量预热。",
            "daily": [
                f"今天先保住 {top_replenish_category} 的畅销补货，不让主销款断货。",
                f"今天去化继续盯 {top_clearance_category}，慢销冬款不要继续深补。",
                "今天重点查高单价保暖款的库存准确性和尺码完整性。",
            ],
            "weekly": [
                "本周继续围绕保暖、居家、基础打底做成交和连带。",
                f"本周春季预热款只做小量试，不要提前压太深。",
                "本周对库存深的冬款做分层：还能卖的保留，慢销的提前准备去化。",
            ],
            "monthly": [
                "本月经营重点是抓住冬季主销窗口，同时给春季做轻量试水。",
                "本月保持主力保暖款不断货，但慢销冬款不再追加。",
                "本月会员经营围绕保暖场景、节日礼品、换新提醒来做。",
            ],
        },
    }

    selected = season_copy[season]

    return {
        "beijing_time": now.strftime("%Y-%m-%d %H:%M"),
        "season": season,
        "phase": phase,
        "next_season": next_season,
        "headline": selected["headline"],
        "top_replenish_season": top_replenish_season,
        "top_replenish_category": top_replenish_category,
        "top_clearance_category": top_clearance_category,
        "daily_actions": selected["daily"],
        "weekly_actions": selected["weekly"],
        "monthly_actions": selected["monthly"],
        "inventory_days": cards["estimated_inventory_days"],
    }


def build_operational_playbooks(metrics: dict) -> list[dict]:
    cards = metrics["summary_cards"]
    actions = metrics["action_summary"]
    time_strategy = build_time_strategy(metrics)
    category_risks = metrics["category_risks"]
    top_members = metrics["top_members"].head(3)
    seasonal_actions = metrics["seasonal_actions"].head(3)
    top_risk_category = top_label_from_series(category_risks["大类"], "高库存品类")
    top_member_names = "、".join(top_members["VIP姓名"].astype(str).tolist()) if not top_members.empty else "高价值会员"
    top_seasonal_sample = (
        "、".join(seasonal_actions["款号"].astype(str).tolist()) if not seasonal_actions.empty else "跨季款"
    )

    playbooks: list[dict] = []

    if cards["estimated_inventory_days"] >= 120:
        playbooks.append(
            {
                "level": "red",
                "title": "库存周期过长，先做促销去化",
                "trigger": f"当前经营库存覆盖天数 {format_num(cards['estimated_inventory_days'], 1)} 天，已经明显偏长。",
                "goal": "先把高库存慢销货动起来，给当季主销和补货腾出空间。",
                "schemes": [
                    {
                        "name": f"{top_risk_category} 组合促销",
                        "detail": f"围绕 {top_risk_category} 做 2 件 / 3 件组合价，优先配基础内裤、袜品、家居这类低决策商品，门店主推“顺手带走”的组合。",
                    },
                    {
                        "name": "会员定向去化促销",
                        "detail": f"优先触达 {top_member_names} 这一类老客，发换季组合包或加价购，主推“到店试一套 / 顺手补一轮”。",
                    },
                    {
                        "name": "周末限时清货台",
                        "detail": f"把 {top_risk_category} 和当前去化重点放到门口清货位，做 3 天限时陈列，配合第二件折扣或满额换购，但不全场乱打折。",
                    },
                ],
            }
        )

    if actions["replenish_count"] >= 120:
        playbooks.append(
            {
                "level": "red",
                "title": "畅销款缺货风险高，补货要分级",
                "trigger": f"当前建议补货 SKU {format_num(actions['replenish_count'])} 个，补货压力较高。",
                "goal": "先保住最能带营业额的款，不让补货动作失控。",
                "schemes": [
                    {
                        "name": "A类马上补",
                        "detail": f"今天先补 {time_strategy['top_replenish_category']}，优先销售金额高、库存 0-1、库存周数小于 1 的款。",
                    },
                    {
                        "name": "B类本周补",
                        "detail": "本周内处理销售稳定但库存还有 1-2 周的款，避免一下子把补货预算打满。",
                    },
                    {
                        "name": "C类先观察",
                        "detail": f"{time_strategy['season']} 和下季交界的款先小量试补，避免把非主销季的货压深。",
                    },
                ],
            }
        )

    if cards["negative_sku_count"] >= 30:
        playbooks.append(
            {
                "level": "red",
                "title": "负库存先纠偏，再谈补货",
                "trigger": f"当前负库存 SKU {format_num(cards['negative_sku_count'])} 个，库存口径已经影响经营判断。",
                "goal": "先把库存账实校准，不然补货和去化都会跑偏。",
                "schemes": [
                    {
                        "name": "先查高频负库存",
                        "detail": "先从销售高、库存低、还在建议补货清单里的负库存款开始校正，优先处理最影响营业额的货。",
                    },
                    {
                        "name": "按来源分三类排查",
                        "detail": "把负库存拆成盘点错误、调拨未入、销售未回写 3 类，店员照类别处理，不要混着查。",
                    },
                    {
                        "name": "未校正前先冻结深补",
                        "detail": "对负库存涉及的款先不要深补，只允许人工确认后补货，避免一边错一边继续压货。",
                    },
                ],
            }
        )

    if actions["seasonal_hold_count"] >= 1:
        playbooks.append(
            {
                "level": "yellow",
                "title": "跨季款先别补，先按季节处理",
                "trigger": f"当前有 {format_num(actions['seasonal_hold_count'])} 个 SKU 被识别为跨季去化或暂缓补货，例如 {top_seasonal_sample}。",
                "goal": "避免把非主销季的货继续补深，把钱和货位留给当前季节。",
                "schemes": [
                    {
                        "name": "有库存先去化",
                        "detail": "如果跨季款手里还有库存，优先转到去化清单，用组合价、加价购、门口清货位来动销。",
                    },
                    {
                        "name": "没库存不再追补",
                        "detail": "如果像冬季羽绒这样当前库存已经为 0，现阶段不要因为历史卖过就立即补，先等回到主销季再评估。",
                    },
                    {
                        "name": "跨季款单独看板",
                        "detail": "把跨季款放到单独的“跨季处理建议清单”，由老板每周决定去化、暂缓还是等待下季，不跟当季补货混在一起。",
                    },
                ],
            }
        )

    if cards["member_sales_ratio"] >= 0.6:
        playbooks.append(
            {
                "level": "green",
                "title": "会员占比高，适合做定向复购",
                "trigger": f"会员销售额占比 {format_num(cards['member_sales_ratio'] * 100, 1)}%，会员已经是门店核心来源。",
                "goal": "把已有会员复购做深，而不是只靠新客自然进店。",
                "schemes": [
                    {
                        "name": "换季提醒",
                        "detail": f"围绕 {time_strategy['season']} 到 {time_strategy['next_season']} 的换季场景，给老客发“尺码 / 厚薄 / 到店试一轮”的提醒。",
                    },
                    {
                        "name": "高客单老客回访",
                        "detail": f"优先回访 {top_member_names} 这类高价值会员，话术聚焦“新到一批适合你家孩子的基础款”。",
                    },
                    {
                        "name": "复购带连带",
                        "detail": "会员到店不要只补单品，主推基础打底 + 袜品 + 家居这种顺手连带组合，放大客单价。",
                    },
                ],
            }
        )

    return playbooks


def table_html(df: pd.DataFrame, title: str, rows: int = 10, tip: str | None = None) -> str:
    preview = df.head(rows).copy()
    preview = decorate_table(preview)
    tip_html = f"<p class='table-tip'>{tip}</p>" if tip else ""
    return f"""
    <section class="table-card">
      <h3>{title}</h3>
      {tip_html}
      {preview.to_html(index=False, classes='data-table', border=0, escape=False)}
    </section>
    """


def build_html(metrics: dict) -> str:
    cards = metrics["summary_cards"]
    charts = build_charts(metrics)
    actions = metrics["action_summary"]
    health_lights = build_health_lights(cards, actions)
    dashboard_tips = build_dashboard_tips(cards, actions)
    time_strategy = build_time_strategy(metrics)
    playbooks = build_operational_playbooks(metrics)
    primary_reference = metrics["primary_reference"]
    other_references = metrics["other_references"]

    card_items = [
        ("经营销售额", f"{format_num(cards['sales_amount'], 2)} 元", "默认已排除道具"),
        ("订单数", format_num(cards["sales_orders"]), f"{cards['sales_days']} 天经营明细"),
        ("客单价", f"{format_num(cards['avg_order_value'], 2)} 元", "经营销售额 / 订单数"),
        ("历史累计销售额", f"{format_num(cards['cumulative_sales_amount'], 2)} 元", "历史累计，默认已排除道具"),
        ("历史累计销量", format_num(cards["cumulative_sales_qty"]), "自首次销售起累计"),
        ("经营库存额", f"{format_num(cards['inventory_amount'], 2)} 元", "默认已排除道具"),
        ("负库存 SKU", format_num(cards["negative_sku_count"]), "需要优先纠偏"),
        ("会员销售额占比", f"{format_num(cards['member_sales_ratio'] * 100, 1)}%", "会员是核心来源"),
        ("预计库存覆盖天数", f"{format_num(cards['estimated_inventory_days'], 1)} 天", "经营商品口径"),
        ("建议补货 SKU", format_num(actions["replenish_count"]), "优先看畅销低库存"),
        ("跨季处理 SKU", format_num(actions["seasonal_hold_count"]), "不建议按原逻辑继续补货"),
        ("建议去化 SKU", format_num(actions["clearance_count"]), "优先看高库存低动销"),
        ("高压货品类", format_num(actions["high_risk_category_count"]), "按库存金额/销售金额判断"),
    ]
    reference_items = [
        ("道具销售额", f"{format_num(cards['props_sales_amount'], 2)} 元", "单独参考，不计入经营销售额"),
        ("道具库存额", f"{format_num(cards['props_inventory_amount'], 2)} 元", "单独参考，不计入经营库存额"),
        ("道具销量", format_num(cards["props_sales_qty"]), "单独参考"),
        ("道具库存件数", format_num(cards["props_inventory_qty"]), "单独参考"),
    ]

    insights_html = "".join(f"<li>{item}</li>" for item in metrics["insights"])
    chart_html = "".join(f"<section class='chart-card'>{chart}</section>" for chart in charts)
    tips_html = "".join(
        f"""
        <div class="tip-card">
          <div class="tip-term">{item['term']}</div>
          <div class="tip-meaning">{item['meaning']}</div>
          <div class="tip-watch">看法：{item['watch']}</div>
        </div>
        """
        for item in dashboard_tips
    )
    time_html = "".join(
        [
            f"""
            <div class="time-card">
              <div class="time-title">北京时间</div>
              <div class="time-value">{time_strategy['beijing_time']}</div>
              <div class="time-note">{time_strategy['season']} / {time_strategy['phase']}</div>
            </div>
            """,
            f"""
            <div class="time-card">
              <div class="time-title">当前季节判断</div>
              <div class="time-value">{time_strategy['season']}</div>
              <div class="time-note">{time_strategy['headline']}</div>
            </div>
            """,
            f"""
            <div class="time-card">
              <div class="time-title">补货关注</div>
              <div class="time-value">{time_strategy['top_replenish_category']}</div>
              <div class="time-note">当前建议补货最多的季节：{time_strategy['top_replenish_season']}</div>
            </div>
            """,
            f"""
            <div class="time-card">
              <div class="time-title">去化关注</div>
              <div class="time-value">{time_strategy['top_clearance_category']}</div>
              <div class="time-note">当前库存覆盖约 {format_num(time_strategy['inventory_days'], 1)} 天</div>
            </div>
            """,
        ]
    )
    daily_actions_html = "".join(f"<li>{item}</li>" for item in time_strategy["daily_actions"])
    weekly_actions_html = "".join(f"<li>{item}</li>" for item in time_strategy["weekly_actions"])
    monthly_actions_html = "".join(f"<li>{item}</li>" for item in time_strategy["monthly_actions"])
    playbooks_html = "".join(
        f"""
        <div class="playbook-card playbook-{item['level']}">
          <div class="playbook-title">{item['title']}</div>
          <div class="playbook-trigger">触发原因：{item['trigger']}</div>
          <div class="playbook-goal">目标：{item['goal']}</div>
          <div class="playbook-subtitle">可直接执行的 3 套方案</div>
          <ul>
            {"".join(f"<li><strong>{scheme['name']}</strong>：{scheme['detail']}</li>" for scheme in item['schemes'])}
          </ul>
        </div>
        """
        for item in playbooks
    )
    if not primary_reference.empty:
        primary = primary_reference.iloc[0]
        reference_intro = (
            f"主逻辑固定关注 {metrics['primary_input']} / {primary['店铺名称']}。"
            "下面其他输入人代表其他店铺，只做参考对比，不参与主经营结论。"
        )
    else:
        reference_intro = "未读取到可用的输入人参考表。"

    tables = "".join(
        [
            table_html(metrics["replenish"], "补货建议清单", 12, "先看销售金额高、库存低、库存周数短的款，优先补畅销款。"),
            table_html(metrics["seasonal_actions"], "跨季处理建议清单", 12, "先看季节策略。跨季去化的款不要继续补，有库存先清；没库存就等下季。"),
            table_html(metrics["clearance"], "去化建议清单", 12, "先看实际库存高、近期零售低、动销率低的款，先停补再想去化。"),
            table_html(metrics["low_stock_bestsellers"], "畅销但低库存的商品", 12, "这些款卖得不差，但库存已经很低，容易影响营业额。"),
            table_html(metrics["slow_moving"], "高库存但低动销的商品", 12, "这些款库存不少，但近期基本没卖动，适合优先排查。"),
            table_html(metrics["negative_inventory"], "负库存异常清单", 12, "先查账、查盘点、查调拨，别直接按这张表补货。"),
            table_html(metrics["top_members"], "高价值会员", 12, "优先回访高消费或高频顾客，做复购和转介绍。"),
            table_html(other_references, "其他店铺参考", 8, reference_intro),
        ]
    )

    card_html = "".join(
        f"""
        <div class="metric-card">
          <div class="metric-title">{title}</div>
          <div class="metric-value">{value}</div>
          <div class="metric-note">{note}</div>
        </div>
        """
        for title, value, note in card_items
    )
    reference_html = "".join(
        f"""
        <div class="metric-card">
          <div class="metric-title">{title}</div>
          <div class="metric-value">{value}</div>
          <div class="metric-note">{note}</div>
        </div>
        """
        for title, value, note in reference_items
    )
    health_html = "".join(
        f"""
        <div class="health-card health-{item['level']}">
          <div class="health-top">
            <span class="health-dot"></span>
            <span class="health-title">{item['title']}</span>
          </div>
          <div class="health-value">{item['value']}</div>
          <div class="health-note">{item['note']}</div>
        </div>
        """
        for item in health_lights
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{cards['store_name']} 库存销售看板</title>
  <style>
    body {{
      margin: 0;
      padding: 0;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: #f6f7fb;
      color: #1f2937;
    }}
    .page {{
      max-width: 1440px;
      margin: 0 auto;
      padding: 28px;
    }}
    .hero {{
      background: linear-gradient(135deg, #0f172a 0%, #1d4ed8 100%);
      color: white;
      padding: 28px;
      border-radius: 20px;
      margin-bottom: 24px;
      box-shadow: 0 18px 48px rgba(15, 23, 42, 0.18);
    }}
    .hero h1 {{
      margin: 0 0 8px;
      font-size: 30px;
    }}
    .hero p {{
      margin: 0;
      opacity: 0.9;
      line-height: 1.6;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin: 24px 0;
    }}
    .metric-card, .chart-card, .table-card, .insight-card {{
      background: white;
      border-radius: 18px;
      box-shadow: 0 10px 30px rgba(15, 23, 42, 0.08);
      padding: 18px;
    }}
    .metric-title {{
      font-size: 14px;
      color: #64748b;
      margin-bottom: 8px;
    }}
    .metric-value {{
      font-size: 28px;
      font-weight: 700;
      margin-bottom: 6px;
    }}
    .metric-note {{
      font-size: 13px;
      color: #94a3b8;
    }}
    .tip-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 16px;
      margin-top: 16px;
    }}
    .tip-card {{
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 16px;
      padding: 16px;
    }}
    .tip-term {{
      font-size: 15px;
      font-weight: 700;
      margin-bottom: 8px;
      color: #0f172a;
    }}
    .tip-meaning {{
      font-size: 13px;
      line-height: 1.7;
      color: #334155;
      margin-bottom: 8px;
    }}
    .tip-watch {{
      font-size: 12px;
      line-height: 1.7;
      color: #475569;
    }}
    .time-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin-top: 16px;
    }}
    .time-card {{
      background: #f8fafc;
      border: 1px solid #dbeafe;
      border-radius: 16px;
      padding: 16px;
    }}
    .time-title {{
      font-size: 13px;
      color: #64748b;
      margin-bottom: 8px;
    }}
    .time-value {{
      font-size: 24px;
      font-weight: 700;
      color: #0f172a;
      margin-bottom: 8px;
    }}
    .time-note {{
      font-size: 13px;
      line-height: 1.7;
      color: #334155;
    }}
    .decision-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 16px;
      margin-top: 16px;
    }}
    .decision-card {{
      background: #ffffff;
      border: 1px solid #e2e8f0;
      border-radius: 16px;
      padding: 16px;
    }}
    .decision-title {{
      font-size: 15px;
      font-weight: 700;
      margin-bottom: 8px;
      color: #0f172a;
    }}
    .decision-card ul {{
      margin: 0 0 0 18px;
      padding: 0;
      line-height: 1.8;
      color: #334155;
      font-size: 13px;
    }}
    .playbook-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 16px;
      margin-top: 16px;
    }}
    .playbook-card {{
      border-radius: 18px;
      padding: 18px;
      border: 1px solid #e5e7eb;
      background: #ffffff;
    }}
    .playbook-title {{
      font-size: 16px;
      font-weight: 700;
      margin-bottom: 10px;
      color: #0f172a;
    }}
    .playbook-trigger,
    .playbook-goal {{
      font-size: 13px;
      line-height: 1.7;
      color: #334155;
      margin-bottom: 8px;
    }}
    .playbook-subtitle {{
      font-size: 13px;
      font-weight: 700;
      color: #0f172a;
      margin: 12px 0 6px;
    }}
    .playbook-card ul {{
      margin: 0 0 0 18px;
      padding: 0;
      line-height: 1.8;
      color: #334155;
      font-size: 13px;
    }}
    .playbook-red {{
      background: #fff7f7;
      border-color: #fecaca;
    }}
    .playbook-yellow {{
      background: #fffbeb;
      border-color: #fde68a;
    }}
    .playbook-green {{
      background: #f0fdf4;
      border-color: #bbf7d0;
    }}
    .health-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin-top: 16px;
    }}
    .health-card {{
      border-radius: 18px;
      padding: 18px;
      border: 1px solid #e5e7eb;
    }}
    .health-top {{
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 10px;
    }}
    .health-dot {{
      width: 12px;
      height: 12px;
      border-radius: 999px;
      display: inline-block;
    }}
    .health-title {{
      font-size: 14px;
      font-weight: 600;
    }}
    .health-value {{
      font-size: 28px;
      font-weight: 700;
      margin-bottom: 6px;
    }}
    .health-note {{
      font-size: 13px;
      line-height: 1.6;
    }}
    .health-red {{
      background: #fff1f2;
      border-color: #fecdd3;
    }}
    .health-red .health-dot {{
      background: #dc2626;
    }}
    .health-red .health-title,
    .health-red .health-value {{
      color: #991b1b;
    }}
    .health-yellow {{
      background: #fffbeb;
      border-color: #fde68a;
    }}
    .health-yellow .health-dot {{
      background: #d97706;
    }}
    .health-yellow .health-title,
    .health-yellow .health-value {{
      color: #92400e;
    }}
    .health-green {{
      background: #ecfdf5;
      border-color: #a7f3d0;
    }}
    .health-green .health-dot {{
      background: #059669;
    }}
    .health-green .health-title,
    .health-green .health-value {{
      color: #065f46;
    }}
    .insight-card ul {{
      margin: 8px 0 0 18px;
      padding: 0;
      line-height: 1.7;
    }}
    .charts {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 18px;
      margin: 24px 0;
    }}
    .tables {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 18px;
      margin: 24px 0;
    }}
    .data-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      overflow: hidden;
    }}
    .data-table th, .data-table td {{
      padding: 8px 10px;
      border-bottom: 1px solid #e5e7eb;
      text-align: left;
    }}
    .data-table th {{
      background: #f8fafc;
      position: sticky;
      top: 0;
    }}
    .table-tip {{
      font-size: 13px;
      color: #475569;
      line-height: 1.7;
      margin: 6px 0 12px;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 3px 10px;
      font-size: 12px;
      font-weight: 600;
      white-space: nowrap;
    }}
    .badge-red {{
      background: #fee2e2;
      color: #991b1b;
    }}
    .badge-yellow {{
      background: #fef3c7;
      color: #92400e;
    }}
    .badge-green {{
      background: #dcfce7;
      color: #166534;
    }}
    .table-card {{
      overflow-x: auto;
    }}
    @media (max-width: 960px) {{
      .charts {{
        grid-template-columns: 1fr;
      }}
      .page {{
        padding: 16px;
      }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <h1>{cards['store_name']} 库存销售看板</h1>
      <p>这份看板把库存、销售、会员、导购和补货风险放在一页里，适合老板和店员直接看重点，不需要先看原始 Excel。</p>
    </section>

    <section class="grid">{card_html}</section>

    <section class="insight-card">
      <h2>北京时间与季节决策</h2>
      <p>这部分按北京时间和当前季节自动生成，直接告诉门店今天、本周、本月更应该抓什么。</p>
      <section class="time-grid">{time_html}</section>
      <section class="decision-grid">
        <div class="decision-card">
          <div class="decision-title">今天先做</div>
          <ul>{daily_actions_html}</ul>
        </div>
        <div class="decision-card">
          <div class="decision-title">本周重点</div>
          <ul>{weekly_actions_html}</ul>
        </div>
        <div class="decision-card">
          <div class="decision-title">本月方向</div>
          <ul>{monthly_actions_html}</ul>
        </div>
      </section>
    </section>

    <section class="insight-card">
      <h2>具体操作方案</h2>
      <p>这部分不是提醒，而是根据当前数据自动生成的处理方案。先处理红色方案，再看绿色增量方案。</p>
      <section class="playbook-grid">{playbooks_html}</section>
    </section>

    <section class="insight-card">
      <h2>经营健康灯</h2>
      <p>先看颜色，再看数字。红色优先处理，黄色持续盯住，绿色维持节奏。</p>
      <section class="health-grid">{health_html}</section>
    </section>

    <section class="insight-card">
      <h2>术语 Tips</h2>
      <p>如果你对这些数字不熟，先看这里。每个术语都告诉你“这是什么”和“你该怎么看”。</p>
      <section class="tip-grid">{tips_html}</section>
    </section>

    <section class="insight-card">
      <h2>道具参考口径</h2>
      <p>道具已从主经营指标里剥离。下面这组数值只做参考，不参与经营销售、库存覆盖、补货和去化判断。</p>
      <section class="grid">{reference_html}</section>
    </section>

    <section class="insight-card">
      <h2>自动提炼的重点提醒</h2>
      <ul>{insights_html}</ul>
    </section>

    <section class="charts">{chart_html}</section>

    <section class="tables">{tables}</section>
  </div>
</body>
</html>
"""


def build_markdown_summary(metrics: dict) -> str:
    cards = metrics["summary_cards"]
    actions = metrics["action_summary"]
    health_lights = build_health_lights(cards, actions)
    dashboard_tips = build_dashboard_tips(cards, actions)[:7]
    time_strategy = build_time_strategy(metrics)
    playbooks = build_operational_playbooks(metrics)
    replenish = metrics["replenish"].head(5)
    seasonal_actions = metrics["seasonal_actions"].head(5)
    clearance = metrics["clearance"].head(5)
    primary_reference = metrics["primary_reference"]
    level_map = {"red": "红灯", "yellow": "黄灯", "green": "绿灯"}
    lines = [
        f"# {cards['store_name']} 库存销售摘要",
        "",
        "## 核心指标",
        f"- 经营销售额：{format_num(cards['sales_amount'], 2)} 元",
        f"- 销售明细时间范围：{cards['sales_detail_start'].strftime('%Y-%m-%d')} 到 {cards['sales_detail_end'].strftime('%Y-%m-%d')}",
        f"- 订单数：{format_num(cards['sales_orders'])}",
        f"- 客单价：{format_num(cards['avg_order_value'], 2)} 元",
        f"- 历史累计销售额：{format_num(cards['cumulative_sales_amount'], 2)} 元",
        f"- 历史累计销量：{format_num(cards['cumulative_sales_qty'])}",
        f"- 历史首次销售日期：{cards['history_first_sale'].strftime('%Y-%m-%d')}",
        f"- 经营库存额：{format_num(cards['inventory_amount'], 2)} 元",
        f"- 经营库存件数：{format_num(cards['inventory_qty'])}",
        f"- 负库存 SKU：{format_num(cards['negative_sku_count'])}",
        f"- 会员销售额占比：{format_num(cards['member_sales_ratio'] * 100, 1)}%",
        f"- 建议补货 SKU：{format_num(actions['replenish_count'])}",
        f"- 跨季处理 SKU：{format_num(actions['seasonal_hold_count'])}",
        f"- 建议去化 SKU：{format_num(actions['clearance_count'])}",
        "",
        "## 输入人 / 店铺逻辑",
    ]
    if not primary_reference.empty:
        row = primary_reference.iloc[0]
        lines.extend([
            f"- 主逻辑固定关注：{metrics['primary_input']} / {row['店铺名称']}",
            "- 其他输入人代表其他店铺，只做参考，不参与主经营口径。",
            "",
        ])
    else:
        lines.extend([
            "- 当前没有读取到可用的输入人参考表。",
            "",
        ])
    lines.extend([
        "## 北京时间与季节决策",
        f"- 北京时间：{time_strategy['beijing_time']}",
        f"- 当前季节：{time_strategy['season']} / {time_strategy['phase']}",
        f"- 当前判断：{time_strategy['headline']}",
        f"- 补货重点：{time_strategy['top_replenish_category']}",
        f"- 去化重点：{time_strategy['top_clearance_category']}",
        "",
        "### 今天先做",
    ]
    lines.extend(f"- {item}" for item in time_strategy["daily_actions"])
    lines.extend([
        "",
        "### 本周重点",
    ])
    lines.extend(f"- {item}" for item in time_strategy["weekly_actions"])
    lines.extend([
        "",
        "### 本月方向",
    ])
    lines.extend(f"- {item}" for item in time_strategy["monthly_actions"])
    lines.extend([
        "",
        "## 具体操作方案",
    ])
    for item in playbooks:
        lines.append(f"- {item['title']}：{item['trigger']}")
        lines.append(f"  目标：{item['goal']}")
        for idx, scheme in enumerate(item["schemes"], 1):
            lines.append(f"  方案{idx}：{scheme['name']}，{scheme['detail']}")
    lines.extend([
        "",
        "## 道具参考",
        f"- 道具销售额：{format_num(cards['props_sales_amount'], 2)} 元",
        f"- 道具销量：{format_num(cards['props_sales_qty'])}",
        f"- 道具库存额：{format_num(cards['props_inventory_amount'], 2)} 元",
        f"- 道具库存件数：{format_num(cards['props_inventory_qty'])}",
        "",
        "## 经营健康灯",
    ])
    lines.extend(
        f"- {level_map[item['level']]} | {item['title']}：{item['value']}，{item['note']}"
        for item in health_lights
    )
    lines.extend([
        "",
        "## 术语 Tips",
    ])
    lines.extend(
        f"- {item['term']}：{item['meaning']} 看法：{item['watch']}"
        for item in dashboard_tips
    )
    lines.extend([
        "",
        "## 自动提醒",
    ])
    lines.extend(f"- {item}" for item in metrics["insights"])
    lines.append("")
    lines.append("## 最值得先处理的表")
    lines.append("- 畅销但低库存的商品：优先补货")
    lines.append("- 跨季处理建议清单：当前不该补的款先拎出来")
    lines.append("- 高库存但低动销的商品：优先去化或停补")
    lines.append("- 负库存异常清单：优先纠偏")
    if not replenish.empty:
        lines.append("")
        lines.append("## 优先补货 Top 5")
        for _, row in replenish.iterrows():
            lines.append(
                f"- {row['款号']} / {row['颜色']}：库存 {format_num(row['库存'])}，周均销量 {format_num(row['周均销量'], 1)}，建议补货 {format_num(row['建议补货量'])}"
            )
    if not seasonal_actions.empty:
        lines.append("")
        lines.append("## 跨季处理 Top 5")
        for _, row in seasonal_actions.iterrows():
            lines.append(
                f"- {row['款号']} / {row['颜色']} / {row['季节']}：季节策略 {row['季节策略']}，库存 {format_num(row['库存'])}，建议 {row['建议动作']}"
            )
    if not clearance.empty:
        lines.append("")
        lines.append("## 优先去化 Top 5")
        for _, row in clearance.iterrows():
            lines.append(
                f"- {row['商品款号']} / {row['商品名称']}：实际库存 {format_num(row['实际库存'])}，近期零售 {format_num(row['近期零售'])}，建议 {row['建议动作']}"
            )
    return "\n".join(lines)


def build_business_report(metrics: dict) -> str:
    cards = metrics["summary_cards"]
    sales_top = metrics["sales_by_category_ex_props"].head(4)
    category_risks = metrics["category_risks"].head(4)
    guides = metrics["guide_perf"].head(3)
    seasonal_actions = metrics["seasonal_actions"].head(5)
    health_lights = build_health_lights(cards, metrics["action_summary"])
    time_strategy = build_time_strategy(metrics)
    playbooks = build_operational_playbooks(metrics)
    primary_reference = metrics["primary_reference"]
    level_map = {"red": "红灯", "yellow": "黄灯", "green": "绿灯"}

    lines = [
        f"# {cards['store_name']} 库存销售分析报告",
        "",
        f"日期：{pd.Timestamp.today().strftime('%Y-%m-%d')}",
        "",
        "## 一句话结论",
        "",
        "这份数据已经足够支持一个给老板和店员直接用的图形化工具。",
        "当前最需要优先管理的不是“再多看几张表”，而是先把库存压力、负库存异常、会员经营和高压货品类管起来。",
        "",
        "## 核心经营判断",
        "",
        f"- 近 {cards['sales_days']} 天经营销售额：{format_num(cards['sales_amount'], 2)} 元",
        f"- 销售明细时间范围：{cards['sales_detail_start'].strftime('%Y-%m-%d')} 到 {cards['sales_detail_end'].strftime('%Y-%m-%d')}",
        f"- 历史累计销售额：{format_num(cards['cumulative_sales_amount'], 2)} 元",
        f"- 历史累计销量：{format_num(cards['cumulative_sales_qty'])}",
        f"- 历史首次到货日期：{cards['history_first_arrival'].strftime('%Y-%m-%d')}",
        f"- 历史首次销售日期：{cards['history_first_sale'].strftime('%Y-%m-%d')}",
        f"- 订单数：{format_num(cards['sales_orders'])}",
        f"- 客单价：{format_num(cards['avg_order_value'], 2)} 元",
        f"- 经营库存件数：{format_num(cards['inventory_qty'])}",
        f"- 经营库存额：{format_num(cards['inventory_amount'], 2)} 元",
        f"- 经营库存覆盖天数：{format_num(cards['estimated_inventory_days'], 1)} 天",
        f"- 道具销售额参考：{format_num(cards['props_sales_amount'], 2)} 元",
        f"- 道具库存额参考：{format_num(cards['props_inventory_amount'], 2)} 元",
        f"- 负库存 SKU：{format_num(cards['negative_sku_count'])}",
        f"- 会员销售额占比：{format_num(cards['member_sales_ratio'] * 100, 1)}%",
        f"- 跨季处理 SKU：{format_num(metrics['action_summary']['seasonal_hold_count'])}",
        "",
        "## 输入人 / 店铺逻辑",
        "",
    ]
    if not primary_reference.empty:
        row = primary_reference.iloc[0]
        lines.extend([
            f"- 主逻辑固定关注：{metrics['primary_input']} / {row['店铺名称']}",
            "- 其他输入人代表其他店铺，只做参考，不参与主经营口径。",
            "",
        ])
    else:
        lines.extend([
            "- 当前没有读取到可用的输入人参考表。",
            "",
        ])
    lines.extend([
        "## 北京时间与季节决策",
        "",
        f"- 北京时间：{time_strategy['beijing_time']}",
        f"- 当前季节：{time_strategy['season']} / {time_strategy['phase']}",
        f"- 当前判断：{time_strategy['headline']}",
        f"- 当前补货重点：{time_strategy['top_replenish_category']}",
        f"- 当前去化重点：{time_strategy['top_clearance_category']}",
        "",
        "### 今天先做",
    ]

    for item in time_strategy["daily_actions"]:
        lines.append(f"- {item}")

    lines.extend([
        "",
        "### 本周重点",
    ])

    for item in time_strategy["weekly_actions"]:
        lines.append(f"- {item}")

    lines.extend([
        "",
        "### 本月方向",
    ])

    for item in time_strategy["monthly_actions"]:
        lines.append(f"- {item}")

    lines.extend([
        "",
        "## 具体操作方案",
        "",
    ])

    for item in playbooks:
        lines.append(f"### {item['title']}")
        lines.append(f"- 触发原因：{item['trigger']}")
        lines.append(f"- 目标：{item['goal']}")
        for idx, scheme in enumerate(item["schemes"], 1):
            lines.append(f"- 方案{idx}：{scheme['name']}，{scheme['detail']}")
        lines.append("")

    if not seasonal_actions.empty:
        lines.append("## 跨季处理 Top 5")
        lines.append("")
        for _, row in seasonal_actions.iterrows():
            lines.append(
                f"- {row['款号']} / {row['颜色']} / {row['季节']}：季节策略 {row['季节策略']}，库存 {format_num(row['库存'])}，建议 {row['建议动作']}"
            )
        lines.append("")

    lines.extend([
        "## 当前最重要的发现",
        "",
        "1. 主经营口径已经剔除道具后，库存覆盖天数仍然偏高，说明库存压力是真实存在的。",
        "2. 负库存异常较多，说明库存口径还需要先校准。",
        "3. 会员已经是核心收入来源，后续值得单独做会员复购提醒。",
        "4. 袜品等品类的压货风险比较明显，适合先停补再做去化。",
        "5. 道具现在只保留为参考值，不再影响销售、库存和补货判断。",
        "",
        "## 经营健康灯",
        "",
    ])

    for item in health_lights:
        lines.append(f"- {level_map[item['level']]} | {item['title']}：{item['value']}，{item['note']}")

    lines.extend([
        "",
        "## 销售贡献靠前的品类",
        "",
    ])

    for _, row in sales_top.iterrows():
        lines.append(
            f"- {row['商品大类']}：销售额 {format_num(row['销售额'], 2)} 元，销量 {format_num(row['销量'])}，订单数 {format_num(row['订单数'])}"
        )

    lines.extend(["", "## 高压货风险品类", ""])
    for _, row in category_risks.iterrows():
        lines.append(
            f"- {row['大类']}：库存金额/销售金额 {format_num(row['库存金额/销售金额'], 2)}，库存量/销售量 {format_num(row['库存量/销售量'], 2)}，状态 {row['状态']}"
        )

    lines.extend(["", "## 导购表现靠前人员", ""])
    for _, row in guides.iterrows():
        lines.append(
            f"- {row['导购员']}：实收金额 {format_num(row['实收金额'], 2)} 元，票数 {format_num(row['票数'])}，连带 {format_num(row['连带'], 2)}，会员销额 {format_num(row['会员销额'], 2)} 元"
        )

    lines.extend(
        [
            "",
            "## 这套数据适不适合做成 Python 工具",
            "",
            "结论：适合，而且已经进入可以落地的阶段。",
            "现在这套包里，短期趋势来自销售明细，长期累计来自商品销售情况，两种口径可以并行展示。",
            "",
            "原因：",
            "",
            "1. 原始 Excel 数量多，老板和店员直接看不方便。",
            "2. 核心动作已经能自动判断：补货、去化、品类风险、会员重点。",
            "3. 当前脚本已经能稳定产出图形化看板、摘要和动作清单。",
            "",
            "## 最推荐的下一步",
            "",
            "1. 继续保留当前脚本和 HTML 看板，先让门店跑起来。",
            "2. 下一版做成本地上传 zip 的简易网页工具，给非技术人员直接用。",
            "3. 后续再加红黄绿预警、断码提醒、会员复购提醒和导购经营看板。",
        ]
    )

    return "\n".join(lines)


def write_outputs(metrics: dict, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    date_tag = pd.Timestamp.today().strftime("%Y-%m-%d")
    html_path = output_dir / f"库存销售看板_{date_tag}.html"
    md_path = output_dir / f"库存销售摘要_{date_tag}.md"
    report_path = output_dir / f"库存销售分析报告_{date_tag}.md"
    replenish_csv = output_dir / f"补货建议清单_{date_tag}.csv"
    clearance_csv = output_dir / f"去化建议清单_{date_tag}.csv"
    category_csv = output_dir / f"品类风险概览_{date_tag}.csv"
    html_path.write_text(build_html(metrics), encoding="utf-8")
    md_path.write_text(build_markdown_summary(metrics), encoding="utf-8")
    report_path.write_text(build_business_report(metrics), encoding="utf-8")
    metrics["replenish"].to_csv(replenish_csv, index=False, encoding="utf-8-sig")
    metrics["clearance"].to_csv(clearance_csv, index=False, encoding="utf-8-sig")
    metrics["category_risks"].to_csv(category_csv, index=False, encoding="utf-8-sig")
    return {
        "html": html_path,
        "markdown": md_path,
        "report": report_path,
        "replenish_csv": replenish_csv,
        "clearance_csv": clearance_csv,
        "category_csv": category_csv,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--store", default=None, help="Optional store name override")
    parser.add_argument("--zip-file", type=Path, default=None, help="Optional zip export to extract and analyze")
    args = parser.parse_args()

    if args.zip_file:
        with tempfile.TemporaryDirectory(prefix="inventory_zip_") as temp_dir:
            extract_dir = Path(temp_dir)
            with zipfile.ZipFile(args.zip_file) as zf:
                zf.extractall(extract_dir)

            reports = resolve_reports(extract_dir)
            raw = load_data(reports)
            store_name = infer_store_name(raw, args.store)
            cleaned = clean_data(raw, store_name)
            metrics = build_metrics(cleaned, store_name)
            outputs = write_outputs(metrics, args.output_dir)
    else:
        reports = resolve_reports(args.input_dir)
        raw = load_data(reports)
        store_name = infer_store_name(raw, args.store)
        cleaned = clean_data(raw, store_name)
        metrics = build_metrics(cleaned, store_name)
        outputs = write_outputs(metrics, args.output_dir)

    print(f"Store: {store_name}")
    print(f"HTML dashboard: {outputs['html']}")
    print(f"Markdown summary: {outputs['markdown']}")
    print(f"Business report: {outputs['report']}")
    print(f"Replenish CSV: {outputs['replenish_csv']}")
    print(f"Clearance CSV: {outputs['clearance_csv']}")
    print(f"Category risk CSV: {outputs['category_csv']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
