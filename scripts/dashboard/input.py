#!/usr/bin/env python3
"""Input loading helpers for the inventory dashboard pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd


PRIMARY_INPUT = "郭文攀"


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


def infer_primary_store_from_retail(
    data: dict[str, pd.DataFrame], primary_input: str = PRIMARY_INPUT
) -> str | None:
    store_retail = data.get("store_retail", pd.DataFrame())
    required_columns = {"输入人", "店铺名称", "金额", "零售单号"}
    if store_retail.empty or not required_columns.issubset(store_retail.columns):
        return None

    primary_rows = store_retail[store_retail["输入人"].fillna("").astype(str).str.strip().eq(primary_input)].copy()
    if primary_rows.empty:
        return None

    grouped = (
        primary_rows.groupby("店铺名称")
        .agg(销售额=("金额", "sum"), 订单数=("零售单号", "nunique"))
        .reset_index()
        .sort_values(["销售额", "订单数", "店铺名称"], ascending=[False, False, True])
    )
    if grouped.empty:
        return None
    return str(grouped.iloc[0]["店铺名称"]).strip()


def infer_store_name(data: dict[str, pd.DataFrame], preferred_store: str | None) -> str:
    if preferred_store:
        return preferred_store

    primary_store = infer_primary_store_from_retail(data)
    if primary_store:
        return primary_store

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


def load_cleaned_store_data(
    input_dir: Path, preferred_store: str | None = None
) -> tuple[dict[str, pd.DataFrame], str]:
    reports = resolve_reports(input_dir)
    raw = load_data(reports)
    store_name = infer_store_name(raw, preferred_store)
    return clean_data(raw, store_name), store_name

