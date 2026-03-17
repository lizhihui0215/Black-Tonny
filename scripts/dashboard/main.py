#!/usr/bin/env python3
"""Build a non-technical inventory and sales dashboard from SQLite analysis data."""

from __future__ import annotations

import argparse
import calendar
import html
import json
import math
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
from scripts.dashboard.rendering import (
    build_charts,
    compact_list_html,
    compact_sentence_with_tip,
    fig_to_html,
    floating_tooltip_css,
    floating_tooltip_script,
    format_badge,
    inline_tip,
    insight_item,
    note_with_tip,
    render_empty,
    render_insights_html,
    render_insights_markdown,
    render_time_strategy_html,
    safe_cell_html,
    table_text_with_tip,
)
from scripts.dashboard.yeusoft import (
    build_yeusoft_report_highlights,
    classify_season_action,
    load_yeusoft_capture_bundle,
    normalize_product_season,
    safe_float,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = ROOT / "reports" / "dashboard-history"
DEFAULT_PAGES_DIR = ROOT / "site" / "dashboard"
DEFAULT_COST_FILE = ROOT / "data" / "local" / "store_cost_snapshot.json"
DEFAULT_COST_HISTORY_FILE = ROOT / "data" / "local" / "store_cost_history.json"
DEFAULT_YEU_CAPTURE_DIR = ROOT / "reports" / "capture-cache"
DEFAULT_ANALYSIS_DB_FILE = ROOT / "reports" / "calibration" / "black_tony_analysis.sqlite"
PRIMARY_INPUT = "郭文攀"
BEIJING_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_MONTHLY_OPERATING_EXPENSE = 20000.0
DEFAULT_ANALYSIS_WINDOW_DAYS = 8
SEASON_STRATEGY_TOOLTIPS = {
    "当季主推": "为什么：这类商品正在主销季，补货最容易直接转成营业额。怎么做：先补销量高、库存浅的中类，再补核心尺码和主销色。好处：能减少断码和错失成交。注意：别平均补货，避免把预算摊薄。",
    "下一季试补": "为什么：这类商品接近主销窗口，但还没到最强主卖期。怎么做：先小量试补 1-2 个颜色和核心尺码，观察 1 周左右。好处：能提前卡位，不至于季节一到就断货。注意：不要一次压深，避免变成跨季库存。",
    "跨季去化": "为什么：这类商品已经偏离当前主销季，再补货的成功率低。怎么做：有库存就先去化，没有库存就先停补。好处：能把预算腾给当季主销款。注意：不要把它和当季补货混在一起看。",
    "暂缓补货": "为什么：当前不是重点投入方向。怎么做：先观察销售、陈列和季节节奏，再决定是否恢复补货。好处：能减少无效进货。注意：暂缓不等于永远不补，要定期复核。",
}
STATUS_TOOLTIPS = {
    "高压货": "为什么：库存金额明显高于销售金额，说明货压得重。怎么做：先停补，再做组合促销、清货位和陈列前移。好处：能先释放库存压力。注意：不要一边去化一边继续深补。",
    "需关注": "为什么：库存和销售开始失衡，但还没到最严重。怎么做：连续盯 1-2 周，必要时先收紧补货。好处：能更早止损。注意：不要因为短期一两天销量回升就放松。",
    "相对健康": "为什么：库存与销售关系还算平衡。怎么做：维持当前补货节奏，重点防断货。好处：能把精力留给问题更大的区域。注意：健康不代表不用看，仍要持续复盘。",
}
ACTION_TOOLTIPS = {
    "立即补货": "为什么：这是主销且库存已经很浅。怎么做：今天先补核心尺码、主销色和高频成交款。好处：能最快保住营业额。注意：先补最赚钱的款，不是全款平均补。",
    "优先补货": "为什么：补货紧迫，但还没到必须当天清完。怎么做：先补最能带营业额的款，后续再补次重点。好处：预算利用率更高。注意：别被低销售款分走预算。",
    "先校库存再补货": "为什么：系统库存不准时，任何补货结论都可能错。怎么做：先查盘点、调拨和销售回写，再决定要不要补。好处：能避免误补和重复补。注意：这一步必须优先于补货动作。",
    "小量试补": "为什么：商品有机会，但信号还不够强。怎么做：少量补货试销，先看 1-2 周表现。好处：能控制风险。注意：不要直接压成深库存。",
    "先停补再去化": "为什么：现有库存已经够多，再补只会更压。怎么做：先停新补货，再做组合价、第二件优惠、门口清货位。好处：能先回收现金流。注意：去化阶段不要追求毛利最大化。",
    "观察并做组合去化": "为什么：当前不适合深补，但也不一定要立刻清仓。怎么做：用搭配销售、组合价和会员提醒慢慢去化。好处：能温和出货。注意：连续 1-2 周无改善就要升级动作。",
    "优先去化": "为什么：这类库存当前更需要卖掉而不是继续补。怎么做：陈列前移、组合促销、会员触达一起做。好处：能先降库存再释放预算。注意：不要和当季主销货抢主陈列位。",
    "跨季不补货": "为什么：当前不是它的主销季。怎么做：有库存先去化，没库存先停。好处：避免新货变旧货。注意：等回到主销季再重新判断。",
    "暂缓补货": "为什么：当前补货优先级不高。怎么做：先把预算和货位留给主销品类。好处：能减少无效投入。注意：后续要定期复核，不是永久冻结。",
}
HIGH_FREQUENCY_ACTION_TOOLTIPS = {
    "先处理负库存": "为什么：负库存会让补货和去化判断失真。怎么做：先核对盘点、调拨和销售回写。好处：后面的经营动作才不会跑偏。注意：别在没校正库存前直接下补货单。",
    "先去库存": "为什么：库存压力已经高于当前销售承接能力。怎么做：先暂停深补，再做清货位、组合价、会员定向去化。好处：先回现金再谈增长。注意：别把主销款一起打乱。",
    "控制库存量": "为什么：继续进货会把压力推大。怎么做：收紧进货和补货节奏，把预算留给主销品类。好处：减少压货。注意：不能一刀切停补，要保主销不断码。",
    "处理跨季品类": "为什么：跨季货在当前阶段周转效率低。怎么做：有库存先去化，没库存先别追补。好处：把货位和预算让给当季。注意：跨季货要单独管理。",
    "联系高价值会员": "为什么：老客最容易贡献稳定销售。怎么做：优先联系购买金额高、消费次数多的会员，做换季提醒和试穿邀约。好处：提升复购最直接。注意：不要只群发无差别促销。",
    "安排去库存动作": "为什么：只看到风险还不够，要落到动作。怎么做：明确哪些停补、哪些清货位、哪些做组合促销。好处：执行更快。注意：动作要有人负责和复盘。",
    "确认跨季处理": "为什么：跨季货最容易越拖越难卖。怎么做：老板拍板是去化、暂缓还是等下季。好处：减少反复摇摆。注意：不要混进当季补货预算。",
    "停止补货": "为什么：当前库存已经足够甚至偏多。怎么做：先停新进货，把现有库存先卖掉。好处：减少继续压货。注意：要区分停补的是问题品类，不是所有货。",
    "组合促销": "为什么：慢销货单独推不好卖。怎么做：和基础款、低决策商品做组合价。好处：提高成交率。注意：要控制折扣，不要把主销毛利一起拖低。",
    "清货陈列": "为什么：顾客先看到，去化效率才会起来。怎么做：把需要优先卖掉的货放到门口或主通道。好处：提升曝光。注意：不能让清货区压过主销区。",
    "控制补货": "为什么：补货方向对，但节奏要收。怎么做：先补销量高、库存低的主销款。好处：降低预算浪费。注意：不要平均补货。",
    "组合去化": "为什么：搭配卖比单独推慢销货更容易成交。怎么做：和基础款、袜品、家居服一起卖。好处：提升连带。注意：搭配要同客群、同场景。",
    "调整陈列": "为什么：陈列会直接影响试穿和成交。怎么做：前移主销、压缩慢销、分区更清楚。好处：让货更会说话。注意：调整后要观察 3-7 天数据。",
    "稳住会员复购": "为什么：复购比重新获客更省成本。怎么做：用换季提醒、到店试穿和组合推荐维持联系。好处：销售更稳。注意：不要打扰过频。",
}


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


def normalize_compare_timestamp(value: object) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        return timestamp.tz_convert(BEIJING_TZ).tz_localize(None)
    return timestamp


def load_cost_snapshot(cost_file: Path | None) -> dict | None:
    if not cost_file or not cost_file.exists():
        return None
    return json.loads(cost_file.read_text(encoding="utf-8"))


def load_cost_history(cost_history_file: Path | None) -> list[dict]:
    if not cost_history_file or not cost_history_file.exists():
        return []
    payload = json.loads(cost_history_file.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        snapshots = payload.get("snapshots")
        if isinstance(snapshots, list):
            return [item for item in snapshots if isinstance(item, dict)]
    return []


def read_analysis_sql(
    conn: sqlite3.Connection,
    query: str,
    *,
    params: list[object] | None = None,
) -> pd.DataFrame:
    return pd.read_sql_query(query, conn, params=params or [])


def load_analysis_db_snapshot(db_path: Path | None, store_name: str | None) -> dict | None:
    if not db_path or not db_path.exists():
        return None

    try:
        conn = sqlite3.connect(db_path)
        latest_batch = read_analysis_sql(
            conn,
            "SELECT batch_id, created_at, store_name FROM latest_import_batch",
        )
        if latest_batch.empty:
            conn.close()
            return None

        batch_id = str(latest_batch.iloc[0]["batch_id"])
        batch_created_at = pd.to_datetime(latest_batch.iloc[0]["created_at"], errors="coerce")
        effective_store_name = str(store_name or latest_batch.iloc[0]["store_name"]).strip()
        master_lines = read_analysis_sql(
            conn,
            """
            SELECT
                store_name,
                input_user,
                sale_date,
                sale_day,
                sale_month,
                order_no,
                line_no,
                sku,
                color,
                size,
                guide_name,
                member_card,
                product_major_type,
                product_middle_type,
                product_minor_type,
                qty,
                sales_amount,
                tag_amount,
                unit_price,
                discount_rate,
                doc_type,
                is_prop
            FROM latest_master_sales_order_lines
            WHERE store_name = ?
            ORDER BY sale_date
            """,
            params=[effective_store_name],
        )
        validation_lines = read_analysis_sql(
            conn,
            """
            SELECT
                store_name,
                input_user,
                sale_date,
                sale_day,
                sale_month,
                order_no,
                line_no,
                sku,
                color,
                size,
                qty,
                sales_amount,
                tag_amount,
                unit_price,
                discount_rate,
                doc_type,
                member_card,
                guide_name,
                product_major_type,
                product_middle_type,
                product_minor_type
            FROM latest_sales_order_lines
            WHERE source_role = 'validation'
            ORDER BY sale_date
            """,
        )
        daily_summary = read_analysis_sql(
            conn,
            """
            SELECT sale_date, net_sales_amount, net_sales_qty, core_order_count, prop_net_sales_amount
            FROM latest_daily_sales_summary
            ORDER BY sale_date
            """,
        )
        monthly_summary = read_analysis_sql(
            conn,
            """
            SELECT month, net_sales_amount
            FROM latest_monthly_sales_summary
            ORDER BY month
            """,
        )
        product_snapshot = read_analysis_sql(
            conn,
            """
            SELECT
                sku,
                color,
                cumulative_sales_qty,
                cumulative_sales_amount,
                cumulative_return_qty,
                current_stock_qty,
                arrival_qty,
                category_name,
                first_arrival_date,
                first_sale_date,
                is_prop
            FROM product_sales_snapshot
            WHERE batch_id = ? AND store_name = ?
            """,
            params=[batch_id, effective_store_name],
        )
        inventory_detail_snapshot = read_analysis_sql(
            conn,
            """
            SELECT *
            FROM latest_inventory_detail_snapshots
            WHERE store_name = ?
            """,
            params=[effective_store_name],
        )
        inventory_sales_snapshot = read_analysis_sql(
            conn,
            """
            SELECT *
            FROM latest_inventory_sales_snapshots
            WHERE store_name = ?
            """,
            params=[effective_store_name],
        )
        stock_flow_snapshot = read_analysis_sql(
            conn,
            """
            SELECT *
            FROM latest_stock_flow_snapshots
            WHERE store_name = ?
            """,
            params=[effective_store_name],
        )
        size_breakdowns = read_analysis_sql(
            conn,
            """
            SELECT *
            FROM latest_size_metric_breakdowns
            WHERE store_name = ?
            """,
            params=[effective_store_name],
        )
        vip_members = read_analysis_sql(
            conn,
            """
            SELECT *
            FROM latest_vip_analysis_members
            WHERE store_name = ?
            """,
            params=[effective_store_name],
        )
        member_rank = read_analysis_sql(
            conn,
            """
            SELECT *
            FROM latest_member_sales_rank
            WHERE store_name = ?
            """,
            params=[effective_store_name],
        )
        guide_summary = read_analysis_sql(
            conn,
            """
            SELECT *
            FROM latest_guide_report_summary
            WHERE store_name = ?
            """,
            params=[effective_store_name],
        )
        retail_detail_snapshot = read_analysis_sql(
            conn,
            """
            SELECT *
            FROM latest_retail_detail_snapshots
            WHERE store_name = ?
            """,
            params=[effective_store_name],
        )
        movement_docs = read_analysis_sql(
            conn,
            """
            SELECT *
            FROM movement_docs
            WHERE batch_id = ? AND store_name = ?
            """,
            params=[batch_id, effective_store_name],
        )
        quality_checks = read_analysis_sql(
            conn,
            """
            SELECT check_name, status, observed_value
            FROM quality_checks
            WHERE batch_id = ?
            ORDER BY check_name
            """,
            params=[batch_id],
        )
        conn.close()
    except Exception:
        return None

    if master_lines.empty:
        return None

    for column in ("sale_date", "sale_day"):
        if column in master_lines.columns:
            master_lines[column] = pd.to_datetime(master_lines[column], errors="coerce")
        if column in validation_lines.columns:
            validation_lines[column] = pd.to_datetime(validation_lines[column], errors="coerce")
    if "sale_date" in daily_summary.columns:
        daily_summary["sale_date"] = pd.to_datetime(daily_summary["sale_date"], errors="coerce")
    for column in ("first_arrival_date", "first_sale_date"):
        if column in product_snapshot.columns:
            product_snapshot[column] = pd.to_datetime(product_snapshot[column], errors="coerce")
    for column in ("birth_date", "input_date", "last_sale_date"):
        if column in vip_members.columns:
            vip_members[column] = pd.to_datetime(vip_members[column], errors="coerce")
    for column in ("come_date", "receive_date"):
        if column in movement_docs.columns:
            movement_docs[column] = pd.to_datetime(movement_docs[column], errors="coerce")
    if "is_prop" in master_lines.columns:
        master_lines["is_prop"] = master_lines["is_prop"].fillna(0).astype(int).astype(bool)
    if "is_prop" in product_snapshot.columns:
        product_snapshot["is_prop"] = product_snapshot["is_prop"].fillna(0).astype(int).astype(bool)

    return {
        "batch_id": batch_id,
        "batch_created_at": batch_created_at,
        "store_name": effective_store_name,
        "master_lines": master_lines,
        "validation_lines": validation_lines,
        "daily_summary": daily_summary,
        "monthly_summary": monthly_summary,
        "product_snapshot": product_snapshot,
        "inventory_detail_snapshot": inventory_detail_snapshot,
        "inventory_sales_snapshot": inventory_sales_snapshot,
        "stock_flow_snapshot": stock_flow_snapshot,
        "size_breakdowns": size_breakdowns,
        "vip_members": vip_members,
        "member_rank": member_rank,
        "guide_summary": guide_summary,
        "retail_detail_snapshot": retail_detail_snapshot,
        "movement_docs": movement_docs,
        "quality_checks": quality_checks,
    }


def build_dashboard_sales_frame_from_lines(frame: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "销售日期",
        "店铺名称",
        "输入人",
        "零售单号",
        "明细流水",
        "款号",
        "颜色",
        "尺码",
        "数量",
        "金额",
        "吊牌金额",
        "单价",
        "折扣",
        "单据类型",
        "会员卡号",
        "导购员",
        "商品大类",
        "商品中类",
        "商品小类",
    ]
    if frame.empty:
        return pd.DataFrame(columns=columns)

    return pd.DataFrame(
        {
            "销售日期": pd.to_datetime(frame.get("sale_date"), errors="coerce"),
            "店铺名称": frame.get("store_name", "").fillna("").astype(str).str.strip(),
            "输入人": frame.get("input_user", "").fillna("").astype(str).str.strip(),
            "零售单号": frame.get("order_no", "").fillna("").astype(str).str.strip(),
            "明细流水": frame.get("line_no", "").fillna("").astype(str).str.strip(),
            "款号": frame.get("sku", "").fillna("").astype(str).str.strip(),
            "颜色": frame.get("color", "").fillna("").astype(str).str.strip(),
            "尺码": frame.get("size", "").fillna("").astype(str).str.strip(),
            "数量": pd.to_numeric(frame.get("qty", 0), errors="coerce").fillna(0.0),
            "金额": pd.to_numeric(frame.get("sales_amount", 0), errors="coerce").fillna(0.0),
            "吊牌金额": pd.to_numeric(frame.get("tag_amount", 0), errors="coerce").fillna(0.0),
            "单价": pd.to_numeric(frame.get("unit_price", 0), errors="coerce").fillna(0.0),
            "折扣": pd.to_numeric(frame.get("discount_rate", 0), errors="coerce").fillna(0.0),
            "单据类型": frame.get("doc_type", "").fillna("").astype(str).str.strip(),
            "会员卡号": frame.get("member_card", "").fillna("").astype(str).str.strip().replace("", pd.NA),
            "导购员": frame.get("guide_name", "").fillna("").astype(str).str.strip().replace("", pd.NA),
            "商品大类": frame.get("product_major_type", "").fillna("").astype(str).str.strip(),
            "商品中类": frame.get("product_middle_type", "").fillna("").astype(str).str.strip(),
            "商品小类": frame.get("product_minor_type", "").fillna("").astype(str).str.strip(),
        }
    )


def build_inventory_detail_from_analysis(analysis_snapshot: dict, store_name: str) -> pd.DataFrame:
    snapshots = analysis_snapshot.get("inventory_detail_snapshot", pd.DataFrame()).copy()
    size_breakdowns = analysis_snapshot.get("size_breakdowns", pd.DataFrame()).copy()
    stock_flow = analysis_snapshot.get("stock_flow_snapshot", pd.DataFrame()).copy()
    columns = [
        "店铺",
        "大类",
        "中类",
        "小类",
        "款号",
        "品名",
        "颜色",
        "尺码",
        "库存",
        "库存额",
        "在途库存",
        "在途库存额",
        "零售价",
    ]
    if snapshots.empty:
        return pd.DataFrame(columns=columns)

    if {"source_name", "metric_scope", "snapshot_id", "size_label", "metric_value"}.issubset(
        size_breakdowns.columns
    ):
        size_rows = size_breakdowns[
            size_breakdowns["source_name"].eq("capture_inventory_detail")
            & size_breakdowns["metric_scope"].eq("stock_qty")
        ][["snapshot_id", "size_label", "metric_value"]].copy()
    else:
        size_rows = pd.DataFrame(columns=["snapshot_id", "size_label", "metric_value"])

    expanded = snapshots.merge(size_rows, on="snapshot_id", how="left")
    expanded["size_label"] = expanded["size_label"].fillna("未拆码")
    expanded["metric_value"] = pd.to_numeric(
        expanded["metric_value"].fillna(expanded["total_stock_qty"]),
        errors="coerce",
    ).fillna(0.0)

    wait_stock = (
        stock_flow.groupby(["sku", "color"], as_index=False)
        .agg(wait_stock_qty=("wait_stock_qty", "sum"))
        if not stock_flow.empty
        else pd.DataFrame(columns=["sku", "color", "wait_stock_qty"])
    )
    expanded = expanded.merge(wait_stock, on=["sku", "color"], how="left")
    expanded["wait_stock_qty"] = pd.to_numeric(expanded["wait_stock_qty"], errors="coerce").fillna(0.0)

    total_stock_qty = pd.to_numeric(expanded["total_stock_qty"], errors="coerce").fillna(0.0)
    expanded["allocation_ratio"] = 0.0
    non_zero = total_stock_qty.ne(0)
    expanded.loc[non_zero, "allocation_ratio"] = (
        expanded.loc[non_zero, "metric_value"] / total_stock_qty[non_zero]
    )
    expanded["inventory_amount"] = (
        pd.to_numeric(expanded["total_stock_amount"], errors="coerce").fillna(0.0)
        * expanded["allocation_ratio"]
    )
    fallback_amount = (
        pd.to_numeric(expanded["retail_price"], errors="coerce").fillna(0.0)
        * expanded["metric_value"]
    )
    expanded["inventory_amount"] = expanded["inventory_amount"].where(non_zero, fallback_amount)
    expanded["wait_qty_allocated"] = expanded["wait_stock_qty"] * expanded["allocation_ratio"]
    expanded["wait_amount_allocated"] = (
        pd.to_numeric(expanded["retail_price"], errors="coerce").fillna(0.0)
        * expanded["wait_qty_allocated"]
    )

    return pd.DataFrame(
        {
            "店铺": store_name,
            "大类": expanded.get("product_major_type", "").fillna("").astype(str).str.strip(),
            "中类": expanded.get("product_middle_type", "").fillna("").astype(str).str.strip(),
            "小类": expanded.get("product_minor_type", "").fillna("").astype(str).str.strip(),
            "款号": expanded.get("sku", "").fillna("").astype(str).str.strip(),
            "品名": expanded.get("product_name", "").fillna("").astype(str).str.strip(),
            "颜色": expanded.get("color", "").fillna("").astype(str).str.strip(),
            "尺码": expanded.get("size_label", "").fillna("").astype(str).str.strip(),
            "库存": expanded["metric_value"],
            "库存额": expanded["inventory_amount"],
            "在途库存": expanded["wait_qty_allocated"],
            "在途库存额": expanded["wait_amount_allocated"],
            "零售价": pd.to_numeric(expanded.get("retail_price", 0), errors="coerce").fillna(0.0),
        }
    )


def build_inventory_sales_from_analysis(analysis_snapshot: dict, store_name: str) -> pd.DataFrame:
    snapshots = analysis_snapshot.get("inventory_sales_snapshot", pd.DataFrame()).copy()
    detail_snapshots = analysis_snapshot.get("inventory_detail_snapshot", pd.DataFrame()).copy()
    columns = [
        "店铺名称",
        "大类",
        "中类",
        "小类",
        "款号",
        "品名",
        "颜色",
        "零售小计",
        "零售金额",
        "库存小计",
        "库存金额",
        "存销比",
        "零售价",
    ]
    if snapshots.empty:
        return pd.DataFrame(columns=columns)

    stock_ref = (
        detail_snapshots[["sku", "color", "total_stock_qty", "total_stock_amount"]]
        .drop_duplicates(subset=["sku", "color"])
        if not detail_snapshots.empty
        else pd.DataFrame(columns=["sku", "color", "total_stock_qty", "total_stock_amount"])
    )
    merged = snapshots.merge(stock_ref, on=["sku", "color"], how="left")
    return pd.DataFrame(
        {
            "店铺名称": store_name,
            "大类": merged.get("product_major_type", "").fillna("").astype(str).str.strip(),
            "中类": merged.get("product_middle_type", "").fillna("").astype(str).str.strip(),
            "小类": merged.get("product_minor_type", "").fillna("").astype(str).str.strip(),
            "款号": merged.get("sku", "").fillna("").astype(str).str.strip(),
            "品名": merged.get("product_name", "").fillna("").astype(str).str.strip(),
            "颜色": merged.get("color", "").fillna("").astype(str).str.strip(),
            "零售小计": pd.to_numeric(merged.get("total_retail_qty", 0), errors="coerce").fillna(0.0),
            "零售金额": pd.to_numeric(merged.get("total_retail_amount", 0), errors="coerce").fillna(0.0),
            "库存小计": pd.to_numeric(merged.get("total_stock_qty", 0), errors="coerce").fillna(0.0),
            "库存金额": pd.to_numeric(merged.get("total_stock_amount", 0), errors="coerce").fillna(0.0),
            "存销比": pd.to_numeric(merged.get("stock_sale_ratio", 0), errors="coerce").fillna(0.0),
            "零售价": pd.to_numeric(merged.get("retail_price", 0), errors="coerce").fillna(0.0),
        }
    )


def build_stock_flow_from_analysis(analysis_snapshot: dict) -> pd.DataFrame:
    snapshots = analysis_snapshot.get("stock_flow_snapshot", pd.DataFrame()).copy()
    columns = [
        "商品款号",
        "商品名称",
        "大类",
        "中类",
        "小类",
        "期初数量",
        "到货数量",
        "调入数量",
        "退货数量",
        "调出数量",
        "零售数量",
        "账面库存",
        "报损数量",
        "实际库存",
        "在途库存",
        "动销率",
        "零售价",
        "颜色",
    ]
    if snapshots.empty:
        return pd.DataFrame(columns=columns)

    return pd.DataFrame(
        {
            "商品款号": snapshots.get("sku", "").fillna("").astype(str).str.strip(),
            "商品名称": snapshots.get("product_name", "").fillna("").astype(str).str.strip(),
            "大类": snapshots.get("product_major_type", "").fillna("").astype(str).str.strip(),
            "中类": snapshots.get("product_middle_type", "").fillna("").astype(str).str.strip(),
            "小类": snapshots.get("product_minor_type", "").fillna("").astype(str).str.strip(),
            "期初数量": pd.to_numeric(snapshots.get("opening_qty", 0), errors="coerce").fillna(0.0),
            "到货数量": pd.to_numeric(snapshots.get("arrival_qty", 0), errors="coerce").fillna(0.0),
            "调入数量": pd.to_numeric(snapshots.get("transfer_in_qty", 0), errors="coerce").fillna(0.0),
            "退货数量": pd.to_numeric(snapshots.get("return_qty", 0), errors="coerce").fillna(0.0),
            "调出数量": pd.to_numeric(snapshots.get("transfer_out_qty", 0), errors="coerce").fillna(0.0),
            "零售数量": pd.to_numeric(snapshots.get("sale_qty", 0), errors="coerce").fillna(0.0),
            "账面库存": pd.to_numeric(snapshots.get("ledger_stock_qty", 0), errors="coerce").fillna(0.0),
            "报损数量": pd.to_numeric(snapshots.get("damage_qty", 0), errors="coerce").fillna(0.0),
            "实际库存": pd.to_numeric(snapshots.get("actual_stock_qty", 0), errors="coerce").fillna(0.0),
            "在途库存": pd.to_numeric(snapshots.get("wait_stock_qty", 0), errors="coerce").fillna(0.0),
            "动销率": pd.to_numeric(snapshots.get("sell_through_rate", 0), errors="coerce").fillna(0.0),
            "零售价": pd.to_numeric(snapshots.get("retail_price", 0), errors="coerce").fillna(0.0),
            "颜色": snapshots.get("color", "").fillna("").astype(str).str.strip(),
        }
    )


def build_guide_from_analysis(analysis_snapshot: dict) -> pd.DataFrame:
    guide_summary = analysis_snapshot.get("guide_summary", pd.DataFrame()).copy()
    columns = ["导购员", "销量", "实收金额", "票数", "单效", "连带", "会员销额", "会员销量"]
    if guide_summary.empty:
        return pd.DataFrame(columns=columns)

    return pd.DataFrame(
        {
            "导购员": guide_summary.get("guide_name", "").fillna("").astype(str).str.strip(),
            "销量": pd.to_numeric(guide_summary.get("sale_qty", 0), errors="coerce").fillna(0.0),
            "实收金额": pd.to_numeric(guide_summary.get("sale_amount", 0), errors="coerce").fillna(0.0),
            "票数": pd.to_numeric(guide_summary.get("order_count", 0), errors="coerce").fillna(0.0),
            "单效": pd.to_numeric(guide_summary.get("average_ticket", 0), errors="coerce").fillna(0.0),
            "连带": pd.to_numeric(guide_summary.get("attachment_rate", 0), errors="coerce").fillna(0.0),
            "会员销额": pd.to_numeric(guide_summary.get("vip_sale_amount", 0), errors="coerce").fillna(0.0),
            "会员销量": pd.to_numeric(guide_summary.get("vip_sale_qty", 0), errors="coerce").fillna(0.0),
        }
    )


def build_members_from_analysis(analysis_snapshot: dict) -> pd.DataFrame:
    members = analysis_snapshot.get("vip_members", pd.DataFrame()).copy()
    columns = ["VIP姓名", "服务导购", "购买金额", "购买总数", "消费次数/年", "平均单笔消费额", "储值余额"]
    if members.empty:
        return pd.DataFrame(columns=columns)

    return pd.DataFrame(
        {
            "VIP姓名": members.get("vip_name", "").fillna("").astype(str).str.strip(),
            "服务导购": members.get("operator_name", "").fillna("").astype(str).str.strip(),
            "购买金额": pd.to_numeric(members.get("total_sale_amount", 0), errors="coerce").fillna(0.0),
            "购买总数": pd.to_numeric(members.get("sale_stock_qty", 0), errors="coerce").fillna(0.0),
            "消费次数/年": pd.to_numeric(members.get("sale_count_per_year", 0), errors="coerce").fillna(0.0),
            "平均单笔消费额": pd.to_numeric(members.get("avg_sale_amount", 0), errors="coerce").fillna(0.0),
            "储值余额": pd.to_numeric(members.get("stored_value_balance", 0), errors="coerce").fillna(0.0),
        }
    )


def build_product_sales_from_analysis(analysis_snapshot: dict) -> pd.DataFrame:
    product_snapshot = analysis_snapshot.get("product_snapshot", pd.DataFrame()).copy()
    retail_detail = analysis_snapshot.get("retail_detail_snapshot", pd.DataFrame()).copy()
    inventory_detail = analysis_snapshot.get("inventory_detail_snapshot", pd.DataFrame()).copy()
    columns = [
        "款号",
        "品名",
        "颜色",
        "大类",
        "中类",
        "小类",
        "年份",
        "季节",
        "波段",
        "销售数",
        "销售金额",
        "累销",
        "累销额",
        "总到货",
        "周期售罄",
        "总售罄",
        "库存",
        "总退货",
        "已销天",
        "首次到货日期",
        "首次销售日期",
    ]
    if product_snapshot.empty:
        return pd.DataFrame(columns=columns)

    retail_ref = (
        retail_detail[
            [
                "sku",
                "color",
                "product_name",
                "product_major_type",
                "product_middle_type",
                "product_minor_type",
                "year_label",
                "season",
                "period_label",
                "total_qty",
                "total_sale_amount",
            ]
        ]
        .drop_duplicates(subset=["sku", "color"])
        .rename(
            columns={
                "product_name": "product_name_retail",
                "product_major_type": "major_type_retail",
                "product_middle_type": "middle_type_retail",
                "product_minor_type": "minor_type_retail",
                "year_label": "year_label_retail",
                "season": "season_retail",
                "period_label": "period_label_retail",
            }
        )
        if not retail_detail.empty
        else pd.DataFrame(
            columns=[
                "sku",
                "color",
                "product_name_retail",
                "major_type_retail",
                "middle_type_retail",
                "minor_type_retail",
                "year_label_retail",
                "season_retail",
                "period_label_retail",
                "total_qty",
                "total_sale_amount",
            ]
        )
    )
    inventory_ref = (
        inventory_detail[
            [
                "sku",
                "color",
                "product_name",
                "product_major_type",
                "product_middle_type",
                "product_minor_type",
                "year_label",
                "season",
                "period_label",
                "total_stock_qty",
            ]
        ]
        .drop_duplicates(subset=["sku", "color"])
        .rename(
            columns={
                "product_name": "product_name_inventory",
                "product_major_type": "major_type_inventory",
                "product_middle_type": "middle_type_inventory",
                "product_minor_type": "minor_type_inventory",
                "year_label": "year_label_inventory",
                "season": "season_inventory",
                "period_label": "period_label_inventory",
            }
        )
        if not inventory_detail.empty
        else pd.DataFrame(
            columns=[
                "sku",
                "color",
                "product_name_inventory",
                "major_type_inventory",
                "middle_type_inventory",
                "minor_type_inventory",
                "year_label_inventory",
                "season_inventory",
                "period_label_inventory",
                "total_stock_qty",
            ]
        )
    )
    merged = product_snapshot.merge(retail_ref, on=["sku", "color"], how="left").merge(
        inventory_ref,
        on=["sku", "color"],
        how="left",
    )

    merged["product_name_final"] = merged.get("product_name_retail").combine_first(
        merged.get("product_name_inventory")
    )
    merged["major_type_final"] = merged.get("major_type_retail").combine_first(
        merged.get("major_type_inventory")
    )
    merged["middle_type_final"] = merged.get("middle_type_retail").combine_first(
        merged.get("middle_type_inventory")
    )
    merged["minor_type_final"] = merged.get("minor_type_retail").combine_first(
        merged.get("minor_type_inventory")
    )
    merged["year_label_final"] = merged.get("year_label_retail").combine_first(
        merged.get("year_label_inventory")
    )
    merged["season_final"] = merged.get("season_retail").combine_first(
        merged.get("season_inventory")
    )
    merged["period_label_final"] = merged.get("period_label_retail").combine_first(
        merged.get("period_label_inventory")
    )

    period_sales_qty = pd.to_numeric(merged.get("total_qty", 0), errors="coerce").fillna(0.0)
    period_sales_amount = pd.to_numeric(merged.get("total_sale_amount", 0), errors="coerce").fillna(0.0)
    current_stock_qty = pd.to_numeric(merged.get("total_stock_qty"), errors="coerce").fillna(
        pd.to_numeric(merged.get("current_stock_qty", 0), errors="coerce").fillna(0.0)
    )
    cumulative_sales_qty = pd.to_numeric(merged.get("cumulative_sales_qty", 0), errors="coerce").fillna(0.0)
    arrival_qty = pd.to_numeric(merged.get("arrival_qty", 0), errors="coerce").fillna(0.0)
    cycle_denominator = period_sales_qty + current_stock_qty
    period_sell_through = pd.Series(0.0, index=merged.index)
    cycle_non_zero = cycle_denominator.ne(0)
    period_sell_through.loc[cycle_non_zero] = (
        period_sales_qty.loc[cycle_non_zero] / cycle_denominator.loc[cycle_non_zero]
    )
    total_sell_through = pd.Series(0.0, index=merged.index)
    arrival_non_zero = arrival_qty.ne(0)
    total_sell_through.loc[arrival_non_zero] = (
        cumulative_sales_qty.loc[arrival_non_zero] / arrival_qty.loc[arrival_non_zero]
    )

    batch_created_at = pd.to_datetime(analysis_snapshot.get("batch_created_at"), errors="coerce")
    first_sale_date = pd.to_datetime(merged.get("first_sale_date"), errors="coerce")
    sold_days = pd.Series(0.0, index=merged.index)
    if pd.notna(batch_created_at):
        valid_sale_days = first_sale_date.notna()
        sold_days.loc[valid_sale_days] = (
            batch_created_at.normalize() - first_sale_date.loc[valid_sale_days].dt.normalize()
        ).dt.days + 1

    return pd.DataFrame(
        {
            "款号": merged.get("sku", "").fillna("").astype(str).str.strip(),
            "品名": merged["product_name_final"].fillna("").astype(str).str.strip(),
            "颜色": merged.get("color", "").fillna("").astype(str).str.strip(),
            "大类": merged["major_type_final"].fillna("").astype(str).str.strip(),
            "中类": merged["middle_type_final"].fillna(merged.get("category_name", "")).astype(str).str.strip(),
            "小类": merged["minor_type_final"].fillna("").astype(str).str.strip(),
            "年份": merged["year_label_final"].fillna("").astype(str).str.strip(),
            "季节": merged["season_final"].fillna("").astype(str).str.strip(),
            "波段": merged["period_label_final"].fillna("").astype(str).str.strip(),
            "销售数": period_sales_qty,
            "销售金额": period_sales_amount,
            "累销": cumulative_sales_qty,
            "累销额": pd.to_numeric(merged.get("cumulative_sales_amount", 0), errors="coerce").fillna(0.0),
            "总到货": arrival_qty,
            "周期售罄": period_sell_through,
            "总售罄": total_sell_through,
            "库存": current_stock_qty,
            "总退货": pd.to_numeric(merged.get("cumulative_return_qty", 0), errors="coerce").fillna(0.0),
            "已销天": sold_days.clip(lower=0),
            "首次到货日期": pd.to_datetime(merged.get("first_arrival_date"), errors="coerce"),
            "首次销售日期": first_sale_date,
        }
    )


def build_movement_from_analysis(analysis_snapshot: dict, store_name: str) -> pd.DataFrame:
    movement_docs = analysis_snapshot.get("movement_docs", pd.DataFrame()).copy()
    columns = ["单据类型", "单据状态", "调拨类型", "发货店铺", "接收店铺", "数量", "吊牌金额", "发货时间", "接收时间"]
    if movement_docs.empty:
        return pd.DataFrame(columns=columns)

    if "to_store" in movement_docs.columns:
        movement_docs = movement_docs[
            movement_docs["to_store"].fillna("").astype(str).str.strip().eq(store_name)
        ].copy()
    return pd.DataFrame(
        {
            "单据类型": movement_docs.get("doc_type", "").fillna("").astype(str).str.strip(),
            "单据状态": movement_docs.get("doc_status", "").fillna("").astype(str).str.strip(),
            "调拨类型": movement_docs.get("transfer_type", "").fillna("").astype(str).str.strip(),
            "发货店铺": movement_docs.get("from_store", "").fillna("").astype(str).str.strip(),
            "接收店铺": movement_docs.get("to_store", "").fillna("").astype(str).str.strip(),
            "数量": pd.to_numeric(movement_docs.get("qty", 0), errors="coerce").fillna(0.0),
            "吊牌金额": pd.to_numeric(movement_docs.get("amount", 0), errors="coerce").fillna(0.0),
            "发货时间": pd.to_datetime(movement_docs.get("come_date"), errors="coerce"),
            "接收时间": pd.to_datetime(movement_docs.get("receive_date"), errors="coerce"),
        }
    )


def build_dashboard_data_from_analysis(analysis_snapshot: dict, store_name: str) -> dict[str, pd.DataFrame]:
    return {
        "sales": build_dashboard_sales_frame_from_lines(analysis_snapshot.get("master_lines", pd.DataFrame())),
        "inventory_detail": build_inventory_detail_from_analysis(analysis_snapshot, store_name),
        "inventory_sales": build_inventory_sales_from_analysis(analysis_snapshot, store_name),
        "stock_flow": build_stock_flow_from_analysis(analysis_snapshot),
        "guide": build_guide_from_analysis(analysis_snapshot),
        "members": build_members_from_analysis(analysis_snapshot),
        "product_sales": build_product_sales_from_analysis(analysis_snapshot),
        "movement": build_movement_from_analysis(analysis_snapshot, store_name),
        "store_retail": build_dashboard_sales_frame_from_lines(
            analysis_snapshot.get("validation_lines", pd.DataFrame())
        ),
    }


def load_dashboard_data_from_analysis(
    db_path: Path | None,
    preferred_store: str | None,
) -> tuple[dict[str, pd.DataFrame], str, dict]:
    analysis_snapshot = load_analysis_db_snapshot(db_path, preferred_store)
    if not analysis_snapshot:
        raise FileNotFoundError(f"Missing usable SQLite analysis snapshot: {db_path}")
    store_name = str(analysis_snapshot.get("store_name", preferred_store or "")).strip()
    return build_dashboard_data_from_analysis(analysis_snapshot, store_name), store_name, analysis_snapshot


def infer_sales_window_days(sales_frame: pd.DataFrame) -> int:
    if sales_frame.empty or "销售日期" not in sales_frame.columns:
        return 0
    sales_dates = pd.to_datetime(sales_frame["销售日期"], errors="coerce").dropna()
    if sales_dates.empty:
        return 0
    return int((sales_dates.max().normalize() - sales_dates.min().normalize()).days + 1)


def build_sales_window_from_analysis(
    analysis_snapshot: dict | None,
    *,
    window_days: int,
) -> tuple[pd.DataFrame, dict[str, object]]:
    if not analysis_snapshot:
        return pd.DataFrame(), {}

    master_lines = analysis_snapshot.get("master_lines")
    monthly_summary = analysis_snapshot.get("monthly_summary")
    if master_lines is None:
        master_lines = pd.DataFrame()
    else:
        master_lines = master_lines.copy()
    if monthly_summary is None:
        monthly_summary = pd.DataFrame()
    else:
        monthly_summary = monthly_summary.copy()
    if master_lines.empty:
        return pd.DataFrame(), {}

    effective_window_days = max(int(window_days or 0), 8)
    master_lines["sale_day"] = pd.to_datetime(master_lines["sale_day"], errors="coerce")
    window_end = master_lines["sale_day"].max()
    if pd.isna(window_end):
        return pd.DataFrame(), {}
    window_start = window_end.normalize() - pd.Timedelta(days=effective_window_days - 1)
    window_lines = master_lines[
        master_lines["sale_day"].between(window_start, window_end.normalize(), inclusive="both")
    ].copy()
    if window_lines.empty:
        return pd.DataFrame(), {}

    sales_frame = pd.DataFrame(
        {
            "销售日期": pd.to_datetime(window_lines["sale_date"], errors="coerce"),
            "零售单号": window_lines["order_no"].astype(str),
            "数量": pd.to_numeric(window_lines["qty"], errors="coerce").fillna(0.0),
            "金额": pd.to_numeric(window_lines["sales_amount"], errors="coerce").fillna(0.0),
            "吊牌金额": pd.to_numeric(window_lines["tag_amount"], errors="coerce").fillna(0.0),
            "单价": pd.to_numeric(window_lines["unit_price"], errors="coerce").fillna(0.0),
            "折扣": pd.to_numeric(window_lines["discount_rate"], errors="coerce").fillna(0.0),
            "单据类型": window_lines["doc_type"].astype(str),
            "会员卡号": window_lines["member_card"].astype(str).str.strip().replace("", pd.NA),
            "导购员": window_lines["guide_name"].astype(str).str.strip().replace("", pd.NA),
            "商品大类": window_lines["product_major_type"].astype(str).str.strip(),
            "商品中类": window_lines["product_middle_type"].astype(str).str.strip(),
            "商品小类": window_lines["product_minor_type"].astype(str).str.strip(),
        }
    )
    current_month_label = get_beijing_now().strftime("%Y-%m")
    month_to_date_sales_amount = 0.0
    if not monthly_summary.empty and {"month", "net_sales_amount"}.issubset(monthly_summary.columns):
        current_month = monthly_summary[monthly_summary["month"].astype(str) == current_month_label]
        if not current_month.empty:
            month_to_date_sales_amount = float(current_month.iloc[0]["net_sales_amount"] or 0.0)

    return sales_frame, {
        "effective_window_days": effective_window_days,
        "window_start": window_start,
        "window_end": window_end.normalize(),
        "month_to_date_sales_amount": month_to_date_sales_amount,
    }



def build_profit_snapshot(raw_snapshot: dict | None) -> dict | None:
    if not raw_snapshot:
        return None

    snapshot_at = pd.to_datetime(raw_snapshot.get("snapshot_datetime"), errors="coerce")
    if pd.isna(snapshot_at):
        snapshot_dt = get_beijing_now()
    else:
        snapshot_dt = snapshot_at.to_pydatetime()
        if snapshot_dt.tzinfo is None:
            snapshot_dt = snapshot_dt.replace(tzinfo=BEIJING_TZ)
        else:
            snapshot_dt = snapshot_dt.astimezone(BEIJING_TZ)

    sales_amount = float(raw_snapshot.get("sales_amount", 0) or 0)
    purchase_cost = float(raw_snapshot.get("purchase_cost", 0) or 0)
    gross_profit = float(raw_snapshot.get("gross_profit", sales_amount - purchase_cost) or 0)
    gross_margin_rate = float(raw_snapshot.get("gross_margin_rate", safe_ratio(gross_profit, sales_amount)) or 0)

    (
        monthly_operating_expense,
        salary_total,
        total_expense,
        expense_items,
        salary_items,
        operating_expense_source,
    ) = resolve_effective_expense_values(raw_snapshot)
    net_profit = float(raw_snapshot.get("net_profit", gross_profit - total_expense) or 0)

    month_days = calendar.monthrange(snapshot_dt.year, snapshot_dt.month)[1]
    elapsed_days = snapshot_dt.day + safe_ratio(snapshot_dt.hour * 60 + snapshot_dt.minute, 1440)
    remaining_days = max(month_days - elapsed_days, 0)

    breakeven_available = gross_margin_rate > 0
    breakeven_sales = safe_ratio(total_expense, gross_margin_rate) if breakeven_available else 0.0
    breakeven_daily_sales = safe_ratio(breakeven_sales, month_days) if breakeven_available else 0.0
    average_daily_sales = safe_ratio(sales_amount, elapsed_days)
    average_daily_gross_profit = safe_ratio(gross_profit, elapsed_days)
    remaining_sales_to_breakeven = max(0.0, breakeven_sales - sales_amount) if breakeven_available else 0.0
    remaining_daily_sales_needed = safe_ratio(remaining_sales_to_breakeven, remaining_days) if breakeven_available else 0.0
    passed_breakeven = sales_amount >= breakeven_sales if breakeven_available and breakeven_sales else False
    net_margin_rate = safe_ratio(net_profit, sales_amount)
    expense_ratio = safe_ratio(total_expense, sales_amount)
    salary_ratio = safe_ratio(salary_total, sales_amount)
    operating_expense_ratio = safe_ratio(monthly_operating_expense, sales_amount)
    expense_coverage_ratio = safe_ratio(gross_profit, total_expense)
    breakeven_progress_ratio = safe_ratio(sales_amount, breakeven_sales) if breakeven_sales else 0.0
    projected_remaining_sales = average_daily_sales * remaining_days
    projected_remaining_gross_profit = projected_remaining_sales * gross_margin_rate
    projected_month_sales = sales_amount + projected_remaining_sales
    projected_month_gross_profit = gross_profit + projected_remaining_gross_profit
    projected_month_net_profit = projected_month_gross_profit - total_expense
    projected_monthly_status = (
        "green" if projected_month_net_profit > 0 else "yellow" if projected_month_gross_profit >= total_expense * 0.9 else "red"
    )
    fixed_cost_daily_burden = safe_ratio(monthly_operating_expense, month_days)
    salary_daily_burden = safe_ratio(salary_total, month_days)
    top_expense_item = max(expense_items, key=lambda item: float(item.get("amount", 0) or 0), default=None)
    top_salary_item = max(salary_items, key=lambda item: float(item.get("amount", 0) or 0), default=None)
    if (not top_expense_item or float(top_expense_item.get("amount", 0) or 0) <= 0) and monthly_operating_expense > 0:
        top_expense_item = {
            "name": "固定费用默认口径" if operating_expense_source != "当前成本快照" else "固定费用",
            "amount": monthly_operating_expense,
        }

    if passed_breakeven and net_profit > 0:
        status = "green"
        headline = "已过保本线"
    elif projected_month_net_profit > 0 or gross_profit >= total_expense * 0.9:
        status = "yellow"
        headline = "接近保本线"
    else:
        status = "red"
        headline = "未过保本线"

    if projected_month_net_profit > 0:
        forecast_headline = "按当前节奏月底大概率还能赚钱"
    elif projected_month_gross_profit >= total_expense:
        forecast_headline = "按当前节奏月底大概率刚过保本"
    else:
        forecast_headline = "按当前节奏月底还有亏损风险"

    return {
        "snapshot_name": raw_snapshot.get("snapshot_name", "成本快照"),
        "snapshot_datetime": snapshot_dt,
        "sales_amount": sales_amount,
        "purchase_cost": purchase_cost,
        "gross_profit": gross_profit,
        "gross_margin_rate": gross_margin_rate,
        "monthly_operating_expense": monthly_operating_expense,
        "salary_total": salary_total,
        "total_expense": total_expense,
        "operating_expense_source": operating_expense_source,
        "net_profit": net_profit,
        "net_margin_rate": net_margin_rate,
        "average_daily_gross_profit": average_daily_gross_profit,
        "expense_ratio": expense_ratio,
        "salary_ratio": salary_ratio,
        "operating_expense_ratio": operating_expense_ratio,
        "expense_coverage_ratio": expense_coverage_ratio,
        "breakeven_sales": breakeven_sales,
        "breakeven_daily_sales": breakeven_daily_sales,
        "breakeven_progress_ratio": breakeven_progress_ratio,
        "breakeven_available": breakeven_available,
        "average_daily_sales": average_daily_sales,
        "remaining_days": remaining_days,
        "remaining_sales_to_breakeven": remaining_sales_to_breakeven,
        "remaining_daily_sales_needed": remaining_daily_sales_needed,
        "projected_month_sales": projected_month_sales,
        "projected_remaining_sales": projected_remaining_sales,
        "projected_month_gross_profit": projected_month_gross_profit,
        "projected_remaining_gross_profit": projected_remaining_gross_profit,
        "projected_month_net_profit": projected_month_net_profit,
        "projected_monthly_status": projected_monthly_status,
        "forecast_headline": forecast_headline,
        "fixed_cost_daily_burden": fixed_cost_daily_burden,
        "salary_daily_burden": salary_daily_burden,
        "top_expense_item": top_expense_item,
        "top_salary_item": top_salary_item,
        "passed_breakeven": passed_breakeven,
        "status": status,
        "headline": headline,
        "expense_items": expense_items,
        "salary_items": salary_items,
        "notes": raw_snapshot.get("notes", []),
    }


def extract_snapshot_margin_rate(raw_snapshot: dict | None) -> float:
    if not raw_snapshot:
        return 0.0

    direct_rate = float(raw_snapshot.get("gross_margin_rate", 0) or 0)
    if direct_rate > 0:
        return direct_rate

    sales_amount = float(raw_snapshot.get("sales_amount", 0) or 0)
    gross_profit = float(raw_snapshot.get("gross_profit", 0) or 0)
    if sales_amount > 0 and gross_profit > 0:
        return safe_ratio(gross_profit, sales_amount)

    return 0.0


def resolve_effective_expense_values(
    raw_snapshot: dict | None,
) -> tuple[float, float, float, list[dict], list[dict], str]:
    if not raw_snapshot:
        return 0.0, 0.0, 0.0, [], [], "缺少成本快照"

    expense_snapshot = raw_snapshot.get("expense_snapshot", {})
    expense_items = raw_snapshot.get("expense_items", [])
    salary_items = raw_snapshot.get("salary_items", [])

    monthly_operating_expense = float(
        expense_snapshot.get(
            "monthly_operating_expense",
            sum(float(item.get("amount", 0) or 0) for item in expense_items),
        )
        or 0
    )
    salary_total = float(
        expense_snapshot.get(
            "salary_total",
            sum(float(item.get("amount", 0) or 0) for item in salary_items),
        )
        or 0
    )

    operating_expense_source = "当前成本快照"
    if monthly_operating_expense <= 0:
        monthly_operating_expense = DEFAULT_MONTHLY_OPERATING_EXPENSE
        operating_expense_source = "默认固定成本（2w）"

    total_expense_raw = float(expense_snapshot.get("total_expense", 0) or 0)
    total_expense = total_expense_raw if total_expense_raw > 0 else monthly_operating_expense + salary_total
    if total_expense <= salary_total and monthly_operating_expense > 0:
        total_expense = monthly_operating_expense + salary_total

    return (
        monthly_operating_expense,
        salary_total,
        total_expense,
        expense_items,
        salary_items,
        operating_expense_source,
    )


def resolve_effective_margin_rate(raw_snapshot: dict | None, raw_history: list[dict] | None) -> tuple[float, str]:
    current_rate = extract_snapshot_margin_rate(raw_snapshot)
    if current_rate > 0:
        return current_rate, "当前成本快照"

    for history_snapshot in reversed(list(raw_history or [])):
        history_rate = extract_snapshot_margin_rate(history_snapshot)
        if history_rate > 0:
            snapshot_at = pd.to_datetime(history_snapshot.get("snapshot_datetime"), errors="coerce")
            if pd.notna(snapshot_at):
                return history_rate, f"历史成本快照（{snapshot_at.strftime('%Y-%m')}）"
            return history_rate, "历史成本快照"

    return 0.48, "默认毛利率（48%）"


def resolve_live_month_sales_amount(
    now: datetime,
    summary_cards: dict[str, object],
    yeusoft_highlights: dict | None,
    raw_snapshot: dict | None,
) -> tuple[float, str]:
    target_label = now.strftime("%Y-%m")
    sales_overview = (yeusoft_highlights or {}).get("sales_overview") if yeusoft_highlights else None
    latest_month = sales_overview.get("latest_month") if sales_overview else None
    if latest_month and str(latest_month.get("label")) == target_label:
        sales_amount = float(latest_month.get("sales_amount", 0) or 0)
        if sales_amount > 0:
            return sales_amount, "POS销售清单（月累计）"

    month_to_date_sales_amount = float(summary_cards.get("month_to_date_sales_amount", 0) or 0)
    if month_to_date_sales_amount > 0:
        return month_to_date_sales_amount, str(summary_cards.get("month_to_date_sales_source") or "校准销售月累计")

    sales_detail_end = summary_cards.get("sales_detail_end")
    if isinstance(sales_detail_end, pd.Timestamp) and sales_detail_end.strftime("%Y-%m") == target_label:
        sales_amount = float(summary_cards.get("sales_amount", 0) or 0)
        if sales_amount > 0:
            return sales_amount, "本地销售明细"

    snapshot_sales = float((raw_snapshot or {}).get("sales_amount", 0) or 0)
    if snapshot_sales > 0:
        return snapshot_sales, "成本快照"

    return 0.0, "缺少实时销售额"


def build_live_profit_snapshot(
    raw_snapshot: dict | None,
    raw_history: list[dict] | None,
    now: datetime,
    summary_cards: dict[str, object],
    yeusoft_highlights: dict | None,
) -> dict | None:
    if not raw_snapshot:
        return None

    snapshot_input = json.loads(json.dumps(raw_snapshot))
    margin_rate, margin_source = resolve_effective_margin_rate(raw_snapshot, raw_history)
    live_sales_amount, sales_source = resolve_live_month_sales_amount(now, summary_cards, yeusoft_highlights, raw_snapshot)

    if live_sales_amount > 0:
        snapshot_input["sales_amount"] = live_sales_amount

    if margin_rate > 0:
        effective_gross_profit = live_sales_amount * margin_rate if live_sales_amount > 0 else float(
            raw_snapshot.get("gross_profit", 0) or 0
        )
        effective_purchase_cost = max((live_sales_amount or 0) - effective_gross_profit, 0.0)
        snapshot_input["gross_margin_rate"] = margin_rate
        snapshot_input["gross_profit"] = effective_gross_profit
        snapshot_input["purchase_cost"] = effective_purchase_cost
        expense_snapshot = snapshot_input.setdefault("expense_snapshot", {})
        monthly_operating_expense, salary_total, total_expense, _, _, _ = resolve_effective_expense_values(snapshot_input)
        expense_snapshot["monthly_operating_expense"] = monthly_operating_expense
        expense_snapshot["salary_total"] = salary_total
        expense_snapshot["total_expense"] = total_expense
        snapshot_input["net_profit"] = effective_gross_profit - total_expense

    profit = build_profit_snapshot(snapshot_input)
    if not profit:
        return None

    profit["sales_source"] = sales_source
    profit["gross_margin_source"] = margin_source
    profit["forecast_basis"] = "当前已实现销售 + 平均日销 x 剩余天数，再按毛利率和总费用折算"
    if margin_rate <= 0:
        profit["forecast_headline"] = "缺少有效毛利率，当前净利预测偏保守"
        profit["projected_monthly_status"] = "yellow"

    return profit


def build_profit_history(raw_history: list[dict] | None, current_snapshot: dict | None) -> dict | None:
    snapshots = list(raw_history or [])
    if current_snapshot:
        snapshots.append(current_snapshot)

    normalized: dict[str, dict] = {}
    for raw_snapshot in snapshots:
        profit = build_profit_snapshot(raw_snapshot)
        if not profit:
            continue
        period_key = profit["snapshot_datetime"].strftime("%Y-%m")
        previous = normalized.get(period_key)
        if not previous or profit["snapshot_datetime"] >= previous["snapshot_datetime"]:
            normalized[period_key] = profit

    entries = sorted(normalized.values(), key=lambda item: item["snapshot_datetime"])
    if not entries:
        return None

    rows: list[dict[str, object]] = []
    for entry in entries:
        rows.append(
            {
                "月份": entry["snapshot_datetime"].strftime("%Y-%m"),
                "快照名称": entry["snapshot_name"],
                "销售额": entry["sales_amount"],
                "毛利额": entry["gross_profit"],
                "固定费用": entry["monthly_operating_expense"],
                "人工费用": entry["salary_total"],
                "总费用": entry["total_expense"],
                "净利润": entry["net_profit"],
                "毛利率": entry["gross_margin_rate"],
                "保本销售额": entry["breakeven_sales"],
                "保本进度": entry["breakeven_progress_ratio"],
                "快照时间": entry["snapshot_datetime"],
            }
        )

    latest = entries[-1]
    previous = entries[-2] if len(entries) >= 2 else None
    delta_net_profit = latest["net_profit"] - previous["net_profit"] if previous else 0.0
    delta_sales = latest["sales_amount"] - previous["sales_amount"] if previous else 0.0
    delta_total_expense = latest["total_expense"] - previous["total_expense"] if previous else 0.0
    delta_breakeven_progress = (
        latest["breakeven_progress_ratio"] - previous["breakeven_progress_ratio"] if previous else 0.0
    )

    if previous:
        if delta_net_profit >= 0 and delta_total_expense <= 0:
            headline = "利润改善"
            status = "green"
            note = "较上月净利润提升，同时总费用没有继续抬高。"
        elif delta_net_profit >= 0:
            headline = "利润回升"
            status = "yellow"
            note = "净利润较上月回升，但仍要继续盯住费用变化。"
        else:
            headline = "利润回落"
            status = "red"
            note = "较上月净利润回落，优先看销售、毛利和费用哪一段变差。"
    else:
        headline = "开始累计"
        status = "neutral"
        note = "当前只有 1 个月成本快照，先从本月开始连续记录。"

    return {
        "entries": entries,
        "rows": rows,
        "latest": latest,
        "previous": previous,
        "delta_net_profit": delta_net_profit,
        "delta_sales": delta_sales,
        "delta_total_expense": delta_total_expense,
        "delta_breakeven_progress": delta_breakeven_progress,
        "headline": headline,
        "status": status,
        "note": note,
    }


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


def build_metrics(
    data: dict[str, pd.DataFrame],
    store_name: str,
    cost_snapshot: dict | None = None,
    cost_history_raw: list[dict] | None = None,
    yeusoft_capture_bundle: dict[str, dict] | None = None,
    analysis_db_file: Path | None = None,
    analysis_snapshot: dict | None = None,
) -> dict:
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
    analysis_snapshot = analysis_snapshot or load_analysis_db_snapshot(analysis_db_file, store_name)
    quality_checks = (
        analysis_snapshot.get("quality_checks", pd.DataFrame()).copy()
        if analysis_snapshot
        else pd.DataFrame()
    )
    analysis_window_meta: dict[str, object] = {}
    if analysis_snapshot:
        analysis_sales, analysis_window_meta = build_sales_window_from_analysis(
            analysis_snapshot,
            window_days=DEFAULT_ANALYSIS_WINDOW_DAYS,
        )
        if not analysis_sales.empty:
            sales = analysis_sales
    profit_history = build_profit_history(cost_history_raw, cost_snapshot)
    yeusoft_highlights = build_yeusoft_report_highlights(
        yeusoft_capture_bundle or {}, current_season_key, next_season_key
    )
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
        "sales_source_label": "本地销售清单样本",
        "cumulative_sales_source_label": "Excel 商品销售情况",
        "month_to_date_sales_amount": 0.0,
        "month_to_date_sales_source": "本地销售清单样本",
    }

    if analysis_snapshot:
        product_snapshot = analysis_snapshot.get("product_snapshot", pd.DataFrame()).copy()
        if not product_snapshot.empty:
            product_snapshot_no_props = product_snapshot[~product_snapshot["is_prop"]].copy()
            product_snapshot_props = product_snapshot[product_snapshot["is_prop"]].copy()
            summary_cards.update(
                {
                    "cumulative_sales_qty": float(product_snapshot_no_props["cumulative_sales_qty"].sum()),
                    "cumulative_sales_amount": float(product_snapshot_no_props["cumulative_sales_amount"].sum()),
                    "cumulative_receipt_qty": float(product_snapshot_no_props["arrival_qty"].sum()),
                    "historical_stock_qty": float(product_snapshot_no_props["current_stock_qty"].sum()),
                    "history_first_arrival": product_snapshot_no_props["first_arrival_date"].min(),
                    "history_first_sale": product_snapshot_no_props["first_sale_date"].min(),
                    "props_cumulative_sales_qty": float(product_snapshot_props["cumulative_sales_qty"].sum()),
                    "props_cumulative_sales_amount": float(product_snapshot_props["cumulative_sales_amount"].sum()),
                    "cumulative_sales_source_label": "SQLite 校准累计快照",
                }
            )
        if analysis_window_meta:
            summary_cards.update(
                {
                    "sales_source_label": f"SQLite 校准销售主表（最近 {int(analysis_window_meta.get('effective_window_days', sales_days or 0))} 天滚动窗口）",
                    "month_to_date_sales_amount": float(analysis_window_meta.get("month_to_date_sales_amount", 0) or 0),
                    "month_to_date_sales_source": "SQLite 校准销售月累计",
                    "analysis_batch_id": analysis_snapshot.get("batch_id"),
                }
            )

    capture_candidates = [
        summary_cards["sales_detail_end"],
        movement["发货时间"].max() if not movement.empty else pd.NaT,
        store_retail["销售日期"].max() if not store_retail.empty and "销售日期" in store_retail.columns else pd.NaT,
    ]
    if analysis_snapshot and pd.notna(analysis_snapshot.get("batch_created_at")):
        capture_candidates.append(analysis_snapshot["batch_created_at"])
    if yeusoft_highlights and pd.notna(yeusoft_highlights.get("capture_at")):
        capture_candidates.append(yeusoft_highlights["capture_at"])
    valid_capture_dates = [normalize_compare_timestamp(item) for item in capture_candidates if pd.notna(item)]
    summary_cards["data_capture_at"] = max(valid_capture_dates) if valid_capture_dates else pd.Timestamp(now.date())
    profit_snapshot = build_live_profit_snapshot(
        cost_snapshot,
        cost_history_raw,
        now,
        summary_cards,
        yeusoft_highlights,
    )
    summary_cards["profit_snapshot"] = profit_snapshot
    summary_cards["yeusoft_highlights"] = yeusoft_highlights

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

    primary_input = PRIMARY_INPUT
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
    retail_detail = (yeusoft_highlights or {}).get("retail_detail") if yeusoft_highlights else {}
    discount_dependent_categories = {
        str(item.get("name", "")).strip()
        for item in (retail_detail or {}).get("top_discount_categories", [])
        if str(item.get("name", "")).strip()
    }
    core_size_names = (retail_detail or {}).get("core_size_names", "主销尺码")

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
    replenish[["补货原则", "主销尺码", "进货提醒", "控折扣原则", "预算建议", "进货顺序"]] = replenish.apply(
        lambda row: pd.Series(
            classify_replenish_rule(
                row,
                discount_dependent_categories,
                core_size_names,
            )
        ),
        axis=1,
    )
    replenish.loc[replenish["库存"] < 0, "建议动作"] = "先校库存再补货"
    replenish.loc[replenish["库存"] < 0, "补货原则"] = "先校库存"
    replenish.loc[replenish["库存"] < 0, "进货提醒"] = "库存口径异常，先别下单"
    replenish.loc[replenish["库存"] < 0, "控折扣原则"] = "先校库存，先别谈活动和折扣"
    replenish.loc[replenish["库存"] < 0, "预算建议"] = "库存异常款先不下单，预算留给正常主销款"
    replenish.loc[replenish["库存"] < 0, "进货顺序"] = "先查账、查盘点、查调拨，确认后再补"
    replenish = replenish.sort_values(
        ["销售金额", "库存周数", "库存"], ascending=[False, True, True]
    )
    replenish_categories = (
        replenish.groupby(["中类", "季节策略"])
        .agg(
            SKU数=("款号", "count"),
            销售额=("销售金额", "sum"),
            库存=("库存", "sum"),
            建议补货量=("建议补货量", "sum"),
            补货原则=("补货原则", lambda values: "、".join(dedupe_preserve_order([str(v) for v in values if str(v).strip()])[:2])),
            主销尺码=("主销尺码", lambda values: "、".join(dedupe_preserve_order([str(v) for v in values if str(v).strip()])[:1])),
            控折扣原则=("控折扣原则", lambda values: "、".join(dedupe_preserve_order([str(v) for v in values if str(v).strip()])[:1])),
            预算建议=("预算建议", lambda values: "、".join(dedupe_preserve_order([str(v) for v in values if str(v).strip()])[:1])),
        )
        .reset_index()
        .sort_values(["销售额", "建议补货量", "SKU数"], ascending=[False, False, False])
        if not replenish.empty
        else pd.DataFrame(columns=["中类", "季节策略", "SKU数", "销售额", "库存", "建议补货量", "补货原则", "主销尺码", "控折扣原则", "预算建议"])
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
    seasonal_categories = (
        seasonal_actions.groupby(["中类", "季节策略", "建议动作"])
        .agg(
            SKU数=("款号", "count"),
            销售额=("销售金额", "sum"),
            库存=("库存", "sum"),
        )
        .reset_index()
        .sort_values(["库存", "销售额", "SKU数"], ascending=[False, False, False])
        if not seasonal_actions.empty
        else pd.DataFrame(columns=["中类", "季节策略", "建议动作", "SKU数", "销售额", "库存"])
    )

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
    clearance_categories = (
        clearance.groupby(["大类", "建议动作"])
        .agg(
            SKU数=("商品款号", "count"),
            实际库存=("实际库存", "sum"),
            近期零售=("近期零售", "sum"),
        )
        .reset_index()
        .sort_values(["实际库存", "SKU数"], ascending=[False, False])
        if not clearance.empty
        else pd.DataFrame(columns=["大类", "建议动作", "SKU数", "实际库存", "近期零售"])
    )

    action_summary = {
        "replenish_count": int(len(replenish)),
        "seasonal_hold_count": int(len(seasonal_actions)),
        "clearance_count": int(len(clearance)),
        "high_risk_category_count": int((category_risks["状态"] == "高压货").sum()),
    }

    insights = [
        insight_item(
            f"近 {summary_cards['sales_days']} 天经营销售额 {format_num(summary_cards['sales_amount'], 2)} 元，客单价 {format_num(summary_cards['avg_order_value'], 2)} 元。",
        ),
        insight_item(
            f"日销趋势当前只覆盖最近 {summary_cards['sales_days']} 天。",
            f"当前趋势来自 {summary_cards.get('sales_source_label', '销售清单')}，时间范围是 {summary_cards['sales_detail_start'].strftime('%Y-%m-%d')} 到 "
            f"{summary_cards['sales_detail_end'].strftime('%Y-%m-%d')}。",
            "时间范围",
        ),
        insight_item(
            f"历史累计销售额约 {format_num(summary_cards['cumulative_sales_amount'], 2)} 元。",
            f"这个口径来自 {summary_cards.get('cumulative_sales_source_label', '商品销售情况')}，自 {summary_cards['history_first_sale'].strftime('%Y-%m-%d')} 以来累计计算。",
            "口径",
        ),
        insight_item(
            f"库存覆盖天数约 {format_num(summary_cards['estimated_inventory_days'], 1)} 天。",
            f"当前账面库存 {format_num(summary_cards['inventory_qty'])} 件，零售价口径库存额约 {format_num(summary_cards['inventory_amount'], 2)} 元。",
            "库存说明",
        ),
        insight_item(
            f"会员销售额占比约 {format_num(summary_cards['member_sales_ratio'] * 100, 1)}%。",
            "会员经营已经是核心收入来源，适合继续做回访和复购。",
            "看法",
        ),
        insight_item(
            f"负库存 SKU {summary_cards['negative_sku_count']} 个，需要优先纠偏。",
            f"负库存金额合计 {format_num(summary_cards['negative_inventory_amount'], 2)} 元；不先纠偏会影响补货和动销判断。",
            "原因",
        ),
        insight_item(
            "道具已从主经营口径剥离，只保留参考值。",
            f"当前道具销售额约 {format_num(summary_cards['props_sales_amount'], 2)} 元，道具库存额约 {format_num(summary_cards['props_inventory_amount'], 2)} 元。",
            "参考值",
        ),
        insight_item(
            f"补货/跨季/去化待处理 SKU：{action_summary['replenish_count']} / {action_summary['seasonal_hold_count']} / {action_summary['clearance_count']}。",
            "建议优先补货的 SKU、跨季不建议补货的 SKU 和建议先去化的 SKU 已分别筛出，可继续下钻到补货去化区查看。",
            "说明",
        ),
    ]
    if yeusoft_highlights:
        sales_overview = yeusoft_highlights.get("sales_overview")
        product_sales_highlight = yeusoft_highlights.get("product_sales")
        member_rank_highlight = yeusoft_highlights.get("member_rank")
        stock_analysis = yeusoft_highlights.get("stock_analysis")
        movement_highlight = yeusoft_highlights.get("movement")
        daily_flow = yeusoft_highlights.get("daily_flow")
        if sales_overview:
            latest_month = sales_overview.get("latest_month")
            if latest_month:
                insights.append(
                    insight_item(
                        f"最近月份 {latest_month['label']} 销售额约 {format_num(latest_month['sales_amount'], 2)} 元。",
                        f"数据来自 POS 销售清单全量；当前主销中类是 {latest_month['top_category']}。",
                        "主销",
                    )
                )
        if product_sales_highlight:
            insights.append(
                insight_item(
                    f"累计售罄率约 {format_num(product_sales_highlight['sellout_rate'] * 100, 1)}%。",
                    f"当前库存主要压在 {product_sales_highlight['top_stock_labels']}。",
                    "库存结构",
                )
            )
        if member_rank_highlight:
            insights.append(
                insight_item(
                    f"前 10 位会员贡献约 {format_num(member_rank_highlight['top10_share'] * 100, 1)}% 销额。",
                    f"高价值会员主要是 {member_rank_highlight['top_names']}。",
                    "会员名单",
                )
            )
        if stock_analysis:
            top_labels = stock_analysis["top_labels"]
            cross_share = stock_analysis["cross_season_inventory_share"] * 100
            current_share = stock_analysis["current_season_inventory_share"] * 100
            insights.append(
                insight_item(
                    f"库存金额主要压在 {top_labels}。",
                    f"其中当季库存约占 {format_num(current_share, 1)}%，跨季库存约占 {format_num(cross_share, 1)}%。",
                    "季节结构",
                )
            )
        if movement_highlight:
            window_start = movement_highlight["window_start"]
            window_end = movement_highlight["window_end"]
            window_label = (
                f"{window_start.strftime('%Y-%m-%d')} 到 {window_end.strftime('%Y-%m-%d')}"
                if pd.notna(window_start) and pd.notna(window_end)
                else "最近一段时间"
            )
            insights.append(
                insight_item(
                    f"{window_label} 内净入库 {format_num(movement_highlight['net_qty'])} 件。",
                    f"入库 {format_num(movement_highlight['inbound_qty'])} 件 / {format_num(movement_highlight['inbound_amount'], 2)} 元；"
                    f"出库 {format_num(movement_highlight['outbound_qty'])} 件 / {format_num(movement_highlight['outbound_amount'], 2)} 元。",
                    "出入库",
                )
            )
        if daily_flow:
            dominant_payment = daily_flow.get("dominant_payment")
            payment_text = (
                f"{dominant_payment['label']}占比 {format_num(dominant_payment['share'] * 100, 1)}%"
                if dominant_payment
                else "暂无明显支付方式集中"
            )
            insights.append(
                insight_item(
                    f"当日流水 {format_num(daily_flow['actual_money'], 2)} 元。",
                    f"{format_num(daily_flow['order_count'])} 单 / {format_num(daily_flow['sales_qty'])} 件，{payment_text}。",
                    "当日结构",
                )
            )
    if profit_snapshot:
        insights.append(
            insight_item(
                f"当前毛利约 {format_num(profit_snapshot['gross_profit'], 2)} 元，净利润约 {format_num(profit_snapshot['net_profit'], 2)} 元。",
                f"销售口径来自 {profit_snapshot.get('sales_source', '当前数据')}；"
                f"毛利率口径来自 {profit_snapshot.get('gross_margin_source', '当前数据')}；"
                f"总费用约 {format_num(profit_snapshot['total_expense'], 2)} 元。",
                "利润口径",
            )
        )
        if profit_snapshot.get("breakeven_available"):
            insights.append(
                insight_item(
                    f"保本销售额约 {format_num(profit_snapshot['breakeven_sales'], 2)} 元。",
                    f"平均每天至少要卖 {format_num(profit_snapshot['breakeven_daily_sales'], 2)} 元。",
                    "保本日销",
                )
            )
            insights.append(
                insight_item(
                    f"当前保本进度约 {format_num(profit_snapshot['breakeven_progress_ratio'] * 100, 1)}%。",
                    f"固定费用约 {format_num(profit_snapshot['monthly_operating_expense'], 2)} 元；"
                    f"人工费用约 {format_num(profit_snapshot['salary_total'], 2)} 元。",
                    "费用结构",
                )
            )
        else:
            insights.append(
                insight_item(
                    "当前保本线按保守口径展示。",
                    f"固定费用约 {format_num(profit_snapshot['monthly_operating_expense'], 2)} 元；"
                    f"人工费用约 {format_num(profit_snapshot['salary_total'], 2)} 元；"
                    "当前缺少有效毛利率。",
                    "原因",
                )
            )
        insights.append(
            insight_item(
                f"月末销售约 {format_num(profit_snapshot['projected_month_sales'], 2)} 元，净利约 {format_num(profit_snapshot['projected_month_net_profit'], 2)} 元。",
                f"当前月已实现销售 {format_num(profit_snapshot['sales_amount'], 2)} 元；"
                f"剩余 {format_num(profit_snapshot['remaining_days'], 1)} 天预计新增销售 {format_num(profit_snapshot['projected_remaining_sales'], 2)} 元。",
                "预测拆解",
            )
        )
    if profit_history:
        if profit_history["previous"]:
            insights.append(
                insight_item(
                    f"较上月净利润变化 {format_num(profit_history['delta_net_profit'], 2)} 元。",
                    f"总费用变化 {format_num(profit_history['delta_total_expense'], 2)} 元。",
                    "对比",
                )
            )
        else:
            insights.append(
                insight_item(
                    "成本历史已开始累计。",
                    "当前只有 1 个月快照，建议从下个月开始连续对比利润和费用。",
                    "说明",
                )
            )
    if not primary_reference.empty:
        row = primary_reference.iloc[0]
        insights.append(
            insight_item(
                f"主逻辑当前只关注 {primary_input} / {row['店铺名称']}。",
                "店铺零售清单已按输入人区分参考店铺，其余输入人仅作为参考对比。",
                "口径",
            )
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
        "replenish_categories": replenish_categories,
        "seasonal_actions": seasonal_actions,
        "seasonal_categories": seasonal_categories,
        "clearance": clearance,
        "clearance_categories": clearance_categories,
        "action_summary": action_summary,
        "insights": insights,
        "yeusoft_highlights": yeusoft_highlights,
        "profit_history": profit_history,
        "quality_checks": quality_checks,
    }

def decorate_table(df: pd.DataFrame) -> pd.DataFrame:
    decorated = df.copy()
    if "季节策略" in decorated.columns:
        decorated["季节策略"] = decorated["季节策略"].map(
            {
                "当季主推": format_badge("当季主推", "green", SEASON_STRATEGY_TOOLTIPS["当季主推"]),
                "下一季试补": format_badge("下一季试补", "yellow", SEASON_STRATEGY_TOOLTIPS["下一季试补"]),
                "跨季去化": format_badge("跨季去化", "red", SEASON_STRATEGY_TOOLTIPS["跨季去化"]),
                "暂缓补货": format_badge("暂缓补货", "yellow", SEASON_STRATEGY_TOOLTIPS["暂缓补货"]),
            }
        ).fillna(decorated["季节策略"])
    if "状态" in decorated.columns:
        decorated["状态"] = decorated["状态"].map(
            {
                "高压货": format_badge("高压货", "red", STATUS_TOOLTIPS["高压货"]),
                "需关注": format_badge("需关注", "yellow", STATUS_TOOLTIPS["需关注"]),
                "相对健康": format_badge("相对健康", "green", STATUS_TOOLTIPS["相对健康"]),
            }
        ).fillna(decorated["状态"])
    if "建议动作" in decorated.columns:
        decorated["建议动作"] = decorated["建议动作"].astype(str).map(
            {
                "立即补货": format_badge("立即补货", "red", ACTION_TOOLTIPS["立即补货"]),
                "优先补货": format_badge("优先补货", "yellow", ACTION_TOOLTIPS["优先补货"]),
                "先校库存再补货": format_badge("先校库存再补货", "red", ACTION_TOOLTIPS["先校库存再补货"]),
                "小量试补": format_badge("小量试补", "yellow", ACTION_TOOLTIPS["小量试补"]),
                "先停补再去化": format_badge("先停补再去化", "red", ACTION_TOOLTIPS["先停补再去化"]),
                "观察并做组合去化": format_badge("观察并做组合去化", "yellow", ACTION_TOOLTIPS["观察并做组合去化"]),
                "优先去化": format_badge("优先去化", "red", ACTION_TOOLTIPS["优先去化"]),
                "跨季不补货": format_badge("跨季不补货", "red", ACTION_TOOLTIPS["跨季不补货"]),
                "暂缓补货": format_badge("暂缓补货", "yellow", ACTION_TOOLTIPS["暂缓补货"]),
            }
        ).fillna(decorated["建议动作"])
    return decorated


def build_dashboard_tips(cards: dict, actions: dict) -> list[dict[str, str]]:
    tips = [
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
    profit = cards.get("profit_snapshot")
    if profit:
        tips.extend(
            [
                {
                    "term": "毛利额",
                    "meaning": "销售额减去进货成本后的余额，还没扣房租、工资、电费这些经营费用。",
                    "watch": "毛利高不代表真正赚钱，还要继续看总费用和净利润。",
                },
                {
                    "term": "净利润",
                    "meaning": "毛利扣掉房租、工资、电费和其他月费用之后，真正剩下的钱。",
                    "watch": "净利润为负时，重点不是继续压货，而是先提高毛利和控制费用。",
                },
                {
                    "term": "保本销售额",
                    "meaning": "按当前毛利率估算，本月至少卖到这个数，才够覆盖总费用。",
                    "watch": "如果当前销售额还没过保本线，就先保主销、提客单、控库存。",
                },
            ]
        )
    return tips


def top_label_from_series(series: pd.Series, fallback: str) -> str:
    clean = series.dropna()
    if clean.empty:
        return fallback
    return str(clean.iloc[0])


def top_labels_from_series(series: pd.Series, fallback: str, limit: int = 2) -> str:
    clean = [str(item).strip() for item in series.dropna().tolist() if str(item).strip()]
    unique_labels = list(dict.fromkeys(clean))
    if not unique_labels:
        return fallback
    return "、".join(unique_labels[:limit])


def trim_text(text: str, max_chars: int = 12) -> str:
    value = str(text).strip()
    if len(value) <= max_chars:
        return value
    return value[:max_chars]


def dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def strip_sentence_tail(text: str) -> str:
    return str(text).strip().rstrip("。.!！?？")


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


def classify_sales_trend(sales_daily: pd.DataFrame) -> dict[str, object]:
    if sales_daily.empty:
        return {
            "label": "数据不足",
            "direction": "flat",
            "recent_avg": 0.0,
            "previous_avg": 0.0,
            "ratio": 1.0,
            "detail": "暂无足够的日销数据做趋势判断。",
        }

    ordered = sales_daily.sort_values("日期").copy()
    window = 3 if len(ordered) >= 6 else max(1, len(ordered) // 2)
    recent = ordered.tail(window)
    previous = ordered.iloc[-(window * 2):-window] if len(ordered) >= window * 2 else ordered.head(window)

    recent_avg = float(recent["销售额"].mean()) if not recent.empty else 0.0
    previous_avg = float(previous["销售额"].mean()) if not previous.empty else recent_avg
    ratio = safe_ratio(recent_avg, previous_avg) if previous_avg else 1.0

    if previous_avg == 0 and recent_avg > 0:
        label = "上涨"
        direction = "up"
    elif ratio >= 1.15:
        label = "上涨"
        direction = "up"
    elif ratio <= 0.85:
        label = "下滑"
        direction = "down"
    else:
        label = "走平"
        direction = "flat"

    return {
        "label": label,
        "direction": direction,
        "recent_avg": recent_avg,
        "previous_avg": previous_avg,
        "ratio": ratio,
        "detail": f"最近 {len(recent)} 天日销均值 {format_num(recent_avg, 2)} 元，对比前段为 {label}。",
    }


def classify_business_stage(phase: str) -> str:
    if "主销" in phase or "起量" in phase:
        return "旺季冲量"
    if "换季" in phase or "预热" in phase or "上新" in phase:
        return "换季切换"
    return "平稳经营"


def build_decision_engine(metrics: dict) -> dict[str, object]:
    cards = metrics["summary_cards"]
    actions = metrics["action_summary"]
    time_strategy = build_time_strategy(metrics)
    sales_trend = classify_sales_trend(metrics["sales_daily"])
    stage = classify_business_stage(time_strategy["phase"])
    profit = cards.get("profit_snapshot")
    signals = build_homepage_operating_signals(metrics)

    top_replenish = top_labels_from_series(metrics["replenish_categories"]["中类"], time_strategy["top_replenish_category"], 2)
    top_clearance = top_labels_from_series(metrics["clearance_categories"]["大类"], time_strategy["top_clearance_category"], 2)
    top_seasonal = top_labels_from_series(metrics["seasonal_categories"]["中类"], "跨季品类", 2)

    if profit and profit["projected_month_net_profit"] < 0 and signals["markdown_pressure_high"]:
        mode = "稳毛利优先"
        headline = "先稳毛利，别靠打折硬撑。"
        summary = (
            f"{time_strategy['phase']}阶段，最近日销{sales_trend['label']}，"
            f"但按当前节奏月末净利约 {format_num(profit['projected_month_net_profit'], 2)} 元。"
            f" 当前实销折扣约 {format_num(signals['weighted_discount_rate'] * 10, 1)} 折，"
            f"{signals['discount_category_names']} 这些中类折扣依赖偏重。先稳毛利、提组合，再谈放大量。"
        )
    elif profit and profit["projected_month_net_profit"] < 0 and signals["low_joint"]:
        mode = "提连带保利润"
        headline = "先提连带和客单，别只冲单数。"
        summary = (
            f"{time_strategy['phase']}阶段，最近日销{sales_trend['label']}，"
            f"但按当前节奏月末净利约 {format_num(profit['projected_month_net_profit'], 2)} 元。"
            f" 最近件单比只有 {format_num(signals['latest_joint_rate'], 2)}，先把 {top_replenish} 做成组合成交，再谈放大量。"
        )
    elif profit and profit["projected_month_net_profit"] < 0 and not profit["passed_breakeven"]:
        mode = "稳利润优先"
        headline = "先稳利润和保本，再谈放大营业额。"
        summary = (
            f"{time_strategy['phase']}阶段，最近日销{sales_trend['label']}，"
            f"当前还差 {format_num(profit['remaining_sales_to_breakeven'], 2)} 元过保本。"
            f" 先保 {top_replenish} 的高毛利主销，先压 {top_clearance} 的库存，不适合做深折扣。"
        )
    elif cards["negative_sku_count"] >= 50:
        mode = "校库存优先"
        headline = "先校库存，再决定补货和去化。"
        summary = (
            f"{time_strategy['phase']}阶段，最近日销{sales_trend['label']}，但当前有 {format_num(cards['negative_sku_count'])} 个负库存 SKU。"
            "先把账实校准，不然所有经营动作都会跑偏。"
        )
    elif cards["estimated_inventory_days"] >= 180 and sales_trend["direction"] != "up":
        mode = "去库存优先"
        headline = "库存偏重，当前先去库存。"
        summary = (
            f"{time_strategy['phase']}阶段，最近日销{sales_trend['label']}，库存还能卖约 {format_num(cards['estimated_inventory_days'], 1)} 天。"
            f"先处理 {top_clearance} 这些高库存品类，别继续深补。"
        )
    elif stage == "换季切换" and actions["seasonal_hold_count"] >= 1:
        mode = "换季切换"
        headline = "换季先切结构，不要补错季。"
        summary = (
            f"现在处于 {time_strategy['phase']}，重点是让 {top_replenish} 起量，同时把 {top_seasonal} 这些跨季品类单独处理。"
        )
    elif actions["replenish_count"] >= 100 and sales_trend["direction"] in {"up", "flat"}:
        mode = "保畅销优先"
        headline = "主销品类要快补，但只补当季。"
        summary = (
            f"{time_strategy['phase']}阶段，最近日销{sales_trend['label']}，当前建议补货 SKU {format_num(actions['replenish_count'])} 个。"
            f"优先保住 {top_replenish} 的主销不断货。"
        )
    else:
        mode = "稳经营"
        headline = "按季节稳经营，边卖边调结构。"
        summary = (
            f"当前处于 {time_strategy['phase']}，最近日销{sales_trend['label']}。"
            f"补货先看 {top_replenish}，去化先看 {top_clearance}，按周复盘即可。"
        )

    if profit and profit["projected_month_net_profit"] >= 0 and profit["passed_breakeven"]:
        summary += " 当前利润口径已经过保本线，可以在不伤毛利的前提下放大主销营业额。"

    return {
        "mode": mode,
        "stage": stage,
        "headline": headline,
        "summary": summary,
        "sales_trend": sales_trend,
        "season": time_strategy["season"],
        "phase": time_strategy["phase"],
        "top_replenish": top_replenish,
        "top_clearance": top_clearance,
        "top_seasonal": top_seasonal,
    }


def build_homepage_operating_signals(metrics: dict) -> dict[str, object]:
    pos_highlights = metrics.get("yeusoft_highlights") or {}
    category_analysis = pos_highlights.get("category_analysis") or {}
    vip_analysis = pos_highlights.get("vip_analysis") or {}
    guide_report = pos_highlights.get("guide_report") or {}
    store_month_report = pos_highlights.get("store_month_report") or {}
    retail_detail = pos_highlights.get("retail_detail") or {}

    latest_month = store_month_report.get("latest_month") if store_month_report else None
    top2_share = float(category_analysis.get("top2_share", 0) or 0)
    dormant_ratio = float(vip_analysis.get("dormant_ratio", 0) or 0)
    top_guide_share = float(guide_report.get("top_guide_share", 0) or 0)
    latest_joint_rate = float((latest_month or {}).get("joint_rate", 0) or 0)
    weighted_discount_rate = float(retail_detail.get("weighted_discount_rate", 0) or 0)
    deep_discount_sales_share = float(retail_detail.get("deep_discount_sales_share", 0) or 0)

    growth_rows = category_analysis.get("growth_rows") or []
    growth_names = "、".join(item["name"] for item in growth_rows[:2]) if growth_rows else category_analysis.get(
        "top_category_names", "主销品类"
    )

    return {
        "category_analysis": category_analysis,
        "vip_analysis": vip_analysis,
        "guide_report": guide_report,
        "store_month_report": store_month_report,
        "retail_detail": retail_detail,
        "latest_month": latest_month,
        "category_concentrated": top2_share >= 0.6,
        "top2_share": top2_share,
        "top_category_names": category_analysis.get("top_category_names", "主销品类"),
        "growth_names": growth_names,
        "vip_dormant_high": dormant_ratio >= 0.35,
        "dormant_ratio": dormant_ratio,
        "active_recent_count": int(vip_analysis.get("active_recent_count", 0) or 0),
        "top_member_names": vip_analysis.get("top_member_names", "高价值会员"),
        "guide_concentrated": top_guide_share >= 0.45,
        "top_guide_name": guide_report.get("top_guide_name", "主力店员"),
        "top_guide_share": top_guide_share,
        "vip_sales_share": float(guide_report.get("vip_sales_share", 0) or 0),
        "low_joint": bool(latest_month) and latest_joint_rate > 0 and latest_joint_rate < 1.2,
        "latest_joint_rate": latest_joint_rate,
        "low_joint_days": int(store_month_report.get("low_joint_days", 0) or 0),
        "latest_month_label": (latest_month or {}).get("label", "最近月份"),
        "markdown_pressure_high": bool(retail_detail.get("markdown_pressure_high")),
        "weighted_discount_rate": weighted_discount_rate,
        "deep_discount_sales_share": deep_discount_sales_share,
        "discount_category_names": retail_detail.get("discount_category_names", "高折扣依赖中类"),
        "core_size_names": retail_detail.get("core_size_names", "主销尺码"),
        "top_size_share": float(retail_detail.get("top_size_share", 0) or 0),
        "top_price_band": retail_detail.get("top_price_band", "主价格带"),
    }


def classify_replenish_rule(
    row: pd.Series,
    discount_dependent_categories: set[str],
    core_size_names: str,
) -> tuple[str, str, str, str, str, str]:
    category = str(row.get("中类", "") or "")
    season_strategy = str(row.get("季节策略", "") or "")
    stock_weeks = safe_float(row.get("库存周数"))
    sales_amount = safe_float(row.get("销售金额"))
    discount_sensitive = category in discount_dependent_categories

    if season_strategy == "下一季试补":
        return (
            "小量试补",
            core_size_names,
            "只补样板尺码，先看真实动销再放量",
            "只做轻活动，不额外加深折扣",
            "预算建议控制在常规补货的 30% 以内，先试单再决定是否扩量",
            "先补核心样板尺码，再补相邻尺码，边缘尺码先不进",
        )
    if discount_sensitive and stock_weeks <= 1:
        return (
            "先稳毛利再补",
            core_size_names,
            "先保高毛利主销，不靠深折补量",
            "先做组合和套装，不建议继续加深折扣",
            "预算先给主销核心款和核心尺码，不做平均补货",
            "先补核心尺码，再补主销色，最后才补边缘尺码",
        )
    if discount_sensitive:
        return (
            "控量补货",
            core_size_names,
            "折扣依赖偏重，补货先小单快返",
            "清货折扣只给尾货，主销款维持当前折扣，不再靠更低折扣冲量",
            "预算只留给快返和断码修复，原则上不做整类深补",
            "先补近两周有成交的尺码，再看是否补主销色",
        )
    if stock_weeks <= 1:
        return (
            "优先保不断码",
            core_size_names,
            "先保核心尺码和主销色",
            "可以做轻活动带连带，不建议先用降价换量",
            "预算优先投给断码风险高的款，再补相邻尺码",
            "先补核心尺码，再补主销色，最后补边缘尺码",
        )
    if sales_amount >= 10000:
        return (
            "按周销快返",
            core_size_names,
            "按近几周动销做小单多次补货",
            "维持现有折扣，优先用搭配销售放大营业额",
            "预算按销量排名分层，优先保前排款，不做平均铺货",
            "先补销量前排款，再补次主销款，边缘款暂缓",
        )
    return (
        "按周销快返",
        core_size_names,
        "按近几周动销做小单多次补货",
        "维持正常折扣，先做场景推荐和组合带量",
        "预算以小单快返为主，观察一周后再决定是否放量",
        "先补主销尺码，再补相邻尺码，边缘款继续观察",
    )


def build_operational_playbooks(metrics: dict) -> list[dict]:
    cards = metrics["summary_cards"]
    actions = metrics["action_summary"]
    time_strategy = build_time_strategy(metrics)
    profit = cards.get("profit_snapshot")
    category_risks = metrics["category_risks"]
    top_members = metrics["top_members"].head(3)
    seasonal_categories = metrics["seasonal_categories"].head(3)
    top_risk_category = top_label_from_series(category_risks["大类"], "高库存品类")
    top_member_names = "、".join(top_members["VIP姓名"].astype(str).tolist()) if not top_members.empty else "高价值会员"
    top_seasonal_categories = (
        top_labels_from_series(seasonal_categories["中类"], "跨季品类", 3)
        if not seasonal_categories.empty
        else "跨季品类"
    )

    playbooks: list[dict] = []

    if profit and not profit["passed_breakeven"]:
        playbooks.append(
            {
                "level": "red" if profit["status"] == "red" else "yellow",
                "title": "还没过保本线，先盯利润而不是只看销售",
                "trigger": (
                    f"当前净利润 {format_num(profit['net_profit'], 2)} 元，"
                    f"保本销售额约 {format_num(profit['breakeven_sales'], 2)} 元，"
                    f"还差 {format_num(profit['remaining_sales_to_breakeven'], 2)} 元。"
                ),
                "goal": "先让本月销售和毛利覆盖固定费用与工资，再决定促销和扩品动作。",
                "schemes": [
                    {
                        "name": "先保高毛利主销",
                        "detail": "今天优先卖动高毛利、当季主销和高连带组合，不用低价促销去换低质量营业额。",
                    },
                    {
                        "name": "盯保本日销",
                        "detail": (
                            f"本月平均每天至少要卖 {format_num(profit['breakeven_daily_sales'], 2)} 元；"
                            f"如果剩余天数不多，后面每天至少要卖 {format_num(profit['remaining_daily_sales_needed'], 2)} 元。"
                        ),
                    },
                    {
                        "name": "先控费用和压货",
                        "detail": "在没过保本线前，先收紧补货、减少非必要促销和低效率支出，把现金留给主销款。",
                    },
                ],
            }
        )

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
                        "detail": f"今天先定 {time_strategy['top_replenish_category']} 这个品类的补货预算，再下钻到销售金额高、库存 0-1、库存周数小于 1 的款。",
                    },
                    {
                        "name": "B类本周补",
                        "detail": "本周内处理同品类里销售稳定但库存还有 1-2 周的款，避免一下子把补货预算打满。",
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
                "trigger": f"当前有 {format_num(actions['seasonal_hold_count'])} 个 SKU 被识别为跨季去化或暂缓补货，重点集中在 {top_seasonal_categories} 这些品类。",
                "goal": "避免把非主销季的货继续补深，把钱和货位留给当前季节。",
                "schemes": [
                    {
                        "name": "有库存先去化",
                        "detail": f"如果 {top_seasonal_categories} 这些跨季品类手里还有库存，优先转到去化清单，用组合价、加价购、门口清货位来动销。",
                    },
                    {
                        "name": "没库存不再追补",
                        "detail": "如果某个跨季品类当前库存已经为 0，现阶段不要因为历史卖过就立即补，先等回到主销季再评估。",
                    },
                    {
                        "name": "跨季款单独看板",
                        "detail": "先看“跨季处理重点品类”，再下钻到单款。由老板每周决定这些品类是去化、暂缓还是等待下季，不跟当季补货混在一起。",
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


def compute_change_ratio(current: float, previous: float) -> float:
    if not previous:
        return 0.0
    return (float(current) - float(previous)) / float(previous)


def judge_sales_driver(order_delta: float, aov_delta: float) -> str:
    if abs(order_delta) >= abs(aov_delta) + 0.05:
        return "单量变化"
    if abs(aov_delta) >= abs(order_delta) + 0.05:
        return "客单价变化"
    return "单量和客单共同变化"


def build_retail_consulting_analysis(metrics: dict, period_type: str | None = None) -> dict[str, object]:
    cards = metrics["summary_cards"]
    actions = metrics["action_summary"]
    decision = build_decision_engine(metrics)
    time_strategy = build_time_strategy(metrics)
    profit = cards.get("profit_snapshot")
    yeusoft = metrics.get("yeusoft_highlights") or {}
    sales_overview = yeusoft.get("sales_overview") or {}
    member_rank = yeusoft.get("member_rank") or {}
    stock_analysis = yeusoft.get("stock_analysis") or {}
    category_highlight = yeusoft.get("category_analysis") or {}
    vip_analysis = yeusoft.get("vip_analysis") or {}
    guide_report = yeusoft.get("guide_report") or {}
    store_month_report = yeusoft.get("store_month_report") or {}
    retail_detail = yeusoft.get("retail_detail") or {}

    period_label = "本月" if period_type == "monthly" else "本季度" if period_type == "quarterly" else "当前阶段"
    previous_label = "上月" if period_type == "monthly" else "上季度" if period_type == "quarterly" else "上一阶段"
    focus_title = "本月最值得关注的 5 个问题" if period_type != "quarterly" else "本季度最值得关注的 5 个问题"
    latest = (
        sales_overview.get("latest_month")
        if period_type in (None, "monthly")
        else sales_overview.get("latest_quarter")
    )
    previous = (
        sales_overview.get("previous_month")
        if period_type in (None, "monthly")
        else sales_overview.get("previous_quarter")
    )

    category_sales = metrics["sales_by_category_ex_props"].copy()
    top_category_name = top_label_from_series(category_sales["商品大类"], "主营品类") if not category_sales.empty else "主营品类"
    top_category_share = (
        safe_ratio(float(category_sales.iloc[0]["销售额"]), float(category_sales["销售额"].sum()))
        if not category_sales.empty
        else 0.0
    )
    top_two_share = (
        safe_ratio(float(category_sales.head(2)["销售额"].sum()), float(category_sales["销售额"].sum()))
        if not category_sales.empty
        else 0.0
    )

    category_risks = metrics["category_risks"].copy()
    top_risk_category = top_label_from_series(category_risks["大类"], "高风险品类") if not category_risks.empty else "高风险品类"
    top_replenish_category = top_label_from_series(metrics["replenish_categories"]["中类"], "补货重点") if not metrics["replenish_categories"].empty else "补货重点"
    top_clearance_category = top_label_from_series(metrics["clearance_categories"]["大类"], "去化重点") if not metrics["clearance_categories"].empty else "去化重点"
    top_seasonal_category = top_label_from_series(metrics["seasonal_categories"]["中类"], "跨季品类") if not metrics["seasonal_categories"].empty else "跨季品类"

    best_sellers = metrics["low_stock_bestsellers"].head(3).copy()
    replenishment_skus = metrics["replenish"].head(5).copy()
    slow_skus = metrics["slow_moving"].head(5).copy()
    clearance_skus = metrics["clearance"].head(5).copy()
    top_members = metrics["top_members"].head(5).copy()
    guide_perf = metrics["guide_perf"].copy()
    avg_attachment = float(guide_perf["连带"].mean()) if not guide_perf.empty else 0.0
    avg_guide_ticket = float(guide_perf["单效"].mean()) if not guide_perf.empty else cards["avg_order_value"]
    sales_trend = decision["sales_trend"]

    sales_analysis: list[str] = []
    if latest and previous:
        sales_delta = compute_change_ratio(latest["sales_amount"], previous["sales_amount"])
        order_delta = compute_change_ratio(latest["order_count"], previous["order_count"])
        aov_delta = compute_change_ratio(latest["avg_order_value"], previous["avg_order_value"])
        driver = judge_sales_driver(order_delta, aov_delta)
        direction = "增长" if sales_delta >= 0 else "下降"
        sales_analysis.append(
            f"【直接数据】{period_label}销售额 {format_num(latest['sales_amount'], 2)} 元，较{previous_label}{direction} {format_num(abs(sales_delta) * 100, 1)}%。"
        )
        if driver == "单量变化":
            sales_analysis.append(
                f"【直接数据】变化主要来自单量，订单数较{previous_label}{'增加' if order_delta >= 0 else '回落'} {format_num(abs(order_delta) * 100, 1)}%，客单价变化相对更小。"
            )
        elif driver == "客单价变化":
            sales_analysis.append(
                f"【直接数据】变化主要来自客单价，客单价较{previous_label}{'增加' if aov_delta >= 0 else '回落'} {format_num(abs(aov_delta) * 100, 1)}%，单量变化相对更小。"
            )
        else:
            sales_analysis.append(
                f"【直接数据】销售变化是单量和客单一起推动的，订单数变化 {format_num(order_delta * 100, 1)}%，客单价变化 {format_num(aov_delta * 100, 1)}%。"
            )
        sales_analysis.append(
            f"【直接数据】当前主销中类是 {latest['top_category']}，说明阶段性增长/下滑主要先看这个中类有没有继续撑住。"
        )
    else:
        sales_analysis.append(
            f"【直接数据】当前短期销售窗口为最近 {cards['sales_days']} 天，经营销售额 {format_num(cards['sales_amount'], 2)} 元，日销趋势判断为 {sales_trend['label']}。"
        )
        sales_analysis.append(
            "【经营推断】当前更像短期波动判断，还缺连续月度可对比数据；先用日销趋势判断流量和转化节奏。"
        )

    if top_category_share >= 0.45:
        sales_analysis.append(
            f"【经营判断】销售看起来不算差，但结构并不轻松，{top_category_name} 单类大约贡献了 {format_num(top_category_share * 100, 1)}% 销售，存在“靠少数品类硬撑”的风险。"
        )
    elif cards["estimated_inventory_days"] >= 180:
        sales_analysis.append(
            "【经营判断】销售额不是唯一问题，库存覆盖天数偏长，说明现在更像“卖得还行但结构不健康”，不适合继续平均进货。"
        )
    else:
        sales_analysis.append("【经营判断】当前销售结构还算能打，但要继续盯主销品类是否稳定，不要让少数爆款突然断货。")
    if retail_detail:
        sales_analysis.append(
            f"【直接数据】全量零售明细显示，当前实销折扣约 {format_num(retail_detail['weighted_discount_rate'] * 10, 1)} 折，深折扣销售占比约 {format_num(retail_detail['deep_discount_sales_share'] * 100, 1)}%。"
        )
        if retail_detail.get("markdown_pressure_high"):
            sales_analysis.append(
                f"【经营判断】当前销售不只是流量问题，{retail_detail['discount_category_names']} 这些品类已经有明显折扣依赖。继续靠深折扣冲营业额，会先伤毛利。"
            )

    category_analysis: list[str] = []
    if not category_sales.empty:
        top_contributors = "、".join(
            f"{row['商品大类']}({format_num(row['销售额'], 2)}元)"
            for _, row in category_sales.head(3).iterrows()
        )
        category_analysis.append(f"【直接数据】品类贡献排序靠前的是：{top_contributors}。")
    if category_highlight:
        growth_rows = category_highlight.get("growth_rows") or []
        decline_rows = category_highlight.get("decline_rows") or []
        if growth_rows:
            category_analysis.append(
                "【直接数据】阶段性增长更快的品类主要是："
                + "、".join(f"{row['name']}(+{format_num(row['delta_sales'], 2)}元)" for row in growth_rows)
                + "。"
            )
        if decline_rows:
            category_analysis.append(
                "【直接数据】阶段性回落更明显的品类主要是："
                + "、".join(f"{row['name']}({format_num(row['delta_sales'], 2)}元)" for row in decline_rows)
                + "。"
            )
    if not category_risks.empty:
        top_risks = "、".join(
            f"{row['大类']}({row['状态']})" for _, row in category_risks.head(3).iterrows()
        )
        category_analysis.append(f"【直接数据】品类风险排序靠前的是：{top_risks}。")
    if not metrics["replenish_categories"].empty:
        top_replenish_rank = "、".join(
            f"{row['中类']}({format_num(row['建议补货量'])})"
            for _, row in metrics["replenish_categories"].head(3).iterrows()
        )
        category_analysis.append(f"【直接数据】品类动作建议里，补货优先级靠前的是：{top_replenish_rank}。")
    if not metrics["clearance_categories"].empty:
        top_clear_rank = "、".join(
            f"{row['大类']}({format_num(row['实际库存'])})"
            for _, row in metrics["clearance_categories"].head(3).iterrows()
        )
        category_analysis.append(f"【直接数据】去化优先级靠前的是：{top_clear_rank}。")
    if top_two_share >= 0.7:
        category_analysis.append(
            f"【经营判断】前两大品类大约贡献了 {format_num(top_two_share * 100, 1)}% 销售，结构偏集中。短期靠它们撑得住，长期要防一旦主力品类失速，整体营业额会一起掉。"
        )
    else:
        category_analysis.append("【经营判断】品类结构不算单一，但库存风险和补货节奏已经开始分化，后面要按品类区别对待，而不是平均发力。")
    if category_highlight and category_highlight.get("top2_share", 0) >= 0.65:
        category_analysis.append(
            f"【经营判断】从全量品类分析看，前两品类贡献约 {format_num(category_highlight['top2_share'] * 100, 1)}%，销售更多靠少数品类撑着，扩品只能做补充，不能动摇主销预算。"
        )
    if retail_detail and retail_detail.get("top_discount_categories"):
        discount_text = "、".join(
            f"{row['name']}({format_num(row['discount_rate'] * 10, 1)}折)"
            for row in retail_detail["top_discount_categories"][:3]
        )
        category_analysis.append(f"【直接数据】折扣依赖更明显的中类是：{discount_text}。")
        category_analysis.append(
            "【经营判断】这说明部分品类现在更像“靠让利换成交”，如果不先调陈列、组合和尺码结构，后面利润会持续被拖薄。"
        )

    sku_analysis: list[str] = []
    if not best_sellers.empty:
        hot_list = "、".join(f"{row['款号']}/{row['颜色']}" for _, row in best_sellers.head(3).iterrows())
        sku_analysis.append(f"【直接数据】当前爆款/断货风险款主要集中在：{hot_list}。")
        sku_analysis.append("【动作建议】这类款先保核心尺码和主销色，不建议一次补深，按 2-3 次小单快返来补最稳。")
    if not replenishment_skus.empty:
        sku_analysis.append(
            f"【经营判断】有持续动销能力的 SKU 主要集中在 {top_replenish_category}，它们更适合稳补；如果只是一两周突然冲高，则先按小量试补处理。"
        )
    if not clearance_skus.empty:
        slow_list = "、".join(f"{row['商品款号']}" for _, row in clearance_skus.head(3).iterrows())
        sku_analysis.append(f"【直接数据】明显滞销或高库存低动销 SKU 主要有：{slow_list}。")
        sku_analysis.append(
            "【动作建议】这类货不要继续深补，优先判断是季节错了、陈列靠后、价格门槛高，还是尺码结构不对，再决定轻促销还是强去化。"
        )
    if not slow_skus.empty:
        sku_analysis.append("【经营判断】连续慢销款更像结构问题，不只是单品问题。先调陈列和搭配，如果 1-2 周仍不改善，再升级到清货动作。")
    if retail_detail and retail_detail.get("size_rows"):
        sku_analysis.append(
            f"【直接数据】全量零售明细显示，主销尺码更集中在：{retail_detail['core_size_names']}。"
        )
        sku_analysis.append(
            "【动作建议】补货不要全尺码平均补，先保这些主销尺码，再用小量补单观察边缘尺码是否真有动销。"
        )

    inventory_actions = {
        "立即补货": [],
        "可观察补货": [],
        "控制补货": [],
        "尽快去化": [],
        "暂缓处理": [],
    }
    if not metrics["replenish_categories"].empty:
        for _, row in metrics["replenish_categories"].head(5).iterrows():
            target = "立即补货" if row["季节策略"] == "当季主推" else "可观察补货"
            inventory_actions[target].append(f"{row['中类']}（建议补货量 {format_num(row['建议补货量'])}）")
    if not metrics["category_risks"].empty:
        for _, row in metrics["category_risks"].head(5).iterrows():
            if row["状态"] == "高压货":
                inventory_actions["尽快去化"].append(f"{row['大类']}（库存金额/销售金额 {format_num(row['库存金额/销售金额'], 2)}）")
            elif row["状态"] == "需关注":
                inventory_actions["控制补货"].append(f"{row['大类']}（先控补货节奏）")
    if not metrics["seasonal_categories"].empty:
        for _, row in metrics["seasonal_categories"].head(5).iterrows():
            target = "暂缓处理" if row["建议动作"] == "暂缓补货" else "尽快去化"
            inventory_actions[target].append(f"{row['中类']}（{row['建议动作']}）")

    inventory_analysis = [
        f"【直接数据】当前经营库存覆盖天数约 {format_num(cards['estimated_inventory_days'], 1)} 天，库存压力判断为 {'偏重' if cards['estimated_inventory_days'] >= 120 else '可控'}。",
        f"【直接数据】库存压力最大的品类先看 {top_risk_category}，而补货优先品类先看 {top_replenish_category}，说明库存结构已经出现“该补的不一定多、该去化的反而压得深”的失衡。",
    ]
    if cards["estimated_inventory_days"] >= 180:
        inventory_analysis.append("【经营判断】当前更适合先去化再补货；如果先补，会把现金继续压进旧货和错季货里。")
    else:
        inventory_analysis.append("【经营判断】当前是补货和去化并行，但补货只补主销和缺码，不能平均补。")

    member_analysis: list[str] = []
    member_analysis.append(
        f"【直接数据】会员销售额占比约 {format_num(cards['member_sales_ratio'] * 100, 1)}%，最近客单价约 {format_num(cards['avg_order_value'], 2)} 元。"
    )
    if avg_attachment > 0:
        member_analysis.append(
            f"【直接数据】店员平均连带约 {format_num(avg_attachment, 2)}，平均单效约 {format_num(avg_guide_ticket, 2)} 元。"
        )
    if cards["member_sales_ratio"] >= 0.6:
        member_analysis.append("【经营判断】当前销售已经明显依赖会员，说明复购稳定性不错，下一步更该做的是把高价值会员的回访和搭配销售做深。")
    else:
        member_analysis.append("【经营判断】当前会员贡献不算稳，后面要补会员召回和老客复购，不然销售容易更多靠自然客流波动。")
    if vip_analysis:
        member_analysis.append(
            f"【直接数据】会员基盘里目前有 {format_num(vip_analysis['member_count'])} 位会员，近 60 天活跃 {format_num(vip_analysis['active_recent_count'])} 位，沉默占比约 {format_num(vip_analysis['dormant_ratio'] * 100, 1)}%。"
        )
        if vip_analysis["dormant_ratio"] >= 0.35:
            member_analysis.append("【经营判断】会员沉默占比偏高，说明老客不是没有，而是唤醒不够。这个阶段更适合做一对一回访，而不是只等自然复购。")
        else:
            member_analysis.append("【经营判断】会员活跃度还算可以，可以把重点放在高价值会员的复购和连带，而不是泛泛拉群。")
    if avg_attachment and avg_attachment < 1.5:
        member_analysis.append("【经营判断】现在更像“有成交，但每单带得不够”，优先提高连带率，比单纯追客流更划算。")
    else:
        member_analysis.append("【经营判断】连带不算太差，但仍建议用基础打底 + 袜品 + 家居服组合继续放大客单。")
    if top_members is not None and not top_members.empty:
        top_member_names = "、".join(top_members["VIP姓名"].astype(str).head(3).tolist())
        member_analysis.append(f"【动作建议】会员回访先盯 {top_member_names}，优先做换季提醒、到店试穿和组合推荐。")
    if guide_report:
        member_analysis.append(
            f"【直接数据】导购总销里 VIP 销售占比约 {format_num(guide_report['vip_sales_share'] * 100, 1)}%，头部导购 {guide_report['top_guide_name']} 贡献约 {format_num(guide_report['top_guide_share'] * 100, 1)}%。"
        )

    rhythm_analysis: list[str] = []
    stage_label = "去库存阶段" if cards["estimated_inventory_days"] >= 180 else "稳利润阶段" if profit and not profit["passed_breakeven"] else "冲销售阶段"
    if not profit:
        stage_label = decision["stage"]
    rhythm_analysis.append(f"【经营判断】当前更像 {stage_label}，不是简单追销售额。")
    if profit:
        if profit["projected_month_net_profit"] < 0:
            rhythm_analysis.append("【直接数据】按当前节奏月末仍有亏损风险，本周应该先保毛利、控补货、做去化，而不是盲目冲低价促销。")
        elif profit["passed_breakeven"]:
            rhythm_analysis.append("【直接数据】当前已经过保本线，后面可以在不伤毛利的前提下放大营业额。")
        if profit["remaining_days"] > 0:
            rhythm_analysis.append(
                f"【直接数据】后面每天至少还要卖 {format_num(profit['remaining_daily_sales_needed'], 2)} 元才能过保本；如果继续慢半拍，月底就会靠最后几天硬冲。"
            )
    if sales_trend["direction"] == "down":
        rhythm_analysis.append("【经营判断】当前节奏更像转化或结构问题，不只是客流问题。先看主销品类和连带，再看活动。")
    else:
        rhythm_analysis.append("【经营判断】当前节奏还能推进，但要防止销售做上去了，利润却被深补和清货拖掉。")
    if store_month_report:
        latest_joint = store_month_report.get("latest_month") or {}
        if latest_joint:
            rhythm_analysis.append(
                f"【直接数据】最近月度件单比约 {format_num(latest_joint.get('joint_rate', 0), 2)}，低连带天数 {format_num(store_month_report.get('low_joint_days', 0))} 天。"
            )
            if latest_joint.get("joint_rate", 0) < 1.2:
                rhythm_analysis.append("【经营判断】当前节奏还有一个明显短板是连带偏弱。进店有单，但每单件数不高，店员执行要先盯组合成交。")

    if guide_report:
        top_guide_name = guide_report.get("top_guide_name") or "主力导购"
        top_guide_share = guide_report.get("top_guide_share", 0)
    else:
        top_guide_name = "主力导购"
        top_guide_share = 0.0
    retail_detail = yeusoft.get("retail_detail") or {}

    diagnosis_summary = (
        f"当前门店最需要优先处理的是 {strip_sentence_tail(decision['headline'])}。"
        f"从数据看，销售主力仍集中在 {top_category_name}，但库存压力主要压在 {top_risk_category}，"
        f"补货应优先给 {top_replenish_category}，去化则先盯 {top_clearance_category}。"
    )
    if profit:
        diagnosis_summary += (
            f" 按当前口径，本月净利预测约 {format_num(profit['projected_month_net_profit'], 2)} 元，"
            f"{'还没有真正过保本线' if not profit['passed_breakeven'] else '已经过保本线，但还要防库存结构失衡'}。"
        )

    focus_issues = dedupe_preserve_order(
        [
            f"库存覆盖天数约 {format_num(cards['estimated_inventory_days'], 1)} 天，库存压力偏重。" if cards["estimated_inventory_days"] >= 120 else f"{top_replenish_category} 当前更需要防断货。",
            f"负库存 SKU 还有 {format_num(cards['negative_sku_count'])} 个，库存口径还没完全干净。" if cards["negative_sku_count"] > 0 else f"当前库存口径基本可用，但仍要继续做周期盘点。",
            f"{top_risk_category} 是当前压货最重的品类，继续补货会进一步拖慢周转。",
            f"{top_category_name} 贡献占比较高，结构上仍有“靠少数品类撑销售”的风险。" if top_category_share >= 0.45 else f"品类结构不算失衡，但补货和去化节奏已经明显分化。",
            "会员贡献已经很高，但连带和复购还可以继续放大。" if cards["member_sales_ratio"] >= 0.6 else "会员贡献还不够稳，销售容易受自然客流影响。",
            "月末净利预测仍偏弱，销售和利润需要一起抓。" if profit and profit["projected_month_net_profit"] < 0 else "利润口径暂时可控，但不能因为销售回暖就放松库存管理。",
        ]
    )[:5]

    weekly_actions = dedupe_preserve_order(
        [
            f"先把 {top_risk_category} 做成专项去化表，先停补、先前移陈列、先做组合价。",
            f"把 {top_replenish_category} 的核心尺码和主销色列成补货清单，本周只补最能带营业额的那批。",
            "先校正负库存，再安排补货；库存没校准前，不做深补。",
            "把高价值会员分成 3 组：本周联系、下周联系、暂缓联系，避免群发式打扰。",
            "店员统一搭配话术：先卖主销，再顺带袜品/基础打底/家居服，提高连带。",
            f"店员排班和带教先盯 {top_guide_name} 的做法，当前销售占比约 {format_num(top_guide_share * 100, 1)}%。",
        ]
        + (
            [
                f"重点复核 {retail_detail['discount_category_names']} 的折扣策略，"
                f"主销尺码先保 {retail_detail['core_size_names']}，不要平均补货。"
            ]
            if retail_detail
            else []
        )
    )[:3]

    replenish_advice = dedupe_preserve_order(
        inventory_actions["立即补货"] + inventory_actions["可观察补货"] or [f"{top_replenish_category} 先按小单快返补货。"]
    )[:6]
    clearance_advice = dedupe_preserve_order(
        inventory_actions["尽快去化"] + inventory_actions["控制补货"] or [f"{top_clearance_category} 先停补，再做去化。"]
    )[:6]
    category_advice = dedupe_preserve_order(
        [
            f"{top_category_name} 继续做主销中轴，优先保不断码。",
            f"{top_risk_category} 先控采购，再安排门口清货位和组合去化。",
            f"{top_seasonal_category} 这类跨季品类要单独管理，不跟当季补货混预算。",
            "儿童内衣 / 棉品 / 家居服要分清角色：主销、连带、去化，别放在一张表里平均看。",
        ]
    )

    owner_advice = dedupe_preserve_order(
        [
            f"本周先盯 3 个数：保本进度、库存覆盖天数、{top_replenish_category} 的断码情况。",
            f"需要你拍板的不是所有货，而是 {top_risk_category} 怎么去化、{top_seasonal_category} 是否暂缓、{top_replenish_category} 补货预算给多少。",
            "如果这周只能做一个经营动作，就先把高库存慢销货位和清货策略定下来，不要让旧货继续占预算。",
        ]
        + (
            [
                f"对 {retail_detail['discount_category_names']} 这几个中类，先拍板是稳毛利还是继续让利；"
                f"补货预算先保 {retail_detail['core_size_names']} 这些主销尺码。"
            ]
            if retail_detail
            else []
        )
    )
    manager_advice = dedupe_preserve_order(
        [
            f"先把 {top_risk_category} 从正常主陈列里压缩出来，给 {top_replenish_category} 腾出更前的位置。",
            "盯员工两件事：主销款不断推、每单至少带一件顺手连带商品。",
            "把负库存、去化名单、补货名单分三张小表带晨会，不要让店员自己判断优先级。",
            f"会员跟进先看 {top_members['VIP姓名'].head(3).tolist() if not top_members.empty else '高价值会员名单'}。",
            f"导购执行先对齐 {top_guide_name} 的成交路径，再让其他人照着练，避免每个人各讲各的。",
        ]
        + (
            [
                f"补货清单先按 {retail_detail['core_size_names']} 排序，"
                f"{retail_detail['discount_category_names']} 这些中类先控量补、先看毛利。"
            ]
            if retail_detail
            else []
        )
    )
    staff_advice = dedupe_preserve_order(
        [
            f"今天优先推 {top_replenish_category}，这是当前最值得先卖、也最该先保不断货的品类。",
            f"带货顺序先主销，再顺带 {top_clearance_category if top_clearance_category != '去化重点' else '袜品/基础打底/家居服'} 这类更容易顺手带走的商品。",
            "慢销款不要硬单推，改成组合推荐：基础款 + 袜品 / 家居服 / 第二件优惠。",
            "顾客犹豫时，先问使用场景和孩子年龄，再推最稳的基础款，不要先推难卖的货。",
        ]
        + (
            [
                f"如果顾客在看 {retail_detail['discount_category_names']} 这些中类，先做组合和场景推荐，"
                "不要一上来就主动降价。"
            ]
            if retail_detail
            else []
        )
    )

    risk_alerts = dedupe_preserve_order(
        [
            f"如果继续平均补货，{top_risk_category} 的压货会继续加重。",
            "如果负库存不先纠偏，补货建议和库存健康判断都会继续失真。" if cards["negative_sku_count"] > 0 else "库存口径相对正常，但仍建议继续做周期盘点。",
            "如果会员回访只做群发，不做分层，复购效率会继续偏低。",
            "如果当前主销中类突然断码，销售额会很容易直接下滑。",
            "如果跨季货不单独管理，到了下个季节会出现旧货、新货一起压的情况。",
        ]
    )

    if_ignore = dedupe_preserve_order(
        [
            f"下周最可能先出现的是 {top_risk_category} 库存继续变重，但真正能卖的 {top_replenish_category} 反而更容易断。",
            "店员会继续把时间花在介绍货，而不是推动组合成交，客单和连带抬不起来。",
            "如果月底前还没压住慢销库存，利润会继续被固定费用和工资吃掉。",
            "跨季货如果这周不处理，下周仍会占货位，影响春夏主销款出样和成交。",
        ]
    )

    priority_matrix = {
        "重要且紧急": dedupe_preserve_order(
            [
                "先纠偏负库存，再决定补货和去化。" if cards["negative_sku_count"] > 0 else f"先处理 {top_risk_category} 的高库存压力。",
                f"先停补 {top_risk_category}，优先安排去化和货位调整。",
                "如果净利预测为负，先盯保本日销和高毛利主销组合。" if profit and profit["projected_month_net_profit"] < 0 else f"优先保住 {top_replenish_category} 的主销不断码。",
            ]
        ),
        "重要不紧急": dedupe_preserve_order(
            [
                "把高价值会员分层回访，做换季提醒和复购带连带。",
                f"把 {top_seasonal_category} 这类跨季货单独管理，避免下一轮继续压货。",
                "每周固定复盘一次品类贡献、补货效果和去化进度。",
            ]
        ),
        "可观察": dedupe_preserve_order(
            [
                "下一季试补品类先小量试单，观察 1 周再决定是否放大。",
                "继续跟踪店员连带率和客单价，判断是不是单量正常但带得少。",
            ]
        ),
        "暂不处理": dedupe_preserve_order(
            [
                "暂不做非核心品类深补。",
                "暂不为了冲营业额做全场重折扣。",
                "暂不把预算投向还没验证的新扩品。",
            ]
        ),
    }

    direct_basis = [
        f"{period_label}销售、订单、客单变化来自 POS 全量销售数据。"
        if latest
        else f"当前销售判断来自最近 {cards['sales_days']} 天经营销售窗口。"
    ]
    if not category_sales.empty:
        direct_basis.append("品类贡献和库存风险来自当前销售、库存和进销存报表。")
    if not metrics["replenish_categories"].empty or not metrics["clearance_categories"].empty:
        direct_basis.append("补货和去化建议来自 SKU 动销、库存周数、季节策略和库存风险规则。")
    if category_highlight:
        direct_basis.append("品类增长/回落判断补充参考了商品品类分析的全量周期数据。")
    if vip_analysis:
        direct_basis.append("会员活跃与沉默判断补充参考了会员综合分析。")
    if guide_report:
        direct_basis.append("店员人效和连带判断补充参考了导购员报表与门店销售月报。")

    inferred_basis = [
        "哪些品类更适合继续放大，部分基于当前主销中类、库存结构和换季逻辑做经营推断。",
        "滞销原因中的价格、陈列、尺码结构问题，属于结合零售经验的判断，不是系统直接字段。",
    ]
    need_more_basis = [
        "如果要更准判断品类增长来源，最好再补连续月度的分品类销售明细。",
        "如果要更准判断店员转化问题，最好补进店人数或试穿数据。",
    ]

    return {
        "period_label": period_label,
        "focus_title": focus_title,
        "diagnosis_summary": diagnosis_summary,
        "focus_issues": focus_issues,
        "weekly_actions": weekly_actions,
        "replenish_advice": replenish_advice,
        "clearance_advice": clearance_advice,
        "category_advice": category_advice,
        "role_guidance": {
            "老板娘": owner_advice,
            "店长": manager_advice,
            "店员": staff_advice,
        },
        "risk_alerts": risk_alerts,
        "if_ignore": if_ignore,
        "priority_matrix": priority_matrix,
        "sales_analysis": sales_analysis,
        "category_analysis": category_analysis,
        "sku_analysis": sku_analysis,
        "inventory_analysis": inventory_analysis,
        "member_analysis": member_analysis,
        "rhythm_analysis": rhythm_analysis,
        "basis_notes": {
            "direct": direct_basis,
            "inferred": inferred_basis,
            "need_more": need_more_basis,
        },
    }


def render_consulting_analysis_html(
    analysis: dict[str, object],
    title: str = "经营分析与销售建议",
    section_id: str = "consulting-analysis",
) -> str:
    sections = [
        ("经营诊断总结", [analysis["diagnosis_summary"]]),
        (analysis["focus_title"], analysis["focus_issues"]),
        ("销售表现分析", analysis["sales_analysis"]),
        ("品类结构分析", analysis["category_analysis"]),
        ("SKU / 爆款 / 滞销分析", analysis["sku_analysis"]),
        ("库存健康分析", analysis["inventory_analysis"]),
        ("会员 / 客单价 / 连带率分析", analysis["member_analysis"]),
        ("目标达成与节奏分析", analysis["rhythm_analysis"]),
        ("本周优先动作建议", analysis["weekly_actions"]),
        ("补货建议", analysis["replenish_advice"]),
        ("去化 / 清货建议", analysis["clearance_advice"]),
        ("品类经营建议", analysis["category_advice"]),
        ("风险预警清单", analysis["risk_alerts"]),
        ("如果下周不处理，最可能出现的问题", analysis["if_ignore"]),
    ]

    role_blocks = "".join(
        f"""
        <div class="analysis-card">
          <h3>{html.escape(role)}建议</h3>
          <ul class="analysis-list">
            {"".join(f"<li>{html.escape(item)}</li>" for item in items)}
          </ul>
        </div>
        """
        for role, items in analysis["role_guidance"].items()
    )

    priority_blocks = "".join(
        f"""
        <div class="analysis-card priority-{tone}">
          <h3>{html.escape(label)}</h3>
          <ul class="analysis-list">
            {"".join(f"<li>{html.escape(item)}</li>" for item in items)}
          </ul>
        </div>
        """
        for label, items, tone in (
            ("重要且紧急", analysis["priority_matrix"]["重要且紧急"], "red"),
            ("重要不紧急", analysis["priority_matrix"]["重要不紧急"], "yellow"),
            ("可观察", analysis["priority_matrix"]["可观察"], "neutral"),
            ("暂不处理", analysis["priority_matrix"]["暂不处理"], "green"),
        )
    )

    basis_html = "".join(
        f"""
        <div class="analysis-card">
          <h3>{html.escape(label)}</h3>
          <ul class="analysis-list">
            {"".join(f"<li>{html.escape(item)}</li>" for item in items)}
          </ul>
        </div>
        """
        for label, items in (
            ("基于数据直接得出的", analysis["basis_notes"]["direct"]),
            ("基于零售经验的判断", analysis["basis_notes"]["inferred"]),
            ("还需要补数据确认的", analysis["basis_notes"]["need_more"]),
        )
    )

    section_cards = "".join(
        f"""
        <div class="analysis-card">
          <h3>{html.escape(section_title)}</h3>
          <ul class="analysis-list">
            {"".join(f"<li>{html.escape(item)}</li>" for item in items)}
          </ul>
        </div>
        """
        for section_title, items in sections
    )

    return f"""
    <section class="module analysis-module" id="{html.escape(section_id)}">
      <div class="module-header">
        <h2 class="module-title">{html.escape(title)}</h2>
        <p class="module-note">这部分不只描述数据，而是把“发生了什么、说明什么、现在最该做什么、谁来做”一起讲清楚。</p>
      </div>
      <div class="analysis-grid">
        {section_cards}
      </div>
      <div class="module-header" style="margin-top:18px;">
        <h2 class="module-title">老板娘 / 店长 / 店员分角色建议</h2>
        <p class="module-note">同一份数据，三个角色的动作不一样，这里直接拆开给执行。</p>
      </div>
      <div class="analysis-grid">
        {role_blocks}
      </div>
      <div class="module-header" style="margin-top:18px;">
        <h2 class="module-title">经营动作优先级排序</h2>
        <p class="module-note">今天先干什么、这周重点抓什么、本月不能忽视什么，都按轻重缓急排好了。</p>
      </div>
      <div class="analysis-grid">
        {priority_blocks}
      </div>
      <div class="module-header" style="margin-top:18px;">
        <h2 class="module-title">判断依据说明</h2>
        <p class="module-note">哪些是直接数据，哪些是零售经验判断，哪些还需要后续补数据，这里单独说明。</p>
      </div>
      <div class="analysis-grid">
        {basis_html}
      </div>
    </section>
    """


def append_consulting_analysis_markdown(lines: list[str], analysis: dict[str, object]) -> None:
    lines.extend(
        [
            "## 经营诊断总结",
            "",
            f"- {analysis['diagnosis_summary']}",
            "",
            f"## {analysis['focus_title']}",
        ]
    )
    lines.extend(f"- {item}" for item in analysis["focus_issues"])
    lines.extend(["", "## 销售表现分析"])
    lines.extend(f"- {item}" for item in analysis["sales_analysis"])
    lines.extend(["", "## 品类结构分析"])
    lines.extend(f"- {item}" for item in analysis["category_analysis"])
    lines.extend(["", "## SKU / 爆款 / 滞销分析"])
    lines.extend(f"- {item}" for item in analysis["sku_analysis"])
    lines.extend(["", "## 库存健康分析"])
    lines.extend(f"- {item}" for item in analysis["inventory_analysis"])
    lines.extend(["", "## 会员 / 客单价 / 连带率分析"])
    lines.extend(f"- {item}" for item in analysis["member_analysis"])
    lines.extend(["", "## 目标达成与节奏分析"])
    lines.extend(f"- {item}" for item in analysis["rhythm_analysis"])
    lines.extend(["", "## 本周优先动作建议"])
    lines.extend(f"- {item}" for item in analysis["weekly_actions"])
    lines.extend(["", "## 补货建议"])
    lines.extend(f"- {item}" for item in analysis["replenish_advice"])
    lines.extend(["", "## 去化 / 清货建议"])
    lines.extend(f"- {item}" for item in analysis["clearance_advice"])
    lines.extend(["", "## 品类经营建议"])
    lines.extend(f"- {item}" for item in analysis["category_advice"])
    lines.extend(["", "## 老板娘 / 店长 / 店员分角色建议", "", "### 给老板娘的建议"])
    lines.extend(f"- {item}" for item in analysis["role_guidance"]["老板娘"])
    lines.extend(["", "### 给店长的建议"])
    lines.extend(f"- {item}" for item in analysis["role_guidance"]["店长"])
    lines.extend(["", "### 给店员的建议"])
    lines.extend(f"- {item}" for item in analysis["role_guidance"]["店员"])
    lines.extend(["", "## 风险预警清单"])
    lines.extend(f"- {item}" for item in analysis["risk_alerts"])
    lines.extend(["", "## 如果下周不处理，最可能出现的问题"])
    lines.extend(f"- {item}" for item in analysis["if_ignore"])
    lines.extend(["", "## 经营动作优先级排序", "", "### 重要且紧急"])
    lines.extend(f"- {item}" for item in analysis["priority_matrix"]["重要且紧急"])
    lines.extend(["", "### 重要不紧急"])
    lines.extend(f"- {item}" for item in analysis["priority_matrix"]["重要不紧急"])
    lines.extend(["", "### 可观察"])
    lines.extend(f"- {item}" for item in analysis["priority_matrix"]["可观察"])
    lines.extend(["", "### 暂不处理"])
    lines.extend(f"- {item}" for item in analysis["priority_matrix"]["暂不处理"])
    lines.extend(["", "## 判断依据说明", "", "### 基于数据直接得出的"])
    lines.extend(f"- {item}" for item in analysis["basis_notes"]["direct"])
    lines.extend(["", "### 基于零售经验做的判断"])
    lines.extend(f"- {item}" for item in analysis["basis_notes"]["inferred"])
    lines.extend(["", "### 还需要补充数据才能进一步确认"])
    lines.extend(f"- {item}" for item in analysis["basis_notes"]["need_more"])


def build_boss_action_board(metrics: dict) -> dict[str, object]:
    cards = metrics["summary_cards"]
    profit = cards.get("profit_snapshot")
    pos_highlights = metrics.get("yeusoft_highlights")
    decision = build_decision_engine(metrics)
    signals = build_homepage_operating_signals(metrics)
    seasonal_categories = metrics["seasonal_categories"].head(3)
    top_replenish_categories = decision["top_replenish"]
    top_clearance_categories = decision["top_clearance"]
    top_seasonal_categories = decision["top_seasonal"]
    headline = decision["headline"]
    summary = (
        f"{decision['summary']} 当前阶段：{decision['stage']}；"
        f"最近日销均值 {format_num(decision['sales_trend']['recent_avg'], 2)} 元。"
    )
    if profit:
        summary += (
            f" 当前净利润 {format_num(profit['net_profit'], 2)} 元，"
            f"{'已过' if profit['passed_breakeven'] else '尚未过'}保本线。"
            f" 按当前节奏月末净利润约 {format_num(profit['projected_month_net_profit'], 2)} 元。"
        )
    if pos_highlights and pos_highlights.get("stock_analysis"):
        summary += f" POS 库存主要压在 {pos_highlights['stock_analysis']['top_labels']}。"
    if pos_highlights and pos_highlights.get("movement"):
        summary += (
            f" 近段时间净入库 {format_num(pos_highlights['movement']['net_qty'])} 件，"
            "补货节奏也要一并考虑。"
        )
    if signals["category_concentrated"]:
        summary += (
            f" 前两品类贡献约 {format_num(signals['top2_share'] * 100, 1)}%，"
            "补货预算先保主销，别平均分。"
        )
    if signals["vip_dormant_high"]:
        summary += (
            f" 会员沉默占比约 {format_num(signals['dormant_ratio'] * 100, 1)}%，"
            "这周要主动唤醒老客。"
        )
    if signals["guide_concentrated"]:
        summary += (
            f" 店员销售主要集中在 {signals['top_guide_name']}，"
            "成交打法要尽快复制给其他人。"
        )
    if signals["markdown_pressure_high"] and decision["mode"] != "稳毛利优先":
        summary += (
            f" 当前实销折扣约 {format_num(signals['weighted_discount_rate'] * 10, 1)} 折，"
            f"{signals['discount_category_names']} 更依赖折扣，今天别急着做深折扣。"
        )
    if signals["low_joint"]:
        summary += (
            f" 最近件单比约 {format_num(signals['latest_joint_rate'], 2)}，"
            "说明成交有了，但每单带得还不够。"
        )

    first_watch_body = (
        "先打开“去化重点品类”和“负库存异常清单”。"
        if cards["negative_sku_count"] >= 30
        else "先打开“去化重点品类”，确认今天最该先处理的品类。"
    )
    if signals["markdown_pressure_high"]:
        first_watch_body = (
            f"先看 {signals['discount_category_names']} 的折扣依赖，再看 {signals['core_size_names']} 这些主销尺码。"
            "今天先稳毛利，再决定要不要做活动。"
        )
    elif signals["category_concentrated"]:
        first_watch_body = (
            f"先看 {signals['top_category_names']} 的补货和销售结构，"
            "今天的预算先保主销，再看其他品类。"
        )
    elif signals["low_joint"]:
        first_watch_body = (
            f"先看 {signals['latest_month_label']} 的件单比和组合销售提醒，"
            "今天优先提升每单带出的件数。"
        )
    elif signals["vip_dormant_high"]:
        first_watch_body = (
            f"先看会员基盘和高价值会员名单，优先把 {signals['top_member_names']} 这类老客叫回来。"
        )

    today_do_body = (
        f"先处理 {top_clearance_categories} 的库存压力；"
        f"补货只看 {top_replenish_categories} 这些当季主销品类。"
    )
    if signals["markdown_pressure_high"]:
        today_do_body = (
            f"今天先把 {signals['discount_category_names']} 做高毛利搭配和门口陈列，"
            f"补货只保 {signals['core_size_names']} 这些主销尺码，别直接靠深折扣冲量。"
        )
    elif signals["low_joint"]:
        today_do_body = (
            f"今天店员先做组合销售，重点把 {top_replenish_categories} 和袜品/内裤做搭配；"
            f"去化仍先盯 {top_clearance_categories}。"
        )
    elif signals["vip_dormant_high"]:
        today_do_body = (
            f"今天先做老客唤醒和会员回访，再把 {top_replenish_categories} 的主销款做定向推荐。"
        )

    owner_decision_body = (
        f"单独看 {top_seasonal_categories} 这些跨季品类，决定是去化、暂缓，还是等回到主销季再补。"
    )
    if signals["markdown_pressure_high"]:
        owner_decision_body = (
            f"今天先拍板 {signals['discount_category_names']} 是否继续让利，"
            f"同时确认 {signals['core_size_names']} 这些尺码的补货预算，别平均补货。"
        )
    elif signals["category_concentrated"]:
        owner_decision_body = (
            f"今天先拍板主销预算，优先给 {signals['top_category_names']}；"
            "其他补货只能做补充，不要平均分货。"
        )
    elif signals["guide_concentrated"]:
        owner_decision_body = (
            f"今天先把 {signals['top_guide_name']} 的成交话术、搭配顺序和加购打法拆出来，"
            "安排给另外店员直接照着用。"
        )
    elif signals["vip_dormant_high"]:
        owner_decision_body = (
            "今天先拍板老客唤醒动作，决定是会员回访、定向组合包，还是到店小福利。"
        )

    actions_today = [
        {
            "title": "先看哪张表",
            "body": first_watch_body,
        },
        {
            "title": "今天怎么做",
            "body": today_do_body,
        },
        {
            "title": "老板今天拍板什么",
            "body": owner_decision_body,
        },
    ]

    dont_do = [
        "不要先看单款，先看品类，再下钻到 SKU。",
        "不要把道具金额和库存算进正常经营判断。",
        "不要把其他输入人的店铺数据当成本店结论。",
    ]
    if not seasonal_categories.empty:
        dont_do.append("不要因为某个冬款历史卖过，就在春夏阶段继续追补。")
    if signals["category_concentrated"]:
        dont_do.append("不要把补货预算平均分到所有品类，先保主销结构。")
    if signals["guide_concentrated"]:
        dont_do.append("不要把成交全压在一个店员身上，头部打法要复制。")
    if signals["vip_dormant_high"]:
        dont_do.append("不要只等自然回购，沉默会员需要主动叫回。")
    if signals["markdown_pressure_high"]:
        dont_do.append("不要为了冲销量继续做深折扣，先看组合和尺码结构。")
    if signals["low_joint"]:
        dont_do.append("不要只盯单数，今天要想办法把每单带得更多。")

    reading_order = [
        "先看“老板一分钟结论”，确认今天的主任务。",
        "再看“经营健康灯”，判断先救火还是先放大机会。",
        "再看“补货重点品类 / 去化重点品类 / 跨季处理重点品类”。",
        "再看“会员经营 / 店员执行 / 月度件单比”这些结构提醒。",
        "最后再下钻到具体 SKU 明细表执行。",
    ]

    meeting_script = [
        f"今天主任务：{headline}",
        f"今天主盯品类：去化看 {top_clearance_categories}，补货看 {top_replenish_categories}。",
        "今天执行顺序：先纠偏，再去化，再补货。",
    ]
    if signals["vip_dormant_high"]:
        meeting_script.append("今天加一件事：沉默会员先回访，不要只等老客自己回来。")
    if signals["guide_concentrated"]:
        meeting_script.append(f"今天带教重点：先复制 {signals['top_guide_name']} 的成交动作。")
    if signals["markdown_pressure_high"]:
        meeting_script.append(
            f"今天毛利重点：{signals['discount_category_names']} 先稳折扣，主销尺码先保 {signals['core_size_names']}。"
        )
    if signals["low_joint"]:
        meeting_script.append("今天门店目标：每单多带一件，不只看有没有成交。")

    return {
        "headline": headline,
        "summary": summary,
        "actions_today": actions_today,
        "dont_do": dont_do,
        "reading_order": reading_order,
        "meeting_script": meeting_script,
        "decision": decision,
    }


def build_today_focus(metrics: dict) -> dict[str, object]:
    cards = metrics["summary_cards"]
    profit = cards.get("profit_snapshot")
    actions = metrics["action_summary"]
    decision = build_decision_engine(metrics)
    signals = build_homepage_operating_signals(metrics)
    replenish_categories = metrics["replenish_categories"]
    clearance_categories = metrics["clearance_categories"]
    seasonal_categories = metrics["seasonal_categories"]
    top_members = metrics["top_members"]

    top_replenish = trim_text(top_label_from_series(replenish_categories["中类"], "主销品类"), 6)
    top_clearance = trim_text(top_label_from_series(clearance_categories["大类"], "高库存品类"), 6)

    conclusions: list[str] = []
    if cards["negative_sku_count"] > 50:
        conclusions.append("先处理负库存")
    if cards["estimated_inventory_days"] > 180:
        conclusions.append("先去库存")
    elif cards["estimated_inventory_days"] > 120:
        conclusions.append("控制库存量")
    if signals["markdown_pressure_high"]:
        conclusions.append("先稳毛利")
    if signals["low_joint"]:
        conclusions.append("先提连带")
    if signals["vip_dormant_high"]:
        conclusions.append("先唤醒老客")
    if signals["category_concentrated"]:
        conclusions.append("先保主销预算")
    if actions["clearance_count"] > 50 or actions["high_risk_category_count"] > 0:
        conclusions.append(trim_text(f"先停补{top_clearance}", 12))
    if actions["replenish_count"] > 100:
        conclusions.append(trim_text(f"优先补{top_replenish}", 12))
    if seasonal_categories.shape[0] > 0:
        conclusions.append("处理跨季品类")
    if cards["member_sales_ratio"] >= 0.6:
        conclusions.append("联系高价值会员")
    if signals["guide_concentrated"]:
        conclusions.append("复制头部打法")
    if profit and not profit["passed_breakeven"]:
        conclusions.append("先冲保本线")
    if decision["mode"] == "保畅销优先":
        conclusions.append(trim_text(f"优先补{top_replenish}", 12))
    if decision["mode"] == "换季切换":
        conclusions.append("先做换季切换")

    conclusions = dedupe_preserve_order(conclusions)
    if len(conclusions) < 3:
        conclusions.extend(
            dedupe_preserve_order(
                [
                    trim_text(f"调整{top_clearance}陈列", 12),
                    trim_text(f"检查{top_replenish}断码", 12),
                    "稳住会员复购",
                ]
            )
        )
    conclusions = conclusions[:3]

    tasks: list[str] = []
    if cards["negative_sku_count"] > 0:
        tasks.append("处理负库存")
    if cards["estimated_inventory_days"] > 180:
        tasks.append("安排去库存动作")
    if not clearance_categories.empty:
        tasks.append(trim_text(f"调整{top_clearance}陈列", 12))
    if not replenish_categories.empty:
        tasks.append(trim_text(f"检查{top_replenish}断码", 12))
    if signals["markdown_pressure_high"]:
        tasks.append("检查折扣依赖")
        tasks.append("确认主销尺码")
    if signals["low_joint"]:
        tasks.append("今天主推组合单")
    if signals["vip_dormant_high"]:
        tasks.append("联系沉默会员")
    if signals["guide_concentrated"]:
        tasks.append("复制头部成交话术")
    if not seasonal_categories.empty:
        tasks.append("确认跨季处理")
    if not top_members.empty:
        tasks.append("联系高价值会员")
    if profit and not profit["passed_breakeven"]:
        tasks.append("对齐保本日销")
    tasks = dedupe_preserve_order(tasks)[:5]

    return {
        "conclusions": conclusions,
        "tasks": tasks,
    }


def suggestions_for_risk_action(action: str) -> list[str]:
    if action == "先停补再去化":
        return ["停止补货", "组合促销", "清货陈列"]
    return ["控制补货", "组合去化", "调整陈列"]


def infer_action_tip(label: str) -> str | None:
    text = str(label).strip()
    if text in HIGH_FREQUENCY_ACTION_TOOLTIPS:
        return HIGH_FREQUENCY_ACTION_TOOLTIPS[text]
    if text in ACTION_TOOLTIPS:
        return ACTION_TOOLTIPS[text]
    if text in STATUS_TOOLTIPS:
        return STATUS_TOOLTIPS[text]
    if text in SEASON_STRATEGY_TOOLTIPS:
        return SEASON_STRATEGY_TOOLTIPS[text]
    if text.startswith("先停补"):
        category = text.replace("先停补", "", 1) or "该品类"
        return f"这个结论表示先暂停 {category} 的新补货，把现有库存先卖掉，再决定后续是否恢复补货。"
    if text.startswith("优先补"):
        category = text.replace("优先补", "", 1) or "该品类"
        return f"这个结论表示先保住 {category} 的主销不断货。先补核心尺码和卖得快的颜色，不要平均补。"
    if text.startswith("调整") and text.endswith("陈列"):
        category = text[2:-2] or "该品类"
        return f"把 {category} 调整到更容易被看到的位置，主销前移，慢销后移，帮助今天更快出货。"
    if text.startswith("检查") and text.endswith("断码"):
        category = text[2:-2] or "该品类"
        return f"先检查 {category} 有没有缺核心尺码。断码会直接影响成交，确认后再做补货。"
    return None


def chip_html(label: str, tone: str = "neutral") -> str:
    safe_label = html.escape(str(label))
    tip = infer_action_tip(label)
    attrs = ""
    classes = f"mini-chip mini-chip-{tone}"
    if tip:
        safe_tip = html.escape(tip, quote=True)
        classes += " tooltip-badge"
        attrs = f' title="{safe_tip}" data-tip="{safe_tip}" tabindex="0" role="note"'
    return f"<span class='{classes}'{attrs}>{safe_label}</span>"


def table_html(df: pd.DataFrame, title: str, rows: int = 10, tip: str | None = None) -> str:
    preview = df.head(rows).copy()
    preview = decorate_table(preview)
    tip_html = f"<p class='table-tip'>{tip}</p>" if tip else ""
    columns = list(preview.columns)
    mobile_visible_cols = min(3, len(columns))
    has_hidden_cols = len(columns) > mobile_visible_cols

    header_html = "".join(
        f"<th data-mobile-hidden=\"{'1' if idx >= mobile_visible_cols else '0'}\">{html.escape(str(column))}</th>"
        for idx, column in enumerate(columns)
    )
    body_rows: list[str] = []
    for _, row in preview.iterrows():
        cells = "".join(
            f"<td data-mobile-hidden=\"{'1' if idx >= mobile_visible_cols else '0'}\" data-col-name=\"{html.escape(str(column), quote=True)}\">"
            f"{safe_cell_html(row[column])}</td>"
            for idx, column in enumerate(columns)
        )
        body_rows.append(f"<tr>{cells}</tr>")

    toggle_html = ""
    if has_hidden_cols:
        toggle_html = (
            "<button type='button' class='table-toggle' data-table-toggle data-expand-label='展开全部列' "
            "data-collapse-label='收起额外列'>展开全部列</button>"
        )
    card_classes = "table-card is-compact" if has_hidden_cols else "table-card"

    return f"""
    <section class="{card_classes}">
      <div class="table-header">
        <h3>{title}</h3>
        {toggle_html}
      </div>
      {tip_html}
      <div class="table-scroll">
        <table class="data-table" border="0">
          <thead><tr>{header_html}</tr></thead>
          <tbody>{''.join(body_rows)}</tbody>
        </table>
      </div>
    </section>
    """


def compact_stat_row(label: str, value: object, is_badge: bool = False, tone: str = "soft") -> str:
    content = chip_html(str(value), tone) if is_badge else f"<strong>{html.escape(str(value))}</strong>"
    return f"<div class='compact-stat'><span>{html.escape(label)}</span>{content}</div>"


def build_yeusoft_highlight_cards(pos_highlights: dict | None) -> list[dict[str, str]]:
    if not pos_highlights:
        return []

    cards: list[dict[str, str]] = []
    sales_overview = pos_highlights.get("sales_overview")
    if sales_overview:
        top_category_labels = sales_overview.get("top_category_labels") or "暂无明显主销中类"
        cards.append(
            {
                "title": "POS 全期零售",
                "value": f"{format_num(sales_overview['sales_amount'], 2)} 元",
                "note": (
                    f"主销中类 {top_category_labels}，会员销售占比 "
                    f"{format_num(sales_overview['member_sales_ratio'] * 100, 1)}%。"
                ),
            }
        )

    product_sales = pos_highlights.get("product_sales")
    if product_sales:
        cards.append(
            {
                "title": "POS 商品动销",
                "value": f"售罄率 {format_num(product_sales['sellout_rate'] * 100, 1)}%",
                "note": (
                    f"当前库存 {format_num(product_sales['current_stock_qty'])} 件，快销潜力款 "
                    f"{format_num(product_sales['fast_sellout_count'])} 个，积压风险款 "
                    f"{format_num(product_sales['backlog_count'])} 个。"
                ),
            }
        )

    member_rank = pos_highlights.get("member_rank")
    if member_rank:
        cards.append(
            {
                "title": "POS 会员排行",
                "value": member_rank["top_names"],
                "note": (
                    f"前 10 位会员贡献 {format_num(member_rank['top10_share'] * 100, 1)}% 销额，"
                    f"适合做定向复购。"
                ),
            }
        )

    stock_analysis = pos_highlights.get("stock_analysis")
    if stock_analysis:
        top_rows = stock_analysis.get("top_rows") or []
        top_labels = "、".join(row["label"] for row in top_rows[:3]) if top_rows else "暂无明显结构"
        cards.append(
            {
                "title": "POS 库存结构",
                "value": top_labels,
                "note": (
                    f"当季库存占比 {format_num(stock_analysis['current_season_inventory_share'] * 100, 1)}%，"
                    f"跨季库存占比 {format_num(stock_analysis['cross_season_inventory_share'] * 100, 1)}%。"
                ),
            }
        )

    movement = pos_highlights.get("movement")
    if movement:
        window_start = movement.get("window_start")
        window_end = movement.get("window_end")
        if pd.notna(window_start) and pd.notna(window_end):
            title = f"近 {max((window_end - window_start).days, 1)} 天出入库"
        else:
            title = "最近出入库"
        cards.append(
            {
                "title": title,
                "value": f"净入库 {format_num(movement['net_qty'])} 件",
                "note": (
                    f"入库 {format_num(movement['inbound_qty'])} 件 / {format_num(movement['inbound_amount'], 2)} 元，"
                    f"出库 {format_num(movement['outbound_qty'])} 件 / {format_num(movement['outbound_amount'], 2)} 元。"
                ),
            }
        )

    daily_flow = pos_highlights.get("daily_flow")
    if daily_flow:
        dominant_payment = daily_flow.get("dominant_payment")
        payment_note = (
            f"{dominant_payment['label']}占比 {format_num(dominant_payment['share'] * 100, 1)}%"
            if dominant_payment
            else "暂无明显主支付方式"
        )
        cards.append(
            {
                "title": "POS 当日流水",
                "value": f"{format_num(daily_flow['actual_money'], 2)} 元",
                "note": (
                    f"{format_num(daily_flow['order_count'])} 单 / {format_num(daily_flow['sales_qty'])} 件，"
                    f"{payment_note}。"
                ),
            }
        )

    category_analysis = pos_highlights.get("category_analysis")
    if category_analysis:
        cards.append(
            {
                "title": "POS 品类结构",
                "value": category_analysis["top_category_names"],
                "note": (
                    f"第一品类贡献 {format_num(category_analysis['top1_share'] * 100, 1)}%，"
                    f"前两品类贡献 {format_num(category_analysis['top2_share'] * 100, 1)}%。"
                ),
            }
        )

    retail_detail = pos_highlights.get("retail_detail")
    if retail_detail:
        cards.append(
            {
                "title": "POS 折扣与尺码",
                "value": f"{format_num(retail_detail['weighted_discount_rate'] * 10, 1)} 折 / {retail_detail['core_size_names']}",
                "note": (
                    f"{retail_detail['discount_category_names']} 折扣依赖偏重，"
                    f"深折扣销售占比约 {format_num(retail_detail['deep_discount_sales_share'] * 100, 1)}%。"
                ),
            }
        )

    vip_analysis = pos_highlights.get("vip_analysis")
    if vip_analysis:
        cards.append(
            {
                "title": "POS 会员基盘",
                "value": f"{format_num(vip_analysis['member_count'])} 人",
                "note": (
                    f"近 60 天活跃 {format_num(vip_analysis['active_recent_count'])} 人，"
                    f"沉默占比约 {format_num(vip_analysis['dormant_ratio'] * 100, 1)}%。"
                ),
            }
        )

    guide_report = pos_highlights.get("guide_report")
    if guide_report:
        cards.append(
            {
                "title": "POS 店员人效",
                "value": guide_report["top_guide_name"],
                "note": (
                    f"销售占比 {format_num(guide_report['top_guide_share'] * 100, 1)}%，"
                    f"VIP 销售占比 {format_num(guide_report['vip_sales_share'] * 100, 1)}%。"
                ),
            }
        )

    return cards


def build_profit_card_defs(profit: dict | None) -> list[tuple[str, str, str, str]]:
    if not profit:
        return []

    breakeven_available = bool(profit.get("breakeven_available"))
    progress_text = (
        "已过保本线"
        if profit["passed_breakeven"]
        else f"还差 {format_num(profit['remaining_sales_to_breakeven'], 2)} 元"
    ) if breakeven_available else "缺少有效毛利率，暂不显示保本进度"
    progress_tone = "green" if profit["passed_breakeven"] else "yellow"
    projection_tone = profit.get("projected_monthly_status", "neutral")
    top_expense = profit.get("top_expense_item") or {}
    top_salary = profit.get("top_salary_item") or {}
    gross_profit_tip = (
        f"销售口径：{profit.get('sales_source', '未标记')}；"
        f"毛利率口径：{profit.get('gross_margin_source', '未标记')}；"
        f"按当前口径估算毛利额 {format_num(profit['gross_profit'], 2)} 元。"
    )
    fixed_cost_tip = (
        f"固定费用来源：{profit.get('operating_expense_source', '当前成本口径')}；"
        f"本月固定费用 {format_num(profit['monthly_operating_expense'], 2)} 元；"
        f"平均每天固定支出约 {format_num(profit['fixed_cost_daily_burden'], 2)} 元。"
    )
    salary_tip = (
        f"当前人工费用按月计 {format_num(profit['salary_total'], 2)} 元；"
        f"平均每天人工成本约 {format_num(profit['salary_daily_burden'], 2)} 元。"
    )
    breakeven_tip = (
        f"公式：总费用 {format_num(profit['total_expense'], 2)} 元 / 毛利率 "
        f"{format_num(profit['gross_margin_rate'] * 100, 1)}% = 保本销售额 "
        f"{format_num(profit['breakeven_sales'], 2)} 元；"
        f"对应保本日销约 {format_num(profit['breakeven_daily_sales'], 2)} 元。"
    ) if breakeven_available else "当前缺少有效毛利率，先按保守口径展示，等补齐毛利率后再精确测算保本线。"
    progress_tip = (
        f"当前销售 {format_num(profit['sales_amount'], 2)} 元；"
        f"保本销售额 {format_num(profit['breakeven_sales'], 2)} 元；"
        f"距离保本还差 {format_num(profit['remaining_sales_to_breakeven'], 2)} 元；"
        f"剩余每天至少要卖 {format_num(profit['remaining_daily_sales_needed'], 2)} 元。"
    ) if breakeven_available else "当前缺少有效毛利率，先不强行给保本进度，避免误导判断。"
    forecast_tip = (
        f"计算过程：已实现销售 {format_num(profit['sales_amount'], 2)} 元；"
        f"当前平均日销 {format_num(profit['average_daily_sales'], 2)} 元；"
        f"剩余 {format_num(profit['remaining_days'], 1)} 天预计新增销售 {format_num(profit['projected_remaining_sales'], 2)} 元；"
        f"月末销售约 {format_num(profit['projected_month_sales'], 2)} 元；"
        f"按毛利率 {format_num(profit['gross_margin_rate'] * 100, 1)}% 预计月末毛利 {format_num(profit['projected_month_gross_profit'], 2)} 元；"
        f"再减总费用 {format_num(profit['total_expense'], 2)} 元，得到月末净利预测 {format_num(profit['projected_month_net_profit'], 2)} 元。"
    )

    return [
        ("净利润", f"{format_num(profit['net_profit'], 2)} 元", profit["headline"], profit["status"]),
        (
            "毛利额",
            f"{format_num(profit['gross_profit'], 2)} 元",
            note_with_tip(
                f"毛利率 {format_num(profit['gross_margin_rate'] * 100, 1)}%",
                gross_profit_tip,
                "口径",
            ),
            "neutral",
        ),
        (
            "固定费用",
            f"{format_num(profit['monthly_operating_expense'], 2)} 元",
            note_with_tip(
                profit.get("operating_expense_source", "当前成本口径") if profit["monthly_operating_expense"] else "当前没有固定费用数据",
                fixed_cost_tip,
                "说明",
            ),
            "neutral",
        ),
        (
            "人工费用",
            f"{format_num(profit['salary_total'], 2)} 元",
            note_with_tip(
                "按当前工资口径" if profit["salary_total"] else "当前没有人工成本数据",
                salary_tip,
                "说明",
            ),
            "neutral",
        ),
        (
            "保本销售额",
            f"{format_num(profit['breakeven_sales'], 2)} 元" if breakeven_available else "待补毛利率",
            note_with_tip(
                f"保本日销约 {format_num(profit['breakeven_daily_sales'], 2)} 元"
                if breakeven_available
                else "先补有效毛利率",
                breakeven_tip,
                "公式",
            ),
            "neutral",
        ),
        (
            "保本进度",
            f"{format_num(min(profit['breakeven_progress_ratio'], 9.99) * 100, 1)}%" if breakeven_available else "待补口径",
            note_with_tip(progress_text, progress_tip, "说明"),
            progress_tone,
        ),
        (
            "月末净利预测",
            f"{format_num(profit['projected_month_net_profit'], 2)} 元",
            note_with_tip(profit["forecast_headline"], forecast_tip, "公式"),
            projection_tone,
        ),
        (
            "最大费用项",
            f"{top_expense.get('name', '未记录')}",
            (
                f"{format_num(float(top_expense.get('amount', 0) or 0), 2)} 元"
                if top_expense
                else "暂无费用明细"
            ),
            "neutral",
        ),
        (
            "最高工资项",
            f"{top_salary.get('name', '未记录')}",
            (
                f"{format_num(float(top_salary.get('amount', 0) or 0), 2)} 元"
                if top_salary
                else "暂无工资明细"
            ),
            "neutral",
        ),
    ]


def build_cost_detail_frames(profit: dict | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not profit:
        return pd.DataFrame(), pd.DataFrame()

    expense_df = pd.DataFrame(profit.get("expense_items") or [])
    salary_df = pd.DataFrame(profit.get("salary_items") or [])
    if not expense_df.empty:
        expense_df = expense_df.copy()
        expense_df["amount"] = expense_df["amount"].apply(lambda value: safe_float(value))
        expense_df = expense_df.sort_values("amount", ascending=False)
    if not salary_df.empty:
        salary_df = salary_df.copy()
        salary_df["amount"] = salary_df["amount"].apply(lambda value: safe_float(value))
        salary_df = salary_df.sort_values("amount", ascending=False)
    return expense_df, salary_df


def build_detail_sections(metrics: dict, reference_intro: str) -> dict[str, str]:
    cards = metrics["summary_cards"]
    actions = metrics["action_summary"]
    charts = build_charts(metrics)
    health_lights = build_health_lights(cards, actions)
    dashboard_tips = build_dashboard_tips(cards, actions)
    time_strategy = build_time_strategy(metrics)
    playbooks = build_operational_playbooks(metrics)
    other_references = metrics["other_references"]

    health_html = "".join(
        f"""
        <div class="health-card health-{item['level']}">
          <div class="health-title">{item['title']}</div>
          <div class="health-value">{item['value']}</div>
          <div class="health-note">{item['note']}</div>
        </div>
        """
        for item in health_lights
    )
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
    playbooks_html = "".join(
        f"""
        <div class="playbook-card playbook-{item['level']}">
          <div class="playbook-title">{item['title']}</div>
          <div class="playbook-trigger">触发原因：{item['trigger']}</div>
          <div class="playbook-goal">目标：{item['goal']}</div>
          <div class="chip-row">
            {"".join(chip_html(scheme['name'], 'soft') for scheme in item['schemes'])}
          </div>
          <ul>
            {"".join(f"<li><strong>{scheme['name']}</strong>：{scheme['detail']}</li>" for scheme in item['schemes'])}
          </ul>
        </div>
        """
        for item in playbooks
    )
    insights_html = render_insights_html(metrics["insights"])
    reference_html = "".join(
        f"""
        <div class="metric-card">
          <div class="metric-title">{title}</div>
          <div class="metric-value">{value}</div>
          <div class="metric-note">{note}</div>
        </div>
        """
        for title, value, note in [
            ("道具销售额", f"{format_num(cards['props_sales_amount'], 2)} 元", "单独参考，不计入经营销售额"),
            ("道具库存额", f"{format_num(cards['props_inventory_amount'], 2)} 元", "单独参考，不计入经营库存额"),
            ("道具销量", format_num(cards["props_sales_qty"]), "单独参考"),
            ("道具库存件数", format_num(cards["props_inventory_qty"]), "单独参考"),
        ]
    )

    overview_panels_html = f"""
      <div class="detail-grid">
        <div class="module detail-module" style="margin:0;">
          <div class="module-header">
            <h3 class="module-title" style="font-size:18px;">经营健康灯</h3>
            <p class="module-note">根据每日数据、整体数据和库存动态自动调整，红色优先处理。</p>
          </div>
          <div class="health-grid">{health_html}</div>
        </div>
        <div class="module detail-module" style="margin:0;">
          <div class="module-header">
            <h3 class="module-title" style="font-size:18px;">北京时间与季节节奏</h3>
            <p class="module-note">今天 / 本周 / 本月的动作建议会根据日销趋势、库存覆盖和换季阶段自动切换。</p>
          </div>
          <ul class="insight-list">{render_time_strategy_html(time_strategy)}</ul>
        </div>
      </div>
      <div class="detail-grid">
        <div class="module detail-module" style="margin:0;">
          <div class="module-header">
            <h3 class="module-title" style="font-size:18px;">道具参考口径</h3>
            <p class="module-note">道具只保留为参考值，不参与主经营判断。</p>
          </div>
          <div class="metrics-grid">{reference_html}</div>
        </div>
        <div class="module detail-module" style="margin:0;">
          <div class="module-header">
            <h3 class="module-title" style="font-size:18px;">自动提炼重点提醒</h3>
            <p class="module-note">根据当天的销售、库存和利润状态生成，适合复盘时快速扫一遍。</p>
          </div>
          <ul class="insight-list">{insights_html}</ul>
        </div>
      </div>
    """

    strategy_panels_html = f"""
      <div class="module detail-module" style="margin:0;">
        <div class="module-header">
          <h3 class="module-title" style="font-size:18px;">自动生成经营方案</h3>
          <p class="module-note">基于日销趋势、整体数据、库存和利润状态自动调整，不是固定文案。</p>
        </div>
        <div class="playbook-grid">{playbooks_html}</div>
      </div>
      <div class="module detail-module" style="margin-top:14px;">
        <div class="module-header">
          <h3 class="module-title" style="font-size:18px;">术语 Tips</h3>
          <p class="module-note">鼠标悬浮或点按标签可看动作词解释；这里是完整词典。</p>
        </div>
        <div class="tip-grid">{tips_html}</div>
      </div>
    """

    replenish_category_table = metrics["replenish_categories"][["中类", "季节策略", "SKU数", "销售额", "库存", "建议补货量", "补货原则", "主销尺码", "控折扣原则", "预算建议"]].copy()
    seasonal_category_table = metrics["seasonal_categories"][["中类", "季节策略", "建议动作", "SKU数", "库存", "销售额"]].copy()
    clearance_category_table = metrics["clearance_categories"][["大类", "建议动作", "SKU数", "实际库存", "近期零售"]].copy()

    replenish_table = metrics["replenish"][["款号", "中类", "颜色", "季节策略", "库存", "周均销量", "库存周数", "销售金额", "建议补货量", "补货原则", "主销尺码", "控折扣原则", "预算建议", "进货顺序", "进货提醒", "建议动作"]].copy()
    seasonal_action_table = metrics["seasonal_actions"][["款号", "中类", "颜色", "季节", "季节策略", "库存", "库存周数", "销售金额", "建议动作"]].copy()
    clearance_cols = ["商品款号", "商品名称", "商品颜色", "大类", "中类", "实际库存", "近期零售", "零售价", "建议动作"]
    clearance_available_cols = [column for column in clearance_cols if column in metrics["clearance"].columns]
    clearance_table = metrics["clearance"][clearance_available_cols].copy()

    if not clearance_table.empty and "商品名称" in clearance_table.columns:
        clearance_table["商品名称"] = clearance_table["商品名称"].apply(lambda value: table_text_with_tip(value, 10, "详情"))
    if not clearance_table.empty and "商品颜色" in clearance_table.columns:
        clearance_table["商品颜色"] = clearance_table["商品颜色"].apply(lambda value: table_text_with_tip(value, 8, "详情"))

    inventory_tables_html = "".join(
        [
            table_html(replenish_category_table, "补货重点品类", 12, "按品类定补货优先级。电脑端适合横向比较，手机端可左右滑动表格。"),
            table_html(seasonal_category_table, "跨季处理重点品类", 12, "先看哪些品类当前不该补，再决定暂缓还是去化。"),
            table_html(clearance_category_table, "去化重点品类", 12, "先看库存压力最大的品类，再安排陈列和促销动作。"),
            table_html(replenish_table, "补货 SKU 明细", 16, "确定品类要补后，再到这里挑具体款。长动作说明已收进标签提示。"),
            table_html(seasonal_action_table, "跨季处理 SKU 明细", 16, "老板二次判断时使用，重点看季节策略、库存和建议动作。"),
            table_html(clearance_table, "去化 SKU 明细", 16, "执行去化时再下钻到具体款，长商品名已收进提示。"),
            table_html(metrics["negative_inventory"], "负库存异常清单", 12, "先查账、查盘点、查调拨。"),
        ]
    )

    people_tables_html = "".join(
        [
            table_html(metrics["top_members"], "高价值会员", 12, "优先回访高消费或高频顾客。"),
            table_html(metrics["guide_perf"], "店员 / 导购表现", 10, "电脑端更适合同屏对比实收金额、票数和连带。"),
            table_html(other_references, "其他店铺参考", 8, reference_intro),
        ]
    )

    download_cards_html = """
      <div class="cards-grid">
        <div class="opportunity-card">
          <div class="card-kicker">主页</div>
          <div class="card-title">返回老板仪表盘</div>
          <p class="table-tip">回到短版首页，快速看今天最该做什么。</p>
          <div class="chip-row">
            <a class="download-link" href="./index.html">返回首页</a>
          </div>
        </div>
        <div class="opportunity-card">
          <div class="card-kicker">HTML</div>
          <div class="card-title">文字摘要</div>
          <p class="table-tip">适合手机快速阅读，也适合转发给店员和群里同步。</p>
          <div class="chip-row">
            <a class="download-link" href="../manuals/dashboard/summary.html">打开 HTML 摘要</a>
            <a class="download-link" href="./summary.md">下载 Markdown</a>
          </div>
        </div>
        <div class="opportunity-card">
          <div class="card-kicker">HTML</div>
          <div class="card-title">分析报告</div>
          <p class="table-tip">适合周复盘时看完整分析，也适合做经营会议材料。</p>
          <div class="chip-row">
            <a class="download-link" href="../manuals/dashboard/report.html">打开 HTML 报告</a>
            <a class="download-link" href="./report.md">下载 Markdown</a>
          </div>
        </div>
        <div class="opportunity-card">
          <div class="card-kicker">CSV</div>
          <div class="card-title">补货 / 去化 / 风险</div>
          <p class="table-tip">需要下钻执行时，再下载 CSV 给店员或表格协作人使用。</p>
          <div class="chip-row">
            <a class="download-link" href="./%E8%A1%A5%E8%B4%A7%E5%BB%BA%E8%AE%AE%E6%B8%85%E5%8D%95.csv">补货 CSV</a>
            <a class="download-link" href="./%E5%8E%BB%E5%8C%96%E5%BB%BA%E8%AE%AE%E6%B8%85%E5%8D%95.csv">去化 CSV</a>
            <a class="download-link" href="./%E5%93%81%E7%B1%BB%E9%A3%8E%E9%99%A9%E6%A6%82%E8%A7%88.csv">风险 CSV</a>
          </div>
        </div>
      </div>
    """

    return {
        "overview_panels_html": overview_panels_html,
        "strategy_panels_html": strategy_panels_html,
        "chart_html": chart_html,
        "inventory_tables_html": inventory_tables_html,
        "people_tables_html": people_tables_html,
        "download_cards_html": download_cards_html,
    }


def build_html(metrics: dict) -> str:
    cards = metrics["summary_cards"]
    profit = cards.get("profit_snapshot")
    pos_highlights = metrics.get("yeusoft_highlights")
    focus = build_today_focus(metrics)
    boss_board = build_boss_action_board(metrics)
    decision = build_decision_engine(metrics)
    time_strategy = build_time_strategy(metrics)

    inventory_days_level = (
        "red" if cards["estimated_inventory_days"] > 180 else "yellow" if cards["estimated_inventory_days"] > 120 else "green"
    )
    core_metrics = [
        ("经营销售额", f"{format_num(cards['sales_amount'], 2)} 元", f"近 {cards['sales_days']} 天经营销售额", "neutral"),
        ("客单价", f"{format_num(cards['avg_order_value'], 2)} 元", "经营销售额 / 订单数", "neutral"),
        ("库存覆盖天数", f"{format_num(cards['estimated_inventory_days'], 1)} 天", "库存还能卖多久", inventory_days_level),
        ("会员销售占比", f"{format_num(cards['member_sales_ratio'] * 100, 1)}%", "会员销售贡献", "neutral"),
    ]

    money_opportunities = (
        metrics["replenish"][metrics["replenish"]["库存周数"] < 1]
        .groupby("中类")
        .agg(销售额=("销售金额", "sum"), 当前库存=("库存", "sum"), 建议补货量=("建议补货量", "sum"))
        .reset_index()
        .sort_values(["销售额", "当前库存"], ascending=[False, True])
        .head(4)
    )
    if money_opportunities.empty:
        money_opportunities = (
            metrics["replenish_categories"][["中类", "销售额", "库存", "建议补货量"]]
            .rename(columns={"库存": "当前库存"})
            .head(4)
        )

    inventory_risks = metrics["clearance_categories"].head(4).copy()
    replenish_focus = (
        metrics["replenish_categories"]
        .sort_values(["SKU数", "销售额", "库存"], ascending=[False, False, True])
        .head(4)
        .copy()
    )
    member_focus = metrics["top_members"].head(3).copy()

    capture_date = pd.Timestamp(cards["data_capture_at"]).strftime("%Y-%m-%d")
    current_strategy = [
        f"当前阶段：{decision['stage']} / {decision['phase']}",
        f"日销趋势：{decision['sales_trend']['label']}",
        f"今日主打法：{decision['mode']}",
        f"季节判断：{time_strategy['headline']}",
    ]
    store_note = f"{cards['store_name']} · 主输入人：{metrics['primary_input']}"
    pos_highlight_cards = build_yeusoft_highlight_cards(pos_highlights)
    profit_card_defs = build_profit_card_defs(profit)
    pos_strip_html = ""
    if pos_highlight_cards:
        strip_summary = "；".join(f"{item['title']}：{item['value']}" for item in pos_highlight_cards[:3])
        strip_note = " ".join(item["note"] for item in pos_highlight_cards[:2])
        pos_strip_html = f"""
      <div class="strip-card">
        <div>
          <strong>POS 高价值数据已接入</strong>
          <p>{html.escape(strip_summary)}。{html.escape(strip_note)}</p>
        </div>
        <a class="strip-link" href="./details.html#overview-section">看 POS 详情</a>
      </div>
        """

    core_metric_html = "".join(
        f"""
        <div class="metric-card metric-{level}">
          <div class="metric-title">{title}</div>
          <div class="metric-value">{value}</div>
          <div class="metric-note">{note}</div>
        </div>
        """
        for title, value, note, level in core_metrics
    )

    profit_cards_html = ""
    if profit:
        profit_metrics_html = "".join(
            f"""
          <div class="metric-card metric-{level}">
            <div class="metric-title">{title}</div>
            <div class="metric-value">{value}</div>
            <div class="metric-note">{note}</div>
          </div>
            """
            for title, value, note, level in profit_card_defs[:7]
        )
        profit_cards_html = f"""
        <div class="submodule-header">
          <h3 class="submodule-title">利润与保本</h3>
          <p class="submodule-note">成本快照已接入。这里不只看赚没赚钱，还看固定费用、人工压力、保本进度和月末预测。</p>
        </div>
        <div class="metrics-grid profit-grid">
          {profit_metrics_html}
        </div>
        """

    money_html = (
        "".join(
            f"""
            <article class="opportunity-card">
              <div class="card-kicker">赚钱机会</div>
              <div class="card-title">{html.escape(str(row['中类']))}</div>
              <div class="stat-row"><span>销售额</span><strong>{format_num(row['销售额'], 2)}</strong></div>
              <div class="stat-row"><span>当前库存</span><strong>{format_num(row['当前库存'])}</strong></div>
              <div class="stat-row"><span>建议补货量</span><strong>{format_num(row['建议补货量'])}</strong></div>
            </article>
            """
            for _, row in money_opportunities.iterrows()
        )
        if not money_opportunities.empty
        else render_empty("当前没有明显的低库存赚钱机会。")
    )

    inventory_risk_html = (
        "".join(
            f"""
            <article class="risk-card">
              <div class="card-title">{html.escape(str(row['大类']))}</div>
              <div class="stat-row"><span>库存数量</span><strong>{format_num(row['实际库存'])}</strong></div>
              <div class="stat-row"><span>近期销量</span><strong>{format_num(row['近期零售'])}</strong></div>
              <div class="chip-row">{''.join(chip_html(item, 'danger') for item in suggestions_for_risk_action(str(row['建议动作'])))}</div>
            </article>
            """
            for _, row in inventory_risks.iterrows()
        )
        if not inventory_risks.empty
        else render_empty("当前没有明显的高库存风险品类。")
    )

    replenish_html = (
        "".join(
            f"""
            <article class="opportunity-card">
              <div class="card-kicker">补货机会</div>
              <div class="card-title">{html.escape(str(row['中类']))}</div>
              <div class="stat-row"><span>销售额</span><strong>{format_num(row['销售额'], 2)}</strong></div>
              <div class="stat-row"><span>库存</span><strong>{format_num(row['库存'])}</strong></div>
              <div class="stat-row"><span>建议补货量</span><strong>{format_num(row['建议补货量'])}</strong></div>
              <div class="card-note">建议补货 SKU：{format_num(row['SKU数'])}</div>
            </article>
            """
            for _, row in replenish_focus.iterrows()
        )
        if not replenish_focus.empty
        else render_empty("当前没有需要优先补货的品类。")
    )

    member_html = (
        "".join(
            f"""
            <article class="member-card">
              <div class="card-title">{html.escape(str(row['VIP姓名']))}</div>
              <div class="card-note">服务导购：{html.escape(str(row['服务导购']))}</div>
              <div class="stat-row"><span>购买金额</span><strong>{format_num(row['购买金额'], 2)}</strong></div>
              <div class="stat-row"><span>消费次数</span><strong>{format_num(row['消费次数/年'])}</strong></div>
              <div class="stat-row"><span>平均客单价</span><strong>{format_num(row['平均单笔消费额'], 2)}</strong></div>
            </article>
            """
            for _, row in member_focus.iterrows()
        )
        if not member_focus.empty
        else render_empty("当前没有可展示的高价值会员。")
    )

    conclusions_html = "".join(chip_html(item, "primary") for item in focus["conclusions"])
    tasks_html = "".join(f"<li>{chip_html(item, 'soft')}</li>" for item in focus["tasks"])
    dont_do_html = "".join(f"<li>{chip_html(item, 'warn')}</li>" for item in boss_board["dont_do"])
    strategy_summary_html = "".join(f"<li>{html.escape(item)}</li>" for item in current_strategy)
    action_today_html = "".join(
        f"""
        <li>
          <strong>{html.escape(item['title'])}</strong>
          <span>{html.escape(item['body'])}</span>
        </li>
        """
        for item in boss_board["actions_today"]
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{cards['store_name']} 老板经营仪表盘</title>
  <style>
    html, body {{
      max-width: 100%;
      overflow-x: hidden;
    }}
    * {{
      box-sizing: border-box;
    }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: #f6f7fb;
      color: #1f2937;
    }}
    .page {{
      max-width: 1320px;
      margin: 0 auto;
      padding: 24px;
    }}
    .top-nav {{
      position: sticky;
      top: 0;
      z-index: 50;
      margin-bottom: 18px;
      background: rgba(246, 247, 251, 0.92);
      backdrop-filter: blur(14px);
      border: 1px solid rgba(148, 163, 184, 0.18);
      border-radius: 18px;
      box-shadow: 0 10px 24px rgba(15, 23, 42, 0.08);
    }}
    .top-nav-links {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      padding: 12px;
    }}
    .top-nav-link {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: 999px;
      padding: 9px 14px;
      font-size: 13px;
      font-weight: 800;
      color: #334155;
      background: #ffffff;
      border: 1px solid #dbe4f0;
      text-decoration: none;
    }}
    .top-nav-link.is-active {{
      background: #dbeafe;
      color: #1d4ed8;
      border-color: #bfdbfe;
    }}
    .page-shell {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 250px;
      gap: 18px;
    }}
    .main-column {{
      min-width: 0;
    }}
    .side-rail {{
      display: flex;
      flex-direction: column;
      gap: 16px;
      align-self: start;
    }}
    .rail-card {{
      position: sticky;
      top: 88px;
      background: #fff;
      border-radius: 18px;
      padding: 16px;
      box-shadow: 0 10px 30px rgba(15, 23, 42, 0.08);
    }}
    .rail-card h3 {{
      margin: 0 0 8px;
      font-size: 17px;
      color: #0f172a;
    }}
    .rail-card p {{
      margin: 0 0 12px;
      font-size: 12px;
      line-height: 1.8;
      color: #64748b;
    }}
    .rail-links {{
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}
    .rail-links a {{
      display: block;
      text-decoration: none;
      color: #334155;
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 14px;
      padding: 10px 12px;
      font-size: 13px;
      font-weight: 700;
    }}
    .rail-links a.current {{
      background: #dbeafe;
      border-color: #bfdbfe;
      color: #1d4ed8;
    }}
    .hero {{
      background: linear-gradient(135deg, #0f172a 0%, #1d4ed8 100%);
      color: white;
      padding: 24px;
      border-radius: 22px;
      margin-bottom: 18px;
      box-shadow: 0 18px 48px rgba(15, 23, 42, 0.18);
    }}
    .hero h1 {{
      margin: 0 0 10px;
      font-size: 30px;
      line-height: 1.25;
    }}
    .hero p {{
      margin: 0;
      opacity: 0.94;
      line-height: 1.8;
    }}
    .hero-note {{
      margin-top: 12px;
      font-size: 13px;
      opacity: 0.9;
    }}
    .hero-status {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 12px;
    }}
    .hero-status-chip {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      background: rgba(255, 255, 255, 0.12);
      border: 1px solid rgba(255, 255, 255, 0.2);
      color: #ffffff;
      border-radius: 999px;
      padding: 8px 12px;
      font-size: 12px;
      font-weight: 700;
      line-height: 1.5;
    }}
    .action-strip {{
      margin-bottom: 18px;
      background: linear-gradient(135deg, #fff7ed 0%, #fffbeb 100%);
      border: 1px solid #fed7aa;
    }}
    .action-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
      margin-top: 16px;
    }}
    .action-card {{
      background: #ffffff;
      border: 1px solid #fde68a;
      border-radius: 18px;
      padding: 16px;
      box-shadow: 0 10px 24px rgba(245, 158, 11, 0.08);
    }}
    .action-kicker {{
      font-size: 12px;
      font-weight: 800;
      color: #b45309;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      margin-bottom: 8px;
    }}
    .action-title {{
      margin: 0 0 8px;
      font-size: 20px;
      color: #0f172a;
    }}
    .action-text {{
      margin: 0 0 12px;
      font-size: 13px;
      line-height: 1.8;
      color: #475569;
    }}
    .action-link {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: 999px;
      padding: 10px 14px;
      text-decoration: none;
      font-size: 13px;
      font-weight: 800;
      background: #1d4ed8;
      color: #ffffff;
    }}
    .quick-nav {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin: 12px 0 18px;
    }}
    .quick-nav a {{
      text-decoration: none;
      color: #1d4ed8;
      background: #eff6ff;
      border: 1px solid #bfdbfe;
      padding: 8px 12px;
      border-radius: 999px;
      font-size: 13px;
      font-weight: 700;
      white-space: nowrap;
    }}
    .module {{
      background: white;
      border-radius: 18px;
      box-shadow: 0 10px 30px rgba(15, 23, 42, 0.08);
      padding: 18px;
      margin-bottom: 18px;
    }}
    .module-header {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
      margin-bottom: 14px;
      flex-wrap: wrap;
    }}
    .module-title {{
      margin: 0;
      font-size: 22px;
      color: #0f172a;
    }}
    .module-note {{
      margin: 0;
      font-size: 13px;
      color: #64748b;
      line-height: 1.8;
    }}
    .detail-link {{
      text-decoration: none;
      color: white;
      background: #1d4ed8;
      border-radius: 999px;
      padding: 10px 14px;
      font-size: 13px;
      font-weight: 800;
      box-shadow: 0 8px 18px rgba(29, 78, 216, 0.22);
    }}
    .focus-wrap {{
      display: grid;
      grid-template-columns: 1.2fr 1fr;
      gap: 16px;
    }}
    .focus-panel {{
      background: #fffdf7;
      border: 1px solid #fde68a;
      border-radius: 16px;
      padding: 16px;
    }}
    .focus-headline {{
      font-size: 28px;
      font-weight: 800;
      color: #92400e;
      margin: 0 0 10px;
      line-height: 1.35;
    }}
    .focus-summary {{
      margin: 0;
      font-size: 14px;
      line-height: 1.8;
      color: #5b4636;
    }}
    .submodule-header {{
      margin: 18px 0 10px;
    }}
    .submodule-title {{
      margin: 0 0 6px;
      font-size: 18px;
      color: #0f172a;
    }}
    .submodule-note {{
      margin: 0;
      font-size: 13px;
      color: #64748b;
      line-height: 1.8;
    }}
    .chip-row {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 12px;
    }}
    .mini-chip {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 6px 12px;
      font-size: 13px;
      font-weight: 700;
      white-space: nowrap;
    }}
    .mini-chip-primary {{
      background: #dbeafe;
      color: #1d4ed8;
    }}
    .mini-chip-soft {{
      background: #f1f5f9;
      color: #334155;
    }}
    .mini-chip-danger {{
      background: #fee2e2;
      color: #991b1b;
    }}
    .mini-chip-warn {{
      background: #fef3c7;
      color: #92400e;
    }}
    .tooltip-badge {{
      position: relative;
      cursor: help;
    }}
    .tooltip-badge::after {{
      content: attr(data-tip);
      position: absolute;
      left: 0;
      bottom: calc(100% + 10px);
      width: min(320px, 68vw);
      white-space: normal;
      background: #0f172a;
      color: #ffffff;
      border-radius: 12px;
      padding: 10px 12px;
      line-height: 1.6;
      font-size: 12px;
      font-weight: 500;
      box-shadow: 0 12px 24px rgba(15, 23, 42, 0.2);
      opacity: 0;
      pointer-events: none;
      transform: translateY(6px);
      transition: opacity 0.18s ease, transform 0.18s ease;
      z-index: 40;
    }}
    .tooltip-badge::before {{
      content: "";
      position: absolute;
      left: 14px;
      bottom: calc(100% + 4px);
      width: 10px;
      height: 10px;
      background: #0f172a;
      transform: rotate(45deg);
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.18s ease, transform 0.18s ease;
      z-index: 39;
    }}
    .tooltip-badge:hover::after,
    .tooltip-badge:hover::before,
    .tooltip-badge:focus-visible::after,
    .tooltip-badge:focus-visible::before {{
      opacity: 1;
      transform: translateY(0);
    }}
    .tooltip-badge:focus-visible {{
      outline: 2px solid #93c5fd;
      outline-offset: 2px;
    }}
    .focus-list, .task-list {{
      margin: 10px 0 0 18px;
      padding: 0;
      line-height: 1.9;
      color: #334155;
      font-size: 14px;
    }}
    .task-list li + li,
    .focus-list li + li {{
      margin-top: 4px;
    }}
    .task-list strong {{
      display: block;
      color: #0f172a;
      margin-bottom: 4px;
    }}
    .metrics-grid, .cards-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
    }}
    .metric-card, .opportunity-card, .risk-card, .member-card {{
      background: #ffffff;
      border-radius: 16px;
      border: 1px solid #e2e8f0;
      padding: 16px;
      min-width: 0;
    }}
    .metric-card {{
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
    }}
    .metric-title {{
      font-size: 14px;
      color: #64748b;
      margin-bottom: 8px;
    }}
    .metric-value {{
      font-size: 30px;
      font-weight: 800;
      margin-bottom: 6px;
      color: #0f172a;
    }}
    .metric-note {{
      font-size: 13px;
      color: #64748b;
      line-height: 1.7;
    }}
    .inline-tip {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      margin-left: 6px;
      padding: 1px 8px;
      border-radius: 999px;
      border: 1px solid #bfdbfe;
      background: #eff6ff;
      color: #1d4ed8;
      font-size: 11px;
      font-weight: 800;
      line-height: 1.6;
      vertical-align: middle;
      white-space: nowrap;
    }}
    .metric-red {{
      border-color: #fecaca;
      background: #fff7f7;
    }}
    .metric-red .metric-value {{
      color: #991b1b;
    }}
    .metric-yellow {{
      border-color: #fde68a;
      background: #fffbeb;
    }}
    .metric-yellow .metric-value {{
      color: #92400e;
    }}
    .metric-green {{
      border-color: #bbf7d0;
      background: #f0fdf4;
    }}
    .metric-green .metric-value {{
      color: #166534;
    }}
    .card-kicker {{
      font-size: 12px;
      font-weight: 700;
      color: #64748b;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      margin-bottom: 6px;
    }}
    .card-title {{
      font-size: 18px;
      font-weight: 800;
      color: #0f172a;
      margin-bottom: 12px;
      line-height: 1.4;
      word-break: break-word;
    }}
    .card-note {{
      font-size: 12px;
      color: #64748b;
      margin-top: 10px;
      line-height: 1.7;
    }}
    .stat-row {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      font-size: 14px;
      line-height: 1.8;
      color: #475569;
    }}
    .stat-row strong {{
      color: #0f172a;
      font-size: 15px;
    }}
    .risk-card {{
      background: #fff8f5;
      border-color: #fed7aa;
    }}
    .member-card {{
      background: #f8fafc;
    }}
    .strip-card {{
      margin-top: 14px;
      border: 1px solid #dbeafe;
      background: #eff6ff;
      border-radius: 16px;
      padding: 14px 16px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 14px;
      flex-wrap: wrap;
    }}
    .strip-card strong {{
      color: #0f172a;
      font-size: 16px;
      display: block;
      margin-bottom: 4px;
    }}
    .strip-card p {{
      margin: 0;
      color: #475569;
      font-size: 13px;
      line-height: 1.7;
    }}
    .strip-link {{
      text-decoration: none;
      color: #1d4ed8;
      font-weight: 800;
      font-size: 13px;
      white-space: nowrap;
    }}
    .empty-card {{
      border: 1px dashed #cbd5e1;
      border-radius: 16px;
      padding: 20px;
      color: #64748b;
      background: #f8fafc;
      font-size: 14px;
      line-height: 1.8;
    }}
    @media (max-width: 960px) {{
      .page {{
        padding: 16px;
      }}
      .page-shell {{
        grid-template-columns: 1fr;
      }}
      .rail-card {{
        position: static;
      }}
      .rail-links {{
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
      .focus-wrap {{
        grid-template-columns: 1fr;
      }}
      .module-header {{
        flex-direction: column;
        align-items: flex-start;
      }}
      .metrics-grid, .cards-grid {{
        grid-template-columns: 1fr;
      }}
    }}
    @media (max-width: 640px) {{
      .page {{
        padding: 12px;
      }}
      .top-nav-links {{
        width: 100%;
      }}
      .top-nav-link {{
        width: 100%;
      }}
      .hero {{
        padding: 18px;
        border-radius: 16px;
      }}
      .hero h1 {{
        font-size: 24px;
      }}
      .hero p,
      .hero-note,
      .module-note,
      .focus-summary,
      .metric-note,
      .card-note,
      .task-list,
      .focus-list {{
        font-size: 12px;
        line-height: 1.75;
      }}
      .hero-status-chip {{
        width: 100%;
      }}
      .quick-nav {{
        flex-wrap: nowrap;
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
        padding-bottom: 2px;
      }}
      .module {{
        padding: 14px;
        border-radius: 16px;
        margin-bottom: 14px;
      }}
      .focus-headline {{
        font-size: 22px;
      }}
      .metric-value {{
        font-size: 24px;
      }}
      .mini-chip {{
        font-size: 12px;
        padding: 6px 10px;
        white-space: normal;
      }}
      .rail-links {{
        grid-template-columns: 1fr;
      }}
      .card-title {{
        font-size: 16px;
      }}
      .stat-row {{
        font-size: 13px;
      }}
      .stat-row strong {{
        font-size: 14px;
      }}
      .strip-card {{
        align-items: flex-start;
      }}
    }}
  {floating_tooltip_css()}
  </style>
</head>
<body>
  <div class="page">
    <nav class="top-nav">
      <div class="top-nav-links">
        <a class="top-nav-link" href="../index.html">首页</a>
        <a class="top-nav-link is-active" href="./index.html">仪表盘</a>
        <a class="top-nav-link" href="./details.html">详细页</a>
        <a class="top-nav-link" href="./relationship.html">库存销售关系页</a>
        <a class="top-nav-link" href="./monthly.html">月度页</a>
        <a class="top-nav-link" href="./quarterly.html">季度页</a>
        <a class="top-nav-link" href="../manuals/index.html">文档中心</a>
        <a class="top-nav-link" href="../costs/index.html">成本维护台</a>
      </div>
    </nav>
    <section class="hero">
      <h1>{cards['store_name']} 老板经营仪表盘</h1>
      <p>首页只保留老板 10 秒内最该知道的事情。总览、经营策略、图表和明细已经拆到详细页，首页更适合每天快速拍板。</p>
      <div class="hero-note">{store_note} · 当前季节：{time_strategy['season']} / {time_strategy['phase']} · 当前阶段：{decision['stage']} · 日销趋势：{decision['sales_trend']['label']}</div>
      <div class="hero-status">
        <div class="hero-status-chip">最近抓取日期：{capture_date}（北京时间）</div>
        <div class="hero-status-chip">数据导入日期：{capture_date}（北京时间）</div>
      </div>
    </section>

    <section class="module action-strip">
      <div class="module-header">
        <h2 class="module-title">老板娘最常用 3 步</h2>
        <p class="module-note">如果今天只做最常用的动作，先点这 3 个，不用在模块里慢慢找。</p>
      </div>
      <div class="action-grid">
        <article class="action-card">
          <div class="action-kicker">第 1 步</div>
          <h3 class="action-title">回首页</h3>
          <p class="action-text">如果要重新选入口、打开文档中心，或者让别人从最清楚的地方开始，就先回首页。</p>
          <a class="action-link" href="../index.html">直接回首页</a>
        </article>
        <article class="action-card">
          <div class="action-kicker">第 2 步</div>
          <h3 class="action-title">看详细页</h3>
          <p class="action-text">如果你已经看完首页结论，下一步通常就是去详细页看总览、经营策略和补货去化明细。</p>
          <a class="action-link" href="./details.html">直接看详细页</a>
          <a class="action-link" href="./relationship.html">专门看库存和销售关系</a>
        </article>
        <article class="action-card">
          <div class="action-kicker">第 3 步</div>
          <h3 class="action-title">一键同步</h3>
          <p class="action-text">如果店里电脑已经开了本地服务，回首页同步区直接一键抓取，就能刷新今天最新报表。</p>
          <a class="action-link" href="../index.html#local-console">去同步区</a>
        </article>
      </div>
    </section>

    <div class="page-shell">
      <div class="main-column">
    <nav class="quick-nav">
      <a href="#focus">今日重点</a>
      <a href="#core-metrics">核心指标</a>
      <a href="#money-opportunities">赚钱机会</a>
      <a href="#inventory-risks">库存风险</a>
      <a href="#replenish-opportunities">补货机会</a>
      <a href="#member-ops">会员经营</a>
    </nav>

    <section class="module" id="focus">
      <div class="module-header">
        <h2 class="module-title">1. 今日经营重点</h2>
        <a class="detail-link" href="./details.html">查看详细数据与图表</a>
        <a class="detail-link" href="./relationship.html">查看库存和销售关系页</a>
      </div>
      <div class="focus-wrap">
        <div class="focus-panel">
          <div class="focus-headline">{boss_board['headline']}</div>
          <p class="focus-summary">{boss_board['summary']}</p>
          <div class="chip-row">{conclusions_html}</div>
          <ul class="focus-list">{strategy_summary_html}</ul>
        </div>
        <div class="focus-panel">
          <div class="submodule-header">
            <h3 class="submodule-title">今日执行任务</h3>
            <p class="submodule-note">先把今天要做的事排清楚，再让店员按顺序执行。</p>
          </div>
          <ul class="task-list">{tasks_html}</ul>
          <div class="submodule-header">
            <h3 class="submodule-title">今天先别做</h3>
          </div>
          <ul class="focus-list">{dont_do_html}</ul>
        </div>
      </div>
      <div class="strip-card">
        <div>
          <strong>总览和经营策略已移到详细页顶部</strong>
          <p>详细页会根据每日销售、整体销售、库存动态和利润保本状态自动刷新，更适合复盘和细看。</p>
        </div>
        <a class="strip-link" href="./details.html#overview-section">打开详细页</a>
      </div>
      {pos_strip_html}
    </section>

    <section class="module" id="core-metrics">
      <div class="module-header">
        <h2 class="module-title">2. 核心经营指标</h2>
        <p class="module-note">先看这 4 个数字，再判断今天是去库存、保畅销，还是冲保本线。</p>
      </div>
      <div class="metrics-grid">{core_metric_html}</div>
      {profit_cards_html}
    </section>

    <section class="module" id="money-opportunities">
      <div class="module-header">
        <h2 class="module-title">3. 赚钱机会</h2>
        <p class="module-note">优先找卖得快但库存浅的品类，先保不断货，再谈放大销售额。</p>
      </div>
      <div class="cards-grid">{money_html}</div>
    </section>

    <section class="module" id="inventory-risks">
      <div class="module-header">
        <h2 class="module-title">4. 库存风险</h2>
        <p class="module-note">这里看库存压力最大的品类。先停补、再去化、再调陈列。</p>
      </div>
      <div class="cards-grid">{inventory_risk_html}</div>
    </section>

    <section class="module" id="replenish-opportunities">
      <div class="module-header">
        <h2 class="module-title">5. 补货机会</h2>
        <p class="module-note">这里只显示最值得优先补的品类。具体款号、颜色和尺码，去详细页再下钻。</p>
      </div>
      <div class="cards-grid">{replenish_html}</div>
    </section>

    <section class="module" id="member-ops">
      <div class="module-header">
        <h2 class="module-title">6. 会员经营</h2>
        <p class="module-note">高价值会员适合优先回访。详细页里会有更完整的会员、店员和参考店信息。</p>
      </div>
      <div class="cards-grid">{member_html}</div>
      <div class="strip-card">
        <div>
          <strong>详细页包含总览、经营策略、图表、补货去化、会员店员和下载区</strong>
          <p>首页用于每天拍板，详细页用于复盘、解释和交给店员执行。</p>
        </div>
        <a class="strip-link" href="./details.html">去详细页</a>
      </div>
    </section>

    <section class="module">
      <div class="module-header">
        <h2 class="module-title">老板拍板参考</h2>
        <p class="module-note">这组话术更适合晨会或微信里直接发给店员。</p>
      </div>
      <ul class="task-list">{action_today_html}</ul>
    </section>
      </div>
      <aside class="side-rail">
        <section class="rail-card">
          <h3>常用导航</h3>
          <p>老板每天最常用的入口都固定在这里，不用回头找按钮。</p>
          <div class="rail-links">
            <a href="../index.html">返回首页</a>
            <a class="current" href="./index.html">当前仪表盘</a>
            <a href="./details.html">进入详细页</a>
            <a href="./relationship.html">进入关系页</a>
            <a href="./monthly.html">进入月度页</a>
            <a href="./quarterly.html">进入季度页</a>
            <a href="../manuals/index.html">进入文档中心</a>
            <a href="../costs/index.html">进入成本维护台</a>
          </div>
        </section>
        <section class="rail-card">
          <h3>本页定位</h3>
          <p>如果只想快速跳到某一块，直接点右边，不用整页来回找。</p>
          <div class="rail-links">
            <a href="#focus">今日重点</a>
            <a href="#core-metrics">核心指标</a>
            <a href="#money-opportunities">赚钱机会</a>
            <a href="#inventory-risks">库存风险</a>
            <a href="#replenish-opportunities">补货机会</a>
            <a href="#member-ops">会员经营</a>
          </div>
        </section>
      </aside>
    </div>
  </div>
{floating_tooltip_script()}
</body>
</html>
"""


def build_detail_html(metrics: dict) -> str:
    cards = metrics["summary_cards"]
    profit = cards.get("profit_snapshot")
    pos_highlights = metrics.get("yeusoft_highlights")
    charts = build_charts(metrics)
    actions = metrics["action_summary"]
    health_lights = build_health_lights(cards, actions)
    dashboard_tips = build_dashboard_tips(cards, actions)
    time_strategy = build_time_strategy(metrics)
    playbooks = build_operational_playbooks(metrics)
    boss_board = build_boss_action_board(metrics)
    focus = build_today_focus(metrics)
    decision = build_decision_engine(metrics)
    consulting_analysis = build_retail_consulting_analysis(metrics)
    profit_card_defs = build_profit_card_defs(profit)
    primary_reference = metrics["primary_reference"]
    other_references = metrics["other_references"]

    def chip(label: str, tone: str = "neutral") -> str:
        return chip_html(label, tone)

    inventory_days_level = (
        "red" if cards["estimated_inventory_days"] > 180 else "yellow" if cards["estimated_inventory_days"] > 120 else "green"
    )
    core_metrics = [
        ("经营销售额", f"{format_num(cards['sales_amount'], 2)} 元", f"近 {cards['sales_days']} 天经营数据", "neutral"),
        ("客单价", f"{format_num(cards['avg_order_value'], 2)} 元", "经营销售额 / 订单数", "neutral"),
        ("库存覆盖天数", f"{format_num(cards['estimated_inventory_days'], 1)} 天", "库存还能卖多久", inventory_days_level),
        ("会员销售占比", f"{format_num(cards['member_sales_ratio'] * 100, 1)}%", "会员带来的销售贡献", "neutral"),
    ]

    money_opportunities = (
        metrics["replenish"][metrics["replenish"]["库存周数"] < 1]
        .groupby("中类")
        .agg(销售额=("销售金额", "sum"), 当前库存=("库存", "sum"), 建议补货量=("建议补货量", "sum"))
        .reset_index()
        .sort_values(["销售额", "当前库存"], ascending=[False, True])
        .head(4)
    )
    if money_opportunities.empty:
        money_opportunities = (
            metrics["replenish_categories"][["中类", "销售额", "库存", "建议补货量"]]
            .rename(columns={"库存": "当前库存"})
            .head(4)
        )

    inventory_risks = metrics["clearance_categories"].head(4).copy()
    replenish_focus = (
        metrics["replenish_categories"]
        .sort_values(["SKU数", "销售额", "库存"], ascending=[False, False, True])
        .head(4)
        .copy()
    )
    member_focus = metrics["top_members"].head(3).copy()

    if not primary_reference.empty:
        primary = primary_reference.iloc[0]
        store_note = f"主店铺：{metrics['primary_input']} / {primary['店铺名称']}"
        reference_intro = (
            f"主逻辑固定关注 {metrics['primary_input']} / {primary['店铺名称']}。"
            "下面其他输入人代表其他店铺，只做参考对比，不参与主经营结论。"
        )
    else:
        store_note = f"主店铺：{cards['store_name']}"
        reference_intro = "未读取到可用的输入人参考表。"
    capture_date = pd.Timestamp(cards["data_capture_at"]).strftime("%Y-%m-%d")

    profit_cards_html = ""
    if profit:
        profit_metrics_html = "".join(
            f"""
          <div class="metric-card metric-{level}">
            <div class="metric-title">{title}</div>
            <div class="metric-value">{value}</div>
            <div class="metric-note">{note}</div>
          </div>
            """
            for title, value, note, level in profit_card_defs
        )
        profit_cards_html = f"""
        <div class="submodule-header">
          <h3 class="submodule-title">利润与保本</h3>
          <p class="submodule-note">按你维护的成本快照计算。这里把固定费用、人工费用、保本进度和月末净利预测一起拉进来。</p>
        </div>
        <div class="metrics-grid profit-grid">
          {profit_metrics_html}
        </div>
        """

    core_metric_html = "".join(
        f"""
        <div class="metric-card metric-{level}">
          <div class="metric-title">{title}</div>
          <div class="metric-value">{value}</div>
          <div class="metric-note">{note}</div>
        </div>
        """
        for title, value, note, level in core_metrics
    )

    conclusions_html = "".join(chip(item, "primary") for item in focus["conclusions"])
    tasks_html = "".join(
        f"<li>{chip(item, 'soft')}</li>" for item in focus["tasks"]
    )
    dont_do_html = "".join(f"<li>{chip(item, 'warn')}</li>" for item in boss_board["dont_do"])
    quick_nav_html = "".join(
        [
            "<a href='#focus'>今日重点</a>",
            "<a href='#core-metrics'>核心指标</a>",
            "<a href='#money-opportunities'>赚钱机会</a>",
            "<a href='#inventory-risks'>库存风险</a>",
            "<a href='#replenish-opportunities'>补货机会</a>",
            "<a href='#member-ops'>会员经营</a>",
            "<a href='#details'>详细数据</a>",
        ]
    )
    detail_nav_items = [
        ("detail-overview", "总览", "健康灯 / 季节 / 提醒"),
        ("detail-strategy", "经营策略", "方案 / 术语"),
        ("detail-charts", "图表", "趋势 / 结构"),
        ("detail-inventory", "补货去化", "品类 / SKU / 异常"),
        ("detail-people", "会员店员", "会员 / 导购 / 参考店"),
        ("detail-downloads", "下载", "摘要 / 报告 / CSV"),
    ]
    detail_nav_html = "".join(
        f"""
        <button type="button" class="detail-nav-btn{' is-active' if index == 0 else ''}" data-detail-target="{item_id}">
          <span class="detail-nav-label">{label}</span>
          <span class="detail-nav-note">{note}</span>
        </button>
        """
        for index, (item_id, label, note) in enumerate(detail_nav_items)
    )

    if not money_opportunities.empty:
        money_html = "".join(
            f"""
            <div class="opportunity-card">
              <div class="card-kicker">赚钱机会</div>
              <div class="card-title">{html.escape(str(row['中类']))}</div>
              <div class="stat-row"><span>销售额</span><strong>{format_num(row['销售额'], 2)}</strong></div>
              <div class="stat-row"><span>当前库存</span><strong>{format_num(row['当前库存'])}</strong></div>
              <div class="stat-row"><span>建议补货量</span><strong>{format_num(row['建议补货量'])}</strong></div>
            </div>
            """
            for _, row in money_opportunities.iterrows()
        )
    else:
        money_html = render_empty("当前没有明显的低库存赚钱机会。")

    if not inventory_risks.empty:
        inventory_risk_html = "".join(
            f"""
            <div class="risk-card">
              <div class="card-title">{html.escape(str(row['大类']))}</div>
              <div class="stat-row"><span>库存数量</span><strong>{format_num(row['实际库存'])}</strong></div>
              <div class="stat-row"><span>近期销量</span><strong>{format_num(row['近期零售'])}</strong></div>
              <div class="chip-row">{''.join(chip(item, 'danger') for item in suggestions_for_risk_action(str(row['建议动作'])))}</div>
            </div>
            """
            for _, row in inventory_risks.iterrows()
        )
    else:
        inventory_risk_html = render_empty("当前没有明显的高库存风险品类。")

    if not replenish_focus.empty:
        replenish_html = "".join(
            f"""
            <div class="opportunity-card">
              <div class="card-kicker">补货机会</div>
              <div class="card-title">{html.escape(str(row['中类']))}</div>
              <div class="stat-row"><span>销售额</span><strong>{format_num(row['销售额'], 2)}</strong></div>
              <div class="stat-row"><span>库存</span><strong>{format_num(row['库存'])}</strong></div>
              <div class="stat-row"><span>建议补货量</span><strong>{format_num(row['建议补货量'])}</strong></div>
              <div class="card-note">建议补货 SKU：{format_num(row['SKU数'])}</div>
            </div>
            """
            for _, row in replenish_focus.iterrows()
        )
    else:
        replenish_html = render_empty("当前没有明显需要优先补货的品类。")

    if not member_focus.empty:
        member_html = "".join(
            f"""
            <div class="member-card">
              <div class="card-title">{html.escape(str(row['VIP姓名']))}</div>
              <div class="card-note">服务导购：{html.escape(str(row['服务导购']))}</div>
              <div class="stat-row"><span>购买金额</span><strong>{format_num(row['购买金额'], 2)}</strong></div>
              <div class="stat-row"><span>消费次数</span><strong>{format_num(row['消费次数/年'])}</strong></div>
              <div class="stat-row"><span>平均客单价</span><strong>{format_num(row['平均单笔消费额'], 2)}</strong></div>
            </div>
            """
            for _, row in member_focus.iterrows()
        )
    else:
        member_html = render_empty("当前没有可展示的高价值会员。")

    health_html = "".join(
        f"""
        <div class="health-card health-{item['level']}">
          <div class="health-title">{item['title']}</div>
          <div class="health-value">{item['value']}</div>
          <div class="health-note">{item['note']}</div>
        </div>
        """
        for item in health_lights
    )
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
    playbooks_html = "".join(
        f"""
        <div class="playbook-card playbook-{item['level']}">
          <div class="playbook-title">{item['title']}</div>
          <div class="playbook-trigger">触发原因：{item['trigger']}</div>
          <div class="playbook-goal">目标：{item['goal']}</div>
          <div class="chip-row">
            {"".join(chip(scheme['name'], 'soft') for scheme in item['schemes'])}
          </div>
          <ul>
            {"".join(f"<li><strong>{scheme['name']}</strong>：{scheme['detail']}</li>" for scheme in item['schemes'])}
          </ul>
        </div>
        """
        for item in playbooks
    )
    insights_html = render_insights_html(metrics["insights"])
    chart_html = "".join(f"<section class='chart-card'>{chart}</section>" for chart in charts)
    pos_cards = build_yeusoft_highlight_cards(pos_highlights)
    expense_df, salary_df = build_cost_detail_frames(profit)
    pos_overview_html = ""
    if pos_cards:
        pos_overview_html = "".join(
            f"""
            <div class="metric-card">
              <div class="metric-title">{html.escape(item['title'])}</div>
              <div class="metric-value" style="font-size:24px;">{html.escape(item['value'])}</div>
              <div class="metric-note">{html.escape(item['note'])}</div>
            </div>
            """
            for item in pos_cards
        )
    cost_breakdown_html = ""
    if profit:
        expense_table = pd.DataFrame()
        salary_table = pd.DataFrame()
        if not expense_df.empty:
            expense_table = expense_df.copy()
            expense_table["金额"] = expense_table["amount"].apply(lambda value: f"{format_num(value, 2)} 元")
            expense_table["说明"] = expense_table["note"].apply(
                lambda value: table_text_with_tip(value, 12, "说明") if value else "-"
            )
            expense_table = expense_table[["name", "金额", "说明"]].rename(columns={"name": "费用项"})
        if not salary_df.empty:
            salary_table = salary_df.copy()
            salary_table["金额"] = salary_table["amount"].apply(lambda value: f"{format_num(value, 2)} 元")
            salary_table["说明"] = salary_table["note"].apply(
                lambda value: table_text_with_tip(value, 12, "说明") if value else "-"
            )
            salary_table = salary_table[["name", "金额", "说明"]].rename(columns={"name": "工资项"})
        props_table = pd.DataFrame(
            [
                {"参考项": "道具销售额", "数值": f"{format_num(cards['props_sales_amount'], 2)} 元", "说明": "单独参考，不计入经营销售额"},
                {"参考项": "道具库存额", "数值": f"{format_num(cards['props_inventory_amount'], 2)} 元", "说明": "单独参考，不计入经营库存额"},
                {"参考项": "道具销量", "数值": format_num(cards["props_sales_qty"]), "说明": "只作参考"},
                {"参考项": "道具库存件数", "数值": format_num(cards["props_inventory_qty"]), "说明": "只作参考"},
            ]
        )
        cost_tables_html = "".join(
            [
                table_html(
                    expense_table,
                    "固定费用拆解",
                    20,
                    "按月固定费用或分摊费用展示，默认收起，真正核利润时再展开。",
                )
                if not expense_table.empty
                else render_empty("当前没有固定费用明细。"),
                table_html(
                    salary_table,
                    "工资拆解",
                    20,
                    "工资当前按固定口径维护，默认收起，需要核人工成本时再看。",
                )
                if not salary_table.empty
                else render_empty("当前没有工资明细。"),
                table_html(
                    props_table,
                    "道具参考口径",
                    10,
                    "道具继续保留，但并入折叠区，避免占用总览长度。它只作参考，不参与主经营判断。",
                ),
            ]
        )
        cost_breakdown_html = f"""
        <details class="detail-panel collapsible-panel">
          <summary>固定费用 / 工资拆解（默认收起）</summary>
          <p class="detail-intro">这里保留利润核算需要的费用底稿。平时默认收起，避免把总览页面拖得太长。</p>
          <div class="tables tables-single tables-compact">{cost_tables_html}</div>
        </details>
        """

    chart_sections_html = "".join(
        f"""
        <details class="detail-panel collapsible-panel chart-toggle-card" {'open' if index == 0 else ''}>
          <summary>图表 {index + 1}</summary>
          <p class="detail-intro">图表默认按一行一个展示，需要时再展开，避免详细页一上来太长。</p>
          <section class="chart-card">{chart}</section>
        </details>
        """
        for index, chart in enumerate(charts)
    ) or render_empty("当前还没有可展示的图表。")

    tips_panel_html = f"""
      <details class="detail-panel collapsible-panel">
        <summary>术语 Tips（默认收起）</summary>
        <p class="detail-intro">页面里已经保留了关键短句和标签提示。这里放完整词典，需要时再展开看。</p>
        <div class="tip-grid">{tips_html}</div>
      </details>
    """

    overview_panels_html = f"""
      <div class="module detail-module detail-module-flat" style="margin:0;">
        <div class="module-header">
          <h3 class="module-title" style="font-size:18px;">经营健康灯</h3>
          <p class="module-note">红色优先处理，黄色持续盯住，绿色维持节奏。</p>
        </div>
        <div class="health-grid health-grid-inline">{health_html}</div>
      </div>
      <div class="module detail-module detail-module-flat" style="margin-top:14px;">
        <div class="module-header">
          <h3 class="module-title" style="font-size:18px;">北京时间与季节节奏</h3>
          <p class="module-note">今天 / 本周 / 本月的季节动作参考。</p>
        </div>
        <ul class="insight-list">{render_time_strategy_html(time_strategy)}</ul>
      </div>
      <div class="detail-grid">
        <div class="module detail-module" style="margin:0;">
          <div class="module-header">
            <h3 class="module-title" style="font-size:18px;">POS 高价值数据</h3>
            <p class="module-note">把报表里更接近真实经营动作的数据抽出来，只保留老板能直接用的信息。</p>
          </div>
          {f"<div class='metrics-grid'>{pos_overview_html}</div>" if pos_overview_html else render_empty("当前还没有可用的 POS 高价值报表样本。")}
        </div>
        <div class="module detail-module" style="margin:0;">
          <div class="module-header">
            <h3 class="module-title" style="font-size:18px;">自动提炼重点提醒</h3>
            <p class="module-note">保留原有数据提醒，也把 POS 新增信息一起带进来，方便复盘时快速扫一遍。</p>
          </div>
          <ul class="insight-list">{insights_html}</ul>
        </div>
      </div>
      {cost_breakdown_html if cost_breakdown_html else ""}
    """
    strategy_panels_html = f"""
      <div class="module detail-module" style="margin:0;">
        <div class="module-header">
          <h3 class="module-title" style="font-size:18px;">自动生成经营方案</h3>
          <p class="module-note">基于当前数据生成的处理方案，适合老板拍板。</p>
        </div>
        <div class="playbook-grid">{playbooks_html}</div>
      </div>
      <div style="margin-top:14px;">{tips_panel_html}</div>
    """
    consulting_panel_html = render_consulting_analysis_html(
        consulting_analysis,
        "经营分析与销售建议",
        "consulting-analysis",
    )
    replenish_category_table = metrics["replenish_categories"][["中类", "季节策略", "SKU数", "销售额", "库存", "建议补货量", "补货原则", "主销尺码", "控折扣原则", "预算建议"]].copy()
    seasonal_category_table = metrics["seasonal_categories"][["中类", "季节策略", "建议动作", "SKU数", "库存", "销售额"]].copy()
    clearance_category_table = metrics["clearance_categories"][["大类", "建议动作", "SKU数", "实际库存", "近期零售"]].copy()
    replenish_table = metrics["replenish"][["款号", "中类", "颜色", "季节策略", "库存", "周均销量", "库存周数", "销售金额", "建议补货量", "补货原则", "主销尺码", "控折扣原则", "预算建议", "进货顺序", "进货提醒", "建议动作"]].copy()
    seasonal_action_table = metrics["seasonal_actions"][["款号", "中类", "颜色", "季节", "季节策略", "库存", "库存周数", "销售金额", "建议动作"]].copy()
    clearance_cols = ["商品款号", "商品名称", "商品颜色", "大类", "中类", "实际库存", "近期零售", "零售价", "建议动作"]
    clearance_available_cols = [column for column in clearance_cols if column in metrics["clearance"].columns]
    clearance_table = metrics["clearance"][clearance_available_cols].copy()

    if not clearance_table.empty and "商品名称" in clearance_table.columns:
        clearance_table["商品名称"] = clearance_table["商品名称"].apply(lambda value: table_text_with_tip(value, 10, "详情"))
    if not clearance_table.empty and "商品颜色" in clearance_table.columns:
        clearance_table["商品颜色"] = clearance_table["商品颜色"].apply(lambda value: table_text_with_tip(value, 8, "详情"))

    inventory_tables_html = "".join(
        [
            table_html(replenish_category_table, "补货重点品类", 12, "按品类定补货优先级。电脑端适合横向比较，手机端可左右滑动表格。"),
            table_html(seasonal_category_table, "跨季处理重点品类", 12, "先看哪些品类当前不该补，再决定暂缓还是去化。"),
            table_html(clearance_category_table, "去化重点品类", 12, "先看库存压力最大的品类，再安排陈列和促销动作。"),
            table_html(replenish_table, "补货 SKU 明细", 16, "确定品类要补后，再到这里挑具体款。长动作说明已收进标签提示。"),
            table_html(seasonal_action_table, "跨季处理 SKU 明细", 16, "老板二次判断时使用，重点看季节策略、库存和建议动作。"),
            table_html(clearance_table, "去化 SKU 明细", 16, "执行去化时再下钻到具体款，长商品名已收进提示。"),
            table_html(metrics["negative_inventory"], "负库存异常清单", 12, "先查账、查盘点、查调拨。"),
        ]
    )
    people_tables_html = "".join(
        [
            table_html(metrics["top_members"], "高价值会员", 12, "优先回访高消费或高频顾客。"),
            table_html(metrics["guide_perf"], "店员 / 导购表现", 10, "电脑端更适合同屏对比实收金额、票数和连带。"),
            table_html(other_references, "其他店铺参考", 8, reference_intro),
        ]
    )
    download_cards_html = """
      <div class="cards-grid">
        <div class="opportunity-card">
          <div class="card-kicker">HTML</div>
          <div class="card-title">老板仪表盘</div>
          <p class="table-tip">适合老板每天直接打开，先看今日重点和执行任务。</p>
          <div class="chip-row">
            <a class="download-link" href="./index.html">打开当前页</a>
          </div>
        </div>
        <div class="opportunity-card">
          <div class="card-kicker">HTML</div>
          <div class="card-title">文字摘要</div>
          <p class="table-tip">适合手机快速阅读，也适合转发给店员和群里同步。</p>
          <div class="chip-row">
            <a class="download-link" href="../manuals/dashboard/summary.html">打开 HTML 摘要</a>
            <a class="download-link" href="./summary.md">下载 Markdown</a>
          </div>
        </div>
        <div class="opportunity-card">
          <div class="card-kicker">HTML</div>
          <div class="card-title">分析报告</div>
          <p class="table-tip">适合周复盘时看完整分析，也适合做经营会议材料。</p>
          <div class="chip-row">
            <a class="download-link" href="../manuals/dashboard/report.html">打开 HTML 报告</a>
            <a class="download-link" href="./report.md">下载 Markdown</a>
          </div>
        </div>
        <div class="opportunity-card">
          <div class="card-kicker">CSV</div>
          <div class="card-title">补货 / 去化 / 风险</div>
          <p class="table-tip">需要下钻执行时，再下载 CSV 给店员或表格协作人使用。</p>
          <div class="chip-row">
            <a class="download-link" href="./%E8%A1%A5%E8%B4%A7%E5%BB%BA%E8%AE%AE%E6%B8%85%E5%8D%95.csv">补货 CSV</a>
            <a class="download-link" href="./%E5%8E%BB%E5%8C%96%E5%BB%BA%E8%AE%AE%E6%B8%85%E5%8D%95.csv">去化 CSV</a>
            <a class="download-link" href="./%E5%93%81%E7%B1%BB%E9%A3%8E%E9%99%A9%E6%A6%82%E8%A7%88.csv">风险 CSV</a>
          </div>
        </div>
      </div>
    """
    detail_quick_nav_html = "".join(
        [
            "<a href='./index.html'>返回首页</a>",
            "<a href='#overview-section'>总览</a>",
            "<a href='#strategy-section'>经营策略</a>",
            "<a href='#consulting-analysis'>经营分析</a>",
            "<a href='#charts-section'>图表</a>",
            "<a href='#inventory-section'>补货去化</a>",
            "<a href='#people-section'>会员店员</a>",
            "<a href='#downloads-section'>下载</a>",
        ]
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{cards['store_name']} 老板经营仪表盘</title>
  <style>
    html, body {{
      max-width: 100%;
      overflow-x: hidden;
    }}
    * {{
      box-sizing: border-box;
    }}
    body {{
      margin: 0;
      padding: 0;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: #f6f7fb;
      color: #1f2937;
    }}
    .page {{
      max-width: 1380px;
      margin: 0 auto;
      padding: 24px;
    }}
    .top-nav {{
      position: sticky;
      top: 0;
      z-index: 50;
      margin-bottom: 18px;
      background: rgba(246, 247, 251, 0.92);
      backdrop-filter: blur(14px);
      border: 1px solid rgba(148, 163, 184, 0.18);
      border-radius: 18px;
      box-shadow: 0 10px 24px rgba(15, 23, 42, 0.08);
    }}
    .top-nav-links {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      padding: 12px;
    }}
    .top-nav-link {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: 999px;
      padding: 9px 14px;
      font-size: 13px;
      font-weight: 800;
      color: #334155;
      background: #ffffff;
      border: 1px solid #dbe4f0;
      text-decoration: none;
    }}
    .top-nav-link.is-active {{
      background: #dbeafe;
      color: #1d4ed8;
      border-color: #bfdbfe;
    }}
    .page-shell {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 250px;
      gap: 18px;
    }}
    .main-column {{
      min-width: 0;
    }}
    .side-rail {{
      display: flex;
      flex-direction: column;
      gap: 16px;
      align-self: start;
    }}
    .rail-card {{
      position: sticky;
      top: 88px;
      background: #fff;
      border-radius: 18px;
      padding: 16px;
      box-shadow: 0 10px 30px rgba(15, 23, 42, 0.08);
    }}
    .rail-card h3 {{
      margin: 0 0 8px;
      font-size: 17px;
      color: #0f172a;
    }}
    .rail-card p {{
      margin: 0 0 12px;
      font-size: 12px;
      line-height: 1.8;
      color: #64748b;
    }}
    .rail-links {{
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}
    .rail-links a {{
      display: block;
      text-decoration: none;
      color: #334155;
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 14px;
      padding: 10px 12px;
      font-size: 13px;
      font-weight: 700;
    }}
    .rail-links a.current {{
      background: #dbeafe;
      border-color: #bfdbfe;
      color: #1d4ed8;
    }}
    .hero {{
      background: linear-gradient(135deg, #0f172a 0%, #1d4ed8 100%);
      color: white;
      padding: 24px;
      border-radius: 20px;
      margin-bottom: 20px;
      box-shadow: 0 18px 48px rgba(15, 23, 42, 0.18);
    }}
    .hero h1 {{
      margin: 0 0 8px;
      font-size: 30px;
    }}
    .hero p {{
      margin: 0;
      opacity: 0.92;
      line-height: 1.7;
    }}
    .hero-note {{
      margin-top: 12px;
      font-size: 13px;
      opacity: 0.88;
    }}
    .hero-status {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 12px;
    }}
    .hero-status-chip {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: rgba(255, 255, 255, 0.12);
      border: 1px solid rgba(255, 255, 255, 0.2);
      color: #ffffff;
      border-radius: 999px;
      padding: 7px 12px;
      font-size: 12px;
      font-weight: 700;
      line-height: 1.5;
    }}
    .action-strip {{
      margin-bottom: 18px;
      background: linear-gradient(135deg, #fff7ed 0%, #fffbeb 100%);
      border: 1px solid #fed7aa;
    }}
    .action-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
      margin-top: 16px;
    }}
    .action-card {{
      background: #ffffff;
      border: 1px solid #fde68a;
      border-radius: 18px;
      padding: 16px;
      box-shadow: 0 10px 24px rgba(245, 158, 11, 0.08);
    }}
    .action-kicker {{
      font-size: 12px;
      font-weight: 800;
      color: #b45309;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      margin-bottom: 8px;
    }}
    .action-title {{
      margin: 0 0 8px;
      font-size: 20px;
      color: #0f172a;
    }}
    .action-text {{
      margin: 0 0 12px;
      font-size: 13px;
      line-height: 1.8;
      color: #475569;
    }}
    .action-link {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: 999px;
      padding: 10px 14px;
      text-decoration: none;
      font-size: 13px;
      font-weight: 800;
      background: #1d4ed8;
      color: #ffffff;
    }}
    .quick-nav {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin: 14px 0 18px;
      max-width: 100%;
      overscroll-behavior-x: contain;
    }}
    .quick-nav a {{
      text-decoration: none;
      color: #1d4ed8;
      background: #eff6ff;
      border: 1px solid #bfdbfe;
      padding: 8px 12px;
      border-radius: 999px;
      font-size: 13px;
      font-weight: 700;
      white-space: nowrap;
    }}
    .module {{
      background: white;
      border-radius: 18px;
      box-shadow: 0 10px 30px rgba(15, 23, 42, 0.08);
      padding: 18px;
      margin-bottom: 18px;
    }}
    .module-header {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
      margin-bottom: 12px;
      flex-wrap: wrap;
    }}
    .module-title {{
      margin: 0;
      font-size: 22px;
      color: #0f172a;
    }}
    .module-note {{
      margin: 0;
      font-size: 13px;
      color: #64748b;
      line-height: 1.7;
    }}
    .submodule-header {{
      margin: 18px 0 10px;
    }}
    .submodule-title {{
      margin: 0 0 6px;
      font-size: 18px;
      color: #0f172a;
    }}
    .submodule-note {{
      margin: 0;
      font-size: 13px;
      color: #64748b;
      line-height: 1.7;
    }}
    .focus-wrap {{
      display: grid;
      grid-template-columns: 1.2fr 1fr;
      gap: 16px;
    }}
    .focus-panel {{
      background: #fffdf7;
      border: 1px solid #fde68a;
      border-radius: 16px;
      padding: 16px;
    }}
    .focus-headline {{
      font-size: 28px;
      font-weight: 800;
      color: #92400e;
      margin: 0 0 10px;
    }}
    .focus-summary {{
      margin: 0;
      font-size: 14px;
      line-height: 1.8;
      color: #5b4636;
    }}
    .chip-row {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 14px;
    }}
    .mini-chip {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 6px 12px;
      font-size: 13px;
      font-weight: 700;
      white-space: nowrap;
    }}
    .mini-chip-primary {{
      background: #dbeafe;
      color: #1d4ed8;
    }}
    .mini-chip-soft {{
      background: #f1f5f9;
      color: #334155;
    }}
    .mini-chip-danger {{
      background: #fee2e2;
      color: #991b1b;
    }}
    .mini-chip-warn {{
      background: #fef3c7;
      color: #92400e;
    }}
    .task-list, .detail-list {{
      margin: 0 0 0 18px;
      padding: 0;
      line-height: 1.9;
      color: #334155;
      font-size: 14px;
    }}
    .metrics-grid, .cards-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
    }}
    .metric-card, .opportunity-card, .risk-card, .member-card, .health-card, .tip-card, .playbook-card, .chart-card, .table-card {{
      background: #ffffff;
      border-radius: 16px;
      border: 1px solid #e2e8f0;
      padding: 16px;
      min-width: 0;
    }}
    .metric-card {{
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
    }}
    .metric-title {{
      font-size: 14px;
      color: #64748b;
      margin-bottom: 8px;
    }}
    .metric-value {{
      font-size: 30px;
      font-weight: 800;
      margin-bottom: 6px;
      color: #0f172a;
    }}
    .metric-note {{
      font-size: 13px;
      color: #64748b;
    }}
    .inline-tip {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      margin-left: 6px;
      padding: 1px 8px;
      border-radius: 999px;
      border: 1px solid #bfdbfe;
      background: #eff6ff;
      color: #1d4ed8;
      font-size: 11px;
      font-weight: 800;
      line-height: 1.6;
      vertical-align: middle;
      white-space: nowrap;
    }}
    .metric-red {{
      border-color: #fecaca;
      background: #fff7f7;
    }}
    .metric-red .metric-value {{
      color: #991b1b;
    }}
    .metric-yellow {{
      border-color: #fde68a;
      background: #fffbeb;
    }}
    .metric-yellow .metric-value {{
      color: #92400e;
    }}
    .metric-green {{
      border-color: #bbf7d0;
      background: #f0fdf4;
    }}
    .metric-green .metric-value {{
      color: #166534;
    }}
    .card-kicker {{
      font-size: 12px;
      font-weight: 700;
      color: #64748b;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      margin-bottom: 6px;
    }}
    .card-title {{
      font-size: 18px;
      font-weight: 800;
      color: #0f172a;
      margin-bottom: 12px;
    }}
    .card-note {{
      font-size: 12px;
      color: #64748b;
      margin-top: 10px;
    }}
    .stat-row {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      font-size: 14px;
      line-height: 1.8;
      color: #475569;
    }}
    .stat-row strong {{
      color: #0f172a;
      font-size: 15px;
    }}
    .risk-card {{
      background: #fff8f5;
      border-color: #fed7aa;
    }}
    .member-card {{
      background: #f8fafc;
    }}
    .empty-card {{
      border: 1px dashed #cbd5e1;
      border-radius: 16px;
      padding: 20px;
      color: #64748b;
      background: #f8fafc;
      font-size: 14px;
      line-height: 1.8;
    }}
    .analysis-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 14px;
    }}
    .analysis-card {{
      background: #ffffff;
      border: 1px solid #e2e8f0;
      border-radius: 16px;
      padding: 16px;
      min-width: 0;
    }}
    .analysis-card h3 {{
      margin: 0 0 10px;
      font-size: 17px;
      color: #0f172a;
    }}
    .analysis-list {{
      margin: 0;
      padding-left: 18px;
      color: #334155;
      font-size: 14px;
      line-height: 1.9;
    }}
    .priority-red {{
      background: #fff7f7;
      border-color: #fecaca;
    }}
    .priority-yellow {{
      background: #fffbeb;
      border-color: #fde68a;
    }}
    .priority-neutral {{
      background: #f8fafc;
      border-color: #cbd5e1;
    }}
    .priority-green {{
      background: #f0fdf4;
      border-color: #bbf7d0;
    }}
    .tooltip-badge {{
      position: relative;
      cursor: help;
    }}
    .tooltip-badge::after {{
      content: attr(data-tip);
      position: absolute;
      left: 0;
      bottom: calc(100% + 10px);
      width: min(320px, 68vw);
      white-space: normal;
      background: #0f172a;
      color: #ffffff;
      border-radius: 12px;
      padding: 10px 12px;
      line-height: 1.6;
      font-size: 12px;
      font-weight: 500;
      box-shadow: 0 12px 24px rgba(15, 23, 42, 0.2);
      opacity: 0;
      pointer-events: none;
      transform: translateY(6px);
      transition: opacity 0.18s ease, transform 0.18s ease;
      z-index: 40;
    }}
    .tooltip-badge::before {{
      content: "";
      position: absolute;
      left: 14px;
      bottom: calc(100% + 4px);
      width: 10px;
      height: 10px;
      background: #0f172a;
      transform: rotate(45deg);
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.18s ease, transform 0.18s ease;
      z-index: 39;
    }}
    .tooltip-badge:hover::after,
    .tooltip-badge:hover::before,
    .tooltip-badge:focus-visible::after,
    .tooltip-badge:focus-visible::before {{
      opacity: 1;
      transform: translateY(0);
    }}
    .tooltip-badge:focus-visible {{
      outline: 2px solid #93c5fd;
      outline-offset: 2px;
    }}
    .detail-panel {{
      background: white;
      border-radius: 18px;
      box-shadow: 0 10px 30px rgba(15, 23, 42, 0.08);
      padding: 18px;
      margin-bottom: 18px;
    }}
    .detail-panel summary {{
      cursor: pointer;
      font-size: 18px;
      font-weight: 800;
      color: #0f172a;
      list-style: none;
    }}
    .detail-panel summary::-webkit-details-marker {{
      display: none;
    }}
    .detail-panel[open] summary {{
      margin-bottom: 14px;
    }}
    .detail-intro {{
      margin: 0 0 14px;
      color: #475569;
      font-size: 13px;
      line-height: 1.8;
    }}
    .detail-shell {{
      display: grid;
      grid-template-columns: 280px minmax(0, 1fr);
      gap: 16px;
      align-items: start;
      min-width: 0;
    }}
    .detail-sidebar {{
      position: sticky;
      top: 16px;
      align-self: start;
    }}
    .detail-sidebar-card {{
      background: #f8fafc;
      border: 1px solid #dbe4f0;
      border-radius: 16px;
      padding: 14px;
      margin-bottom: 12px;
    }}
    .detail-sidebar-title {{
      margin: 0 0 8px;
      font-size: 16px;
      font-weight: 800;
      color: #0f172a;
    }}
    .detail-sidebar-note {{
      margin: 0;
      font-size: 12px;
      line-height: 1.8;
      color: #64748b;
    }}
    .detail-nav {{
      display: grid;
      gap: 10px;
      margin-top: 12px;
      max-width: 100%;
      overscroll-behavior-x: contain;
    }}
    .detail-nav-btn {{
      appearance: none;
      width: 100%;
      border: 1px solid #dbe4f0;
      background: #ffffff;
      border-radius: 14px;
      padding: 12px;
      text-align: left;
      cursor: pointer;
      transition: border-color 0.18s ease, background 0.18s ease, transform 0.18s ease;
      min-width: 0;
    }}
    .detail-nav-btn:hover {{
      border-color: #93c5fd;
      background: #f8fbff;
      transform: translateY(-1px);
    }}
    .detail-nav-btn.is-active {{
      border-color: #60a5fa;
      background: #eff6ff;
      box-shadow: 0 8px 18px rgba(37, 99, 235, 0.08);
    }}
    .detail-nav-label {{
      display: block;
      font-size: 14px;
      font-weight: 800;
      color: #0f172a;
      margin-bottom: 4px;
    }}
    .detail-nav-note {{
      display: block;
      font-size: 12px;
      color: #64748b;
      line-height: 1.6;
    }}
    .detail-content {{
      min-width: 0;
      max-width: 100%;
      overflow-x: hidden;
    }}
    .detail-pane {{
      display: none;
      animation: fadeIn 0.18s ease;
      min-width: 0;
      max-width: 100%;
      overflow-x: hidden;
    }}
    .detail-pane.is-active {{
      display: block;
    }}
    .detail-pane + .detail-pane {{
      margin-top: 0;
    }}
    .detail-pane-header {{
      margin-bottom: 12px;
    }}
    .detail-pane-title {{
      margin: 0 0 6px;
      font-size: 20px;
      font-weight: 800;
      color: #0f172a;
    }}
    .detail-pane-note {{
      margin: 0;
      color: #64748b;
      font-size: 13px;
      line-height: 1.8;
    }}
    .detail-module {{
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05);
    }}
    .detail-grid, .tip-grid, .playbook-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 14px;
      margin-top: 14px;
      min-width: 0;
      max-width: 100%;
    }}
    .charts,
    .tables {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 14px;
      margin-top: 14px;
      min-width: 0;
      max-width: 100%;
    }}
    .tables-compact {{
      margin-top: 0;
    }}
    .health-grid {{
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 14px;
      margin-top: 14px;
      min-width: 0;
      max-width: 100%;
    }}
    .detail-module-flat {{
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05);
    }}
    .health-red {{
      background: #fff1f2;
      border-color: #fecdd3;
    }}
    .health-yellow {{
      background: #fffbeb;
      border-color: #fde68a;
    }}
    .health-green {{
      background: #ecfdf5;
      border-color: #a7f3d0;
    }}
    .health-title {{
      font-size: 14px;
      color: #64748b;
      margin-bottom: 8px;
    }}
    .health-value {{
      font-size: 28px;
      font-weight: 800;
      margin-bottom: 6px;
    }}
    .health-note {{
      font-size: 13px;
      line-height: 1.7;
      color: #475569;
    }}
    .tip-term {{
      font-size: 15px;
      font-weight: 800;
      margin-bottom: 8px;
    }}
    .collapsible-panel {{
      margin-bottom: 0;
    }}
    .collapsible-panel summary {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }}
    .collapsible-panel summary::after {{
      content: "展开";
      font-size: 12px;
      font-weight: 700;
      color: #1d4ed8;
      background: #eff6ff;
      border: 1px solid #bfdbfe;
      border-radius: 999px;
      padding: 4px 10px;
      flex-shrink: 0;
    }}
    .collapsible-panel[open] summary::after {{
      content: "收起";
    }}
    .tip-meaning, .tip-watch, .playbook-trigger, .playbook-goal, .table-tip {{
      font-size: 13px;
      line-height: 1.8;
      color: #475569;
    }}
    .playbook-title {{
      font-size: 16px;
      font-weight: 800;
      margin-bottom: 10px;
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
    .playbook-card ul, .insight-list {{
      margin: 10px 0 0 18px;
      padding: 0;
      line-height: 1.8;
      font-size: 13px;
      color: #334155;
    }}
    .download-link {{
      text-decoration: none;
      color: #1d4ed8;
      background: #eff6ff;
      border: 1px solid #bfdbfe;
      border-radius: 999px;
      padding: 7px 12px;
      font-size: 12px;
      font-weight: 700;
    }}
    .data-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
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
    .table-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      margin-bottom: 8px;
    }}
    .table-header h3 {{
      margin: 0;
      font-size: 18px;
      color: #0f172a;
    }}
    .table-toggle {{
      display: none;
      border: 1px solid #bfdbfe;
      background: #eff6ff;
      color: #1d4ed8;
      border-radius: 999px;
      padding: 7px 10px;
      font-size: 11px;
      font-weight: 700;
      white-space: nowrap;
      cursor: pointer;
    }}
    .table-scroll {{
      max-width: 100%;
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
      overscroll-behavior-x: contain;
    }}
    .table-card {{
      overflow-x: auto;
      max-width: 100%;
      -webkit-overflow-scrolling: touch;
      overscroll-behavior-x: contain;
    }}
    .compact-card {{
      overflow: hidden;
    }}
    .compact-list {{
      display: grid;
      gap: 12px;
      margin-top: 6px;
    }}
    .compact-item {{
      border: 1px solid #e2e8f0;
      border-radius: 14px;
      padding: 14px;
      background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
    }}
    .compact-item-head {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 10px;
      margin-bottom: 10px;
    }}
    .compact-item-title {{
      font-size: 16px;
      font-weight: 800;
      color: #0f172a;
      line-height: 1.4;
      word-break: break-word;
    }}
    .compact-item-subtitle {{
      font-size: 12px;
      color: #64748b;
      line-height: 1.7;
      word-break: break-word;
    }}
    .compact-stats {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }}
    .compact-stat {{
      background: #ffffff;
      border: 1px solid #e2e8f0;
      border-radius: 12px;
      padding: 10px 12px;
      display: flex;
      flex-direction: column;
      gap: 6px;
      min-width: 0;
    }}
    .compact-stat span {{
      font-size: 11px;
      font-weight: 700;
      color: #64748b;
      line-height: 1.5;
    }}
    .compact-stat strong {{
      font-size: 16px;
      font-weight: 800;
      color: #0f172a;
      line-height: 1.4;
      word-break: break-word;
    }}
    .compact-stat .mini-chip {{
      align-self: flex-start;
      max-width: 100%;
      white-space: normal;
      word-break: break-word;
    }}
    .compact-more {{
      margin-top: 10px;
      border-top: 1px dashed #dbe4f0;
      padding-top: 10px;
    }}
    .compact-more summary {{
      cursor: pointer;
      font-size: 12px;
      font-weight: 700;
      color: #1d4ed8;
      list-style: none;
    }}
    .compact-more summary::-webkit-details-marker {{
      display: none;
    }}
    .compact-detail-list {{
      margin: 8px 0 0 18px;
      padding: 0;
      color: #475569;
      font-size: 12px;
      line-height: 1.8;
    }}
    .chart-card {{
      overflow: hidden;
      max-width: 100%;
      padding: 0;
      border: 0;
      box-shadow: none;
    }}
    .chart-card .js-plotly-plot,
    .chart-card .plot-container,
    .chart-card .plotly,
    .chart-card .svg-container {{
      width: 100% !important;
      max-width: 100% !important;
    }}
    .chart-card .modebar {{
      max-width: calc(100% - 8px);
      right: 4px !important;
    }}
    @keyframes fadeIn {{
      from {{
        opacity: 0;
        transform: translateY(3px);
      }}
      to {{
        opacity: 1;
        transform: translateY(0);
      }}
    }}
    @media (max-width: 960px) {{
      .page {{
        padding: 16px;
      }}
      .page-shell {{
        grid-template-columns: 1fr;
      }}
      .rail-card {{
        position: static;
      }}
      .rail-links {{
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
      .quick-nav {{
        position: sticky;
        top: 8px;
        z-index: 20;
        background: rgba(246, 247, 251, 0.96);
        padding: 8px 0 6px;
        margin-top: 10px;
      }}
      .quick-nav a {{
        font-size: 12px;
        padding: 7px 10px;
      }}
      .focus-wrap {{
        grid-template-columns: 1fr;
      }}
      .detail-shell {{
        grid-template-columns: 1fr;
      }}
      .detail-sidebar {{
        position: static;
      }}
      .detail-nav {{
        grid-template-columns: repeat(3, minmax(0, 1fr));
        overflow: visible;
      }}
      .module-header {{
        flex-direction: column;
        align-items: flex-start;
      }}
      .metrics-grid, .cards-grid, .detail-grid, .health-grid, .tip-grid, .playbook-grid, .charts, .tables {{
        grid-template-columns: 1fr;
      }}
      .tooltip-badge::after {{
        width: min(260px, 72vw);
      }}
    }}
    @media (max-width: 640px) {{
      .page {{
        padding: 12px;
      }}
      .top-nav-links {{
        width: 100%;
      }}
      .top-nav-link {{
        width: 100%;
      }}
      .quick-nav {{
        flex-wrap: nowrap;
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
        margin: 10px 0 14px;
        padding-bottom: 2px;
        scroll-snap-type: x proximity;
      }}
      .quick-nav a {{
        scroll-snap-align: start;
      }}
      .hero {{
        padding: 18px;
        border-radius: 16px;
      }}
      .hero h1 {{
        font-size: 24px;
        line-height: 1.3;
      }}
      .hero p, .hero-note {{
        font-size: 12px;
        line-height: 1.7;
      }}
      .hero-status {{
        gap: 8px;
      }}
      .hero-status-chip {{
        width: 100%;
        justify-content: center;
        text-align: center;
        font-size: 11px;
        padding: 7px 10px;
      }}
      .module {{
        padding: 14px;
        border-radius: 16px;
        margin-bottom: 14px;
      }}
      .detail-panel {{
        padding: 14px;
      }}
      .detail-intro {{
        font-size: 12px;
      }}
      .detail-sidebar-card {{
        padding: 12px;
        border-radius: 14px;
      }}
      .detail-nav {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 8px;
        overflow: visible;
        margin-right: 0;
        padding-bottom: 0;
      }}
      .detail-nav-btn {{
        width: 100%;
        min-width: 0;
        padding: 8px 6px;
        border-radius: 12px;
      }}
      .detail-nav-label {{
        font-size: 12px;
        margin-bottom: 0;
        text-align: center;
      }}
      .detail-nav-note {{
        display: none;
      }}
      .detail-pane-note,
      .detail-sidebar-note {{
        font-size: 11px;
        line-height: 1.7;
      }}
      .quick-nav a,
      .download-link {{
        font-size: 11px;
      }}
      .rail-links {{
        grid-template-columns: 1fr;
      }}
      .detail-sidebar-card:last-child {{
        display: none;
      }}
      .detail-pane-title {{
        font-size: 18px;
      }}
      .collapsible-panel summary::after {{
        padding: 3px 8px;
        font-size: 11px;
      }}
      .table-toggle {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
      }}
      .compact-item {{
        padding: 12px;
      }}
      .compact-item-head {{
        margin-bottom: 8px;
      }}
      .compact-item-title {{
        font-size: 15px;
      }}
      .compact-item-subtitle {{
        font-size: 11px;
      }}
      .compact-stats {{
        grid-template-columns: 1fr;
        gap: 8px;
      }}
      .compact-stat {{
        padding: 9px 10px;
      }}
      .compact-stat strong {{
        font-size: 15px;
      }}
      .compact-detail-list {{
        font-size: 11px;
      }}
      .table-card.is-compact [data-mobile-hidden="1"] {{
        display: none;
      }}
      .module-title {{
        font-size: 18px;
      }}
      .focus-panel,
      .metric-card, .opportunity-card, .risk-card, .member-card, .health-card, .tip-card, .playbook-card, .chart-card, .table-card {{
        padding: 14px;
        border-radius: 14px;
      }}
      .focus-headline {{
        font-size: 22px;
        line-height: 1.35;
      }}
      .focus-summary,
      .module-note,
      .task-list, .detail-list,
      .tip-meaning, .tip-watch, .playbook-trigger, .playbook-goal, .table-tip,
      .health-note {{
        font-size: 12px;
        line-height: 1.75;
      }}
      .metric-value,
      .health-value {{
        font-size: 24px;
      }}
      .card-title {{
        font-size: 16px;
        margin-bottom: 10px;
      }}
      .stat-row {{
        font-size: 13px;
        line-height: 1.7;
      }}
      .stat-row strong {{
        font-size: 14px;
      }}
      .mini-chip {{
        font-size: 12px;
        padding: 6px 10px;
        white-space: normal;
      }}
      .chip-row {{
        gap: 8px;
      }}
      .task-list, .detail-list {{
        margin-left: 16px;
      }}
      .data-table {{
        font-size: 12px;
      }}
      .data-table th, .data-table td {{
        padding: 7px 8px;
      }}
    }}
  {floating_tooltip_css()}
  </style>
</head>
<body>
  <div class="page">
    <nav class="top-nav">
      <div class="top-nav-links">
        <a class="top-nav-link" href="../index.html">首页</a>
        <a class="top-nav-link" href="./index.html">仪表盘</a>
        <a class="top-nav-link is-active" href="./details.html">详细页</a>
        <a class="top-nav-link" href="./relationship.html">库存销售关系页</a>
        <a class="top-nav-link" href="./monthly.html">月度页</a>
        <a class="top-nav-link" href="./quarterly.html">季度页</a>
        <a class="top-nav-link" href="../manuals/index.html">文档中心</a>
        <a class="top-nav-link" href="../costs/index.html">成本维护台</a>
      </div>
    </nav>
    <section class="hero">
      <h1>{cards['store_name']} 详细经营页</h1>
      <p>这是长版详细页。总览和经营策略放在最上面，后面依次看图表、补货去化、会员店员和下载区，更适合复盘和细看。</p>
      <div class="hero-note">{store_note} · 当前季节：{time_strategy['season']} / {time_strategy['phase']} · 日销趋势：{decision['sales_trend']['label']}</div>
      <div class="hero-status">
        <div class="hero-status-chip">最近抓取日期：{capture_date}（北京时间）</div>
        <div class="hero-status-chip">数据导入日期：{capture_date}（北京时间）</div>
      </div>
    </section>

    <section class="module action-strip">
      <div class="module-header">
        <h2 class="module-title">老板娘最常用 3 步</h2>
        <p class="module-note">如果你已经在详细页里了，最常见的动作通常还是这 3 个。</p>
      </div>
      <div class="action-grid">
        <article class="action-card">
          <div class="action-kicker">第 1 步</div>
          <h3 class="action-title">回仪表盘</h3>
          <p class="action-text">如果只是想重新看今天结论和重点，不要在详细页里绕，直接回仪表盘首页最快。</p>
          <a class="action-link" href="./index.html">直接回仪表盘</a>
        </article>
        <article class="action-card">
          <div class="action-kicker">第 2 步</div>
          <h3 class="action-title">回首页</h3>
          <p class="action-text">如果要重新选入口、打开文档中心或交给别人从最简单的地方开始，就先回首页。</p>
          <a class="action-link" href="../index.html">直接回首页</a>
        </article>
        <article class="action-card">
          <div class="action-kicker">第 3 步</div>
          <h3 class="action-title">一键同步</h3>
          <p class="action-text">如果店里电脑已经开了本地服务，回首页同步区一键抓取，今天的数据会重新刷一遍。</p>
          <a class="action-link" href="../index.html#local-console">去同步区</a>
        </article>
      </div>
    </section>

    <div class="page-shell">
      <div class="main-column">
    <nav class="quick-nav">{detail_quick_nav_html}</nav>

    <section class="module" id="overview-section">
      <div class="module-header">
        <h2 class="module-title">总览</h2>
        <p class="module-note">先看整体状态，再决定今天是先救火、先去库存，还是先放大机会。</p>
      </div>
      {overview_panels_html}
    </section>

    <section class="module" id="strategy-section">
      <div class="module-header">
        <h2 class="module-title">经营策略</h2>
        <p class="module-note">这里的策略会根据每日数据、整体数据、库存和利润状态自动调整。</p>
      </div>
      {strategy_panels_html}
    </section>

    {consulting_panel_html}

    <section class="module" id="charts-section">
      <div class="module-header">
        <h2 class="module-title">图表</h2>
        <p class="module-note">适合看趋势、结构和变化，不适合第一眼就下结论。</p>
      </div>
      <div class="charts charts-single">{chart_sections_html}</div>
    </section>

    <section class="module" id="inventory-section">
      <div class="module-header">
        <h2 class="module-title">补货 / 去化</h2>
        <p class="module-note">先看品类，再看 SKU，再看负库存异常。执行时从这里往下钻。</p>
      </div>
      <div class="tables tables-single">{inventory_tables_html}</div>
    </section>

    <section class="module" id="people-section">
      <div class="module-header">
        <h2 class="module-title">会员 / 店员 / 参考店</h2>
        <p class="module-note">这一组适合复盘复购、导购执行和其他店铺对比，不参与主店第一页结论。</p>
      </div>
      <div class="tables tables-single">{people_tables_html}</div>
    </section>

    <section class="module" id="downloads-section">
      <div class="module-header">
        <h2 class="module-title">下载</h2>
        <p class="module-note">需要转发、导出或交给执行层时，从这里拿 HTML 和 CSV。</p>
      </div>
      {download_cards_html}
    </section>
      </div>
      <aside class="side-rail">
        <section class="rail-card">
          <h3>常用导航</h3>
          <p>老板和店员在任何细节页里，都能从这里直接回到常用页面。</p>
          <div class="rail-links">
            <a href="../index.html">返回首页</a>
            <a href="./index.html">回仪表盘</a>
            <a class="current" href="./details.html">当前详细页</a>
            <a href="./relationship.html">进入关系页</a>
            <a href="./monthly.html">进入月度页</a>
            <a href="./quarterly.html">进入季度页</a>
            <a href="../manuals/index.html">进入文档中心</a>
            <a href="../costs/index.html">进入成本维护台</a>
          </div>
        </section>
        <section class="rail-card">
          <h3>本页定位</h3>
          <p>如果只是看某一块，直接在右边跳，不用回到顶部重新找。</p>
          <div class="rail-links">
            <a href="#overview-section">总览</a>
            <a href="#strategy-section">经营策略</a>
            <a href="#consulting-analysis">经营分析</a>
            <a href="#charts-section">图表</a>
            <a href="#inventory-section">补货 / 去化</a>
            <a href="#people-section">会员 / 店员</a>
            <a href="#downloads-section">下载</a>
          </div>
        </section>
      </aside>
    </div>
  </div>
  <script>
    (function () {{
      document.querySelectorAll('[data-table-toggle]').forEach((button) => {{
        const card = button.closest('.table-card');
        if (!card) return;
        button.addEventListener('click', () => {{
          const compact = card.classList.toggle('is-compact');
          button.textContent = compact
            ? (button.getAttribute('data-expand-label') || '展开全部列')
            : (button.getAttribute('data-collapse-label') || '收起额外列');
        }});
      }});
    }})();
  </script>
{floating_tooltip_script()}
</body>
</html>
"""


def build_period_rows(metrics: dict, period_type: str) -> list[dict[str, object]]:
    pos_highlights = metrics.get("yeusoft_highlights") or {}
    sales_overview = pos_highlights.get("sales_overview") or {}
    key = "monthly_rows" if period_type == "monthly" else "quarterly_rows"
    rows = list(sales_overview.get(key) or [])
    if rows:
        return rows

    daily = metrics.get("sales_daily", pd.DataFrame()).copy()
    if daily.empty:
        return []
    daily = daily[daily["日期"].notna()].copy()
    if daily.empty:
        return []

    freq = "M" if period_type == "monthly" else "Q"
    daily["period"] = daily["日期"].dt.to_period(freq)
    grouped = (
        daily.groupby("period")
        .agg(销售额=("销售额", "sum"), 订单数=("订单数", "sum"))
        .reset_index()
        .sort_values("period")
    )
    rows = []
    for _, row in grouped.iterrows():
        period = row["period"]
        label = period.strftime("%Y-%m") if period_type == "monthly" else f"{period.year}Q{period.quarter}"
        rows.append(
            {
                "label": label,
                "sales_amount": float(row["销售额"]),
                "sales_qty": 0.0,
                "order_count": int(row["订单数"]),
                "avg_order_value": safe_ratio(row["销售额"], row["订单数"]),
                "member_ratio": 0.0,
                "top_category": "待补全",
                "top_category_sales": 0.0,
            }
        )
    return rows


def build_period_summary(metrics: dict, period_type: str) -> dict[str, object]:
    cards = metrics["summary_cards"]
    profit = cards.get("profit_snapshot")
    period_name = "月度" if period_type == "monthly" else "季度"
    pos_highlights = metrics.get("yeusoft_highlights") or {}
    product_sales = pos_highlights.get("product_sales")
    member_rank = pos_highlights.get("member_rank")
    category_highlight = pos_highlights.get("category_analysis")
    vip_analysis = pos_highlights.get("vip_analysis")
    guide_report = pos_highlights.get("guide_report")
    store_month_report = pos_highlights.get("store_month_report")
    retail_detail = pos_highlights.get("retail_detail")
    rows = build_period_rows(metrics, period_type)
    latest = rows[-1] if rows else None
    previous = rows[-2] if len(rows) >= 2 else None
    peak = max(rows, key=lambda item: item["sales_amount"], default=None)
    avg_sales = safe_ratio(sum(item["sales_amount"] for item in rows), len(rows))

    if latest and previous and previous["sales_amount"]:
        delta_pct = safe_ratio(latest["sales_amount"] - previous["sales_amount"], previous["sales_amount"])
    else:
        delta_pct = 0.0
    delta_tone = "green" if delta_pct >= 0.08 else "red" if delta_pct <= -0.08 else "yellow"
    delta_text = (
        f"较上{'月' if period_type == 'monthly' else '季度'}增长 {format_num(delta_pct * 100, 1)}%"
        if delta_pct >= 0
        else f"较上{'月' if period_type == 'monthly' else '季度'}回落 {format_num(abs(delta_pct) * 100, 1)}%"
    )

    guidance: list[str] = []
    purchase_guidance: list[str] = []
    replenish_categories = metrics.get("replenish_categories", pd.DataFrame())
    seasonal_categories = metrics.get("seasonal_categories", pd.DataFrame())
    clearance_categories = metrics.get("clearance_categories", pd.DataFrame())
    if latest:
        if delta_pct >= 0.08:
            guidance.append(
                f"最近一{'个月' if period_type == 'monthly' else '个季度'}销售有抬升，主销中类是 {latest['top_category']}，优先保证这个中类不断码。"
            )
        elif delta_pct <= -0.08:
            guidance.append(
                f"最近一{'个月' if period_type == 'monthly' else '个季度'}销售回落，先收紧平均补货，把预算集中到仍在跑量的 {latest['top_category']}。"
            )
        else:
            guidance.append(
                f"最近一{'个月' if period_type == 'monthly' else '个季度'}销售相对平稳，适合用 {latest['top_category']} 做稳客流，再慢慢去化慢销库存。"
            )
        if latest.get("member_ratio", 0) >= 0.6:
            guidance.append("会员贡献高，这个阶段更适合做定向回访和到店试穿，而不是全场硬促销。")
    if category_highlight:
        growth_rows = category_highlight.get("growth_rows") or []
        decline_rows = category_highlight.get("decline_rows") or []
        if growth_rows:
            guidance.append(
                "阶段性跑得更快的品类是 "
                + "、".join(row["name"] for row in growth_rows)
                + "，这批更适合继续放大陈列和补货预算。"
            )
        if decline_rows:
            guidance.append(
                "阶段性回落更明显的品类是 "
                + "、".join(row["name"] for row in decline_rows)
                + "，先别急着补，先判断是季节切换、货位靠后还是尺码结构不对。"
            )

    if product_sales:
        cross_share = product_sales["cross_season_stock_share"]
        if cross_share >= 0.35:
            guidance.append(
                f"当前跨季库存占比约 {format_num(cross_share * 100, 1)}%，这个阶段要先去跨季库存，再决定深补。"
            )
        elif product_sales["current_season_stock_share"] < 0.35:
            guidance.append(
                f"当季库存占比只有 {format_num(product_sales['current_season_stock_share'] * 100, 1)}%，补货预算要更多留给当季主销款。"
            )
        if product_sales["backlog_count"] >= 30:
            guidance.append(
                f"当前还有 {format_num(product_sales['backlog_count'])} 个积压风险款，陈列和组合促销要优先围绕这些款做。"
            )

    if member_rank and member_rank["top10_share"] >= 0.25:
        guidance.append(
            f"前 10 位会员贡献约 {format_num(member_rank['top10_share'] * 100, 1)}% 销额，优先回访 {member_rank['top_names']} 这类高价值会员。"
        )
    if vip_analysis and vip_analysis["dormant_ratio"] >= 0.35:
        guidance.append(
            f"会员沉默占比约 {format_num(vip_analysis['dormant_ratio'] * 100, 1)}%，这个阶段要把唤醒老客列进周任务。"
        )
    if guide_report and guide_report["top_guide_share"] >= 0.45:
        guidance.append(
            f"导购销售集中在 {guide_report['top_guide_name']}，占比约 {format_num(guide_report['top_guide_share'] * 100, 1)}%。接下来要把她的成交打法拆出来，带其他店员复制。"
        )
    if store_month_report:
        latest_joint = (
            store_month_report.get("latest_month")
            if period_type == "monthly"
            else store_month_report.get("latest_quarter")
        ) or {}
        if latest_joint and latest_joint.get("joint_rate", 0) < 1.2:
            guidance.append(
                f"最近{period_name}件单比约 {format_num(latest_joint.get('joint_rate', 0), 2)}，成交有了但每单带得不够，陈列和店员话术都要更偏组合。"
            )
    if retail_detail:
        guidance.append(
            f"当前实销折扣约 {format_num(retail_detail['weighted_discount_rate'] * 10, 1)} 折，主价格带在 {retail_detail['top_price_band']}。"
        )
        if retail_detail.get("markdown_pressure_high"):
            guidance.append(
                f"{retail_detail['discount_category_names']} 这些中类折扣依赖偏重，这个阶段先稳毛利、提客单和做组合，不建议继续用深折扣硬冲。"
            )

    if profit:
        if period_type == "monthly":
            if profit["passed_breakeven"]:
                guidance.append("当前月度已过保本线，可以在不伤毛利的前提下做轻促销放大营业额。")
            else:
                guidance.append("当前月度还没稳过保本线，先保客单、连带和主销中类，不要急着做深折扣。")
        else:
            guidance.append(
                f"按当前利润口径，月末净利预测约 {format_num(profit['projected_month_net_profit'], 2)} 元，季度策略要兼顾利润和库存节奏。"
            )
        if profit["projected_month_net_profit"] < 0:
            guidance.append(
                f"当前总费用约 {format_num(profit['total_expense'], 2)} 元，按现有节奏毛利还盖不住费用。这个阶段先做高毛利组合、提客单和控补货，不建议为了冲销售做深折扣。"
            )
        elif profit["passed_breakeven"]:
            guidance.append(
                "利润口径已经过保本线，后面的动作重点不是继续压缩经营，而是在守住毛利的前提下把主销营业额做大。"
            )

    if not guidance:
        guidance.append("当前还缺少足够的长时间数据，先保持主销品类不断码，再继续积累月度与季度记录。")

    top_replenish = replenish_categories.iloc[0] if not replenish_categories.empty else None
    top_seasonal = seasonal_categories.iloc[0] if not seasonal_categories.empty else None
    top_clearance = clearance_categories.iloc[0] if not clearance_categories.empty else None
    if latest and top_replenish is not None:
        if delta_pct >= 0.08:
            purchase_guidance.append(
                f"{period_name}进货优先放在 {latest['top_category']} 和 {top_replenish['中类']}。先补核心尺码和主销色，按 2-3 次小单快返来补，不要一次压深。"
            )
        elif delta_pct <= -0.08:
            purchase_guidance.append(
                f"{period_name}销售回落时，进货预算先收紧到 {latest['top_category']} 这类仍有成交的中类，其他中类只做保断码补货，不做平均备货。"
            )
        else:
            purchase_guidance.append(
                f"{period_name}销售相对平稳，进货以 {latest['top_category']} 为主，{top_replenish['中类']} 作为补充，维持小单多次的节奏最稳。"
            )

    if product_sales:
        cross_share = product_sales["cross_season_stock_share"]
        current_share = product_sales["current_season_stock_share"]
        if cross_share >= 0.35:
            purchase_guidance.append(
                f"当前跨季库存占比约 {format_num(cross_share * 100, 1)}%，这期进货要明显收缩跨季和非主销货，预算优先留给当季货，先去库存再扩品。"
            )
        if current_share < 0.35:
            purchase_guidance.append(
                f"当季库存占比只有 {format_num(current_share * 100, 1)}%，这期新进货建议至少 60% 以上给当季主销中类，先保主销不断码。"
            )

    if top_replenish is not None:
        purchase_guidance.append(
            f"从补货信号看，当前最值得补的是 {top_replenish['中类']}，建议补货量约 {format_num(top_replenish['建议补货量'])}。做法上先保销量高的款和尺码，不建议整类平均补。"
        )
    if category_highlight and category_highlight.get("growth_rows"):
        leading_name = category_highlight["growth_rows"][0]["name"]
        purchase_guidance.append(
            f"从品类趋势看，{leading_name} 近期跑得更快，这期进货预算可以适度向它倾斜，但仍然只补核心款和核心尺码。"
        )
    if retail_detail and retail_detail.get("size_rows"):
        purchase_guidance.append(
            f"从全量零售尺码结构看，主销尺码更集中在 {retail_detail['core_size_names']}。这期补货先保这些尺码，再观察边缘尺码是否真有成交。"
        )
    if retail_detail and retail_detail.get("markdown_pressure_high"):
        purchase_guidance.append(
            f"{retail_detail['discount_category_names']} 当前更依赖折扣成交，这期进货不要盲目放大，先保高毛利主销和核心尺码，避免新货继续靠让利卖。"
        )
        if top_replenish is not None:
            purchase_guidance.append(
                f"{period_name}补货顺序建议：先补 {top_replenish['中类']} 的 {retail_detail['core_size_names']}，"
                f"再观察 {retail_detail['discount_category_names']} 的真实毛利和连带，暂时不要给这几个中类做平均深补。"
            )
    elif retail_detail and top_replenish is not None:
        purchase_guidance.append(
            f"{period_name}补货顺序建议：先补 {top_replenish['中类']} 的 {retail_detail['core_size_names']}，"
            "再补相邻尺码，最后才补边缘尺码。先保成交，再追求尺码齐全。"
        )

    if product_sales and retail_detail:
        cross_share = product_sales["cross_season_stock_share"]
        current_share = product_sales["current_season_stock_share"]
        if retail_detail.get("markdown_pressure_high") and cross_share >= 0.35:
            purchase_guidance.append(
                f"{period_name}预算建议：当季主销和核心尺码至少占 60%，断码快返约 25%，跨季去化和试单合计不超过 15%。当前先把预算留给 {retail_detail['core_size_names']} 这些主销尺码。"
            )
        elif retail_detail.get("markdown_pressure_high"):
            purchase_guidance.append(
                f"{period_name}预算建议：高毛利主销中类约 55%，基础刚需中类约 30%，{retail_detail['discount_category_names']} 这类折扣依赖中类只留 15% 左右快返预算。"
            )
        elif current_share < 0.35:
            purchase_guidance.append(
                f"{period_name}预算建议：当季主销至少 65%，下一季试单约 15%，其余 20% 留给断码修复和小单快返，先把当季结构拉起来。"
            )
        else:
            purchase_guidance.append(
                f"{period_name}预算建议：增长更快的主销中类约 50%，稳定基础中类约 30%，观察和试补中类约 20%。预算先看动销和尺码，不按品类平均分。"
            )

    if top_clearance is not None and top_clearance["实际库存"] > 0:
        purchase_guidance.append(
            f"{top_clearance['大类']} 当前库存压力还在，这期进货前要先给它让预算和货位。高库存品类先停补、先去化，避免新货和旧货一起压。"
        )

    if top_seasonal is not None and str(top_seasonal["季节策略"]) in {"跨季去化", "暂缓补货"}:
        purchase_guidance.append(
            f"{top_seasonal['中类']} 当前季节策略是 {top_seasonal['季节策略']}，这类货本期不适合深补。正确做法是有库存先处理，没库存先等回到主销季再判断。"
        )
    if profit:
        if profit["projected_month_net_profit"] < 0:
            purchase_guidance.append(
                f"按当前利润口径，月底净利仍偏弱。这期进货先保高毛利、快周转、主销中类，低毛利和慢销中类只补断码，不做压货型备货。"
            )
        elif profit["passed_breakeven"]:
            purchase_guidance.append(
                "当前利润口径已过保本线，这期进货可以更主动，但仍以小单快返为主，优先放大主销，不建议因为利润转正就平均扩所有品类。"
            )

    if not purchase_guidance:
        purchase_guidance.append("当前还缺少足够的周期数据，进货先遵守两个原则：优先当季主销、避免平均补货。")

    overview_text = (
        f"最近{len(rows)}个{'月' if period_type == 'monthly' else '季度'}已纳入统计；"
        f"最新周期 {latest['label']} 销售额 {format_num(latest['sales_amount'], 2)} 元，"
        f"{delta_text if previous else '当前还没有可比周期'}。"
        if latest
        else "当前还没有足够的周期数据。"
    )

    return {
        "rows": rows,
        "latest": latest,
        "previous": previous,
        "peak": peak,
        "avg_sales": avg_sales,
        "delta_pct": delta_pct,
        "delta_tone": delta_tone,
        "delta_text": delta_text,
        "guidance": guidance[:5],
        "purchase_guidance": purchase_guidance[:5],
        "overview_text": overview_text,
        "product_sales": product_sales,
        "member_rank": member_rank,
        "category_highlight": category_highlight,
        "vip_analysis": vip_analysis,
        "guide_report": guide_report,
        "store_month_report": store_month_report,
        "retail_detail": retail_detail,
        "profit": profit,
    }


def build_period_charts(period_summary: dict[str, object], period_type: str) -> list[str]:
    rows = period_summary["rows"]
    if not rows:
        return []
    frame = pd.DataFrame(rows)
    charts: list[str] = []

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=frame["label"],
            y=frame["sales_amount"],
            name="销售额",
            marker_color="#1d4ed8",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=frame["label"],
            y=frame["order_count"],
            name="订单数",
            mode="lines+markers",
            yaxis="y2",
            line=dict(color="#f97316", width=3),
        )
    )
    fig.update_layout(
        title=f"{'月度' if period_type == 'monthly' else '季度'}销售额与订单数",
        height=400,
        margin=dict(l=20, r=20, t=60, b=20),
        yaxis=dict(title="销售额"),
        yaxis2=dict(title="订单数", overlaying="y", side="right"),
        legend=dict(orientation="h"),
    )
    charts.append(fig_to_html(fig, include_js=True))

    fig2 = go.Figure()
    fig2.add_trace(
        go.Scatter(
            x=frame["label"],
            y=frame["avg_order_value"],
            name="客单价",
            mode="lines+markers",
            line=dict(color="#0f766e", width=3),
        )
    )
    fig2.add_trace(
        go.Bar(
            x=frame["label"],
            y=frame["member_ratio"] * 100,
            name="会员占比",
            marker_color="#a855f7",
            opacity=0.45,
            yaxis="y2",
        )
    )
    fig2.update_layout(
        title=f"{'月度' if period_type == 'monthly' else '季度'}客单价与会员占比",
        height=400,
        margin=dict(l=20, r=20, t=60, b=20),
        yaxis=dict(title="客单价"),
        yaxis2=dict(title="会员占比(%)", overlaying="y", side="right"),
        legend=dict(orientation="h"),
    )
    charts.append(fig_to_html(fig2))
    return charts


def build_period_cards(rows: list[dict[str, object]], period_type: str) -> str:
    if not rows:
        return render_empty(f"当前还没有可展示的{'月度' if period_type == 'monthly' else '季度'}数据。")

    cards_html = []
    for index, row in enumerate(reversed(rows[-6:])):
        source_index = len(rows) - 1 - index
        previous = rows[source_index - 1] if source_index - 1 >= 0 else None
        if previous and previous["sales_amount"]:
            change_pct = safe_ratio(row["sales_amount"] - previous["sales_amount"], previous["sales_amount"])
            change_text = f"{'增长' if change_pct >= 0 else '回落'} {format_num(abs(change_pct) * 100, 1)}%"
            change_tone = "green" if change_pct >= 0.08 else "red" if change_pct <= -0.08 else "yellow"
        else:
            change_text = "暂无可比"
            change_tone = "neutral"
        cards_html.append(
            f"""
            <article class="period-card">
              <div class="period-card-head">
                <div class="period-card-title">{html.escape(str(row['label']))}</div>
                <div class="mini-chip mini-chip-{change_tone}">{html.escape(change_text)}</div>
              </div>
              <div class="period-stat-grid">
                <div class="period-stat"><span>销售额</span><strong>{format_num(row['sales_amount'], 2)} 元</strong></div>
                <div class="period-stat"><span>订单数</span><strong>{format_num(row['order_count'])}</strong></div>
                <div class="period-stat"><span>客单价</span><strong>{format_num(row['avg_order_value'], 2)} 元</strong></div>
                <div class="period-stat"><span>会员占比</span><strong>{format_num(row['member_ratio'] * 100, 1)}%</strong></div>
              </div>
              <div class="period-card-note">主销中类：{html.escape(str(row['top_category']))}</div>
            </article>
            """
        )
    return f"<div class='period-card-grid'>{''.join(cards_html)}</div>"


def build_period_page(metrics: dict, period_type: str) -> str:
    cards = metrics["summary_cards"]
    period_summary = build_period_summary(metrics, period_type)
    consulting_analysis = build_retail_consulting_analysis(metrics, period_type)
    latest = period_summary["latest"]
    peak = period_summary["peak"]
    product_sales = period_summary["product_sales"]
    member_rank = period_summary["member_rank"]
    category_highlight = period_summary["category_highlight"]
    vip_analysis = period_summary["vip_analysis"]
    guide_report = period_summary["guide_report"]
    store_month_report = period_summary["store_month_report"]
    retail_detail = period_summary["retail_detail"]
    profit = period_summary["profit"]
    charts = build_period_charts(period_summary, period_type)
    period_cards_html = build_period_cards(period_summary["rows"], period_type)
    period_label = "月度" if period_type == "monthly" else "季度"
    current_nav = "monthly.html" if period_type == "monthly" else "quarterly.html"
    other_period_nav = "quarterly.html" if period_type == "monthly" else "monthly.html"
    other_period_label = "季度" if period_type == "monthly" else "月度"

    metric_cards: list[tuple[str, str, str, str]] = []
    if latest:
        metric_cards.extend(
            [
                (f"最新{period_label}销售额", f"{format_num(latest['sales_amount'], 2)} 元", latest["label"], "neutral"),
                (f"最新{period_label}客单价", f"{format_num(latest['avg_order_value'], 2)} 元", "销售额 / 订单数", "neutral"),
                (
                    f"最新{period_label}会员占比",
                    f"{format_num(latest['member_ratio'] * 100, 1)}%",
                    "会员贡献",
                    "green" if latest["member_ratio"] >= 0.6 else "yellow" if latest["member_ratio"] >= 0.4 else "neutral",
                ),
            ]
        )
    metric_cards.append((f"平均{period_label}销售额", f"{format_num(period_summary['avg_sales'], 2)} 元", f"共 {len(period_summary['rows'])} 个{period_label}周期", "neutral"))
    if peak:
        metric_cards.append((f"峰值{period_label}", f"{peak['label']} / {format_num(peak['sales_amount'], 2)} 元", "当前统计范围内最高", "green"))
    metric_cards.append((f"{'月环比' if period_type == 'monthly' else '季环比'}", period_summary["delta_text"], "和上一周期相比", period_summary["delta_tone"]))

    if product_sales:
        metric_cards.append(
            (
                "跨季库存占比",
                f"{format_num(product_sales['cross_season_stock_share'] * 100, 1)}%",
                f"库存主要压在 {product_sales['top_stock_labels']}",
                "red" if product_sales["cross_season_stock_share"] >= 0.35 else "yellow" if product_sales["cross_season_stock_share"] >= 0.2 else "green",
            )
        )
    if member_rank:
        metric_cards.append(
            (
                "前10会员销额占比",
                f"{format_num(member_rank['top10_share'] * 100, 1)}%",
                member_rank["top_names"],
                "green" if member_rank["top10_share"] >= 0.25 else "neutral",
            )
        )
    if category_highlight:
        metric_cards.append(
            (
                "前两品类集中度",
                f"{format_num(category_highlight['top2_share'] * 100, 1)}%",
                category_highlight["top_category_names"],
                "red" if category_highlight["top2_share"] >= 0.7 else "yellow" if category_highlight["top2_share"] >= 0.55 else "green",
            )
        )
    if guide_report:
        metric_cards.append(
            (
                "店员销售集中度",
                f"{format_num(guide_report['top_guide_share'] * 100, 1)}%",
                f"主力导购 {guide_report['top_guide_name']}",
                "red" if guide_report["top_guide_share"] >= 0.5 else "yellow" if guide_report["top_guide_share"] >= 0.35 else "green",
            )
        )
    if vip_analysis:
        metric_cards.append(
            (
                "会员沉默占比",
                f"{format_num(vip_analysis['dormant_ratio'] * 100, 1)}%",
                f"近60天活跃 {format_num(vip_analysis['active_recent_count'])} 人",
                "red" if vip_analysis["dormant_ratio"] >= 0.35 else "yellow" if vip_analysis["dormant_ratio"] >= 0.2 else "green",
            )
        )
    if store_month_report:
        latest_joint = (
            store_month_report.get("latest_month")
            if period_type == "monthly"
            else store_month_report.get("latest_quarter")
        ) or {}
        if latest_joint:
            metric_cards.append(
                (
                    f"最近{period_label}件单比",
                    format_num(latest_joint.get("joint_rate", 0), 2),
                    f"低连带天数 {format_num(store_month_report.get('low_joint_days', 0))}",
                    "yellow" if latest_joint.get("joint_rate", 0) < 1.2 else "green",
                )
            )
    if retail_detail:
        metric_cards.append(
            (
                "实销折扣率",
                f"{format_num(retail_detail['weighted_discount_rate'] * 10, 1)} 折",
                retail_detail["discount_category_names"],
                "red"
                if retail_detail["weighted_discount_rate"] < 0.75
                else "yellow"
                if retail_detail["weighted_discount_rate"] < 0.82
                else "green",
            )
        )
    if profit and period_type == "monthly":
        metric_cards.append(
            (
                "当前保本进度",
                f"{format_num(profit['breakeven_progress_ratio'] * 100, 1)}%",
                profit["forecast_headline"],
                "green" if profit["passed_breakeven"] else "yellow",
            )
        )
    if profit:
        metric_cards.append(
            (
                "月末净利预测",
                f"{format_num(profit['projected_month_net_profit'], 2)} 元",
                "先看利润，再决定冲销售还是控补货",
                "green" if profit["projected_month_net_profit"] > 0 else "yellow" if profit["projected_month_gross_profit"] >= profit["total_expense"] * 0.9 else "red",
            )
        )

    metric_html = "".join(
        f"""
        <div class="metric-card metric-{level}">
          <div class="metric-title">{title}</div>
          <div class="metric-value">{value}</div>
          <div class="metric-note">{note}</div>
        </div>
        """
        for title, value, note, level in metric_cards
    )
    charts_html = "".join(f"<section class='chart-card'>{chart}</section>" for chart in charts) if charts else render_empty(f"当前还没有可展示的{period_label}图表。")
    guidance_html = "".join(f"<li>{html.escape(item)}</li>" for item in period_summary["guidance"])
    purchase_guidance_html = "".join(f"<li>{html.escape(item)}</li>" for item in period_summary["purchase_guidance"])
    support_cards: list[str] = []
    if latest:
        support_cards.append(
            f"""
            <article class="support-card">
              <h3>最新{period_label}主销中类</h3>
              <div class="support-value">{html.escape(str(latest['top_category']))}</div>
              <p>最新周期里，这个中类贡献最大，通常优先保障它的核心尺码和主色。</p>
            </article>
            """
        )
    if product_sales:
        support_cards.append(
            f"""
            <article class="support-card">
              <h3>商品动销提醒</h3>
              <div class="support-value">快销 {format_num(product_sales['fast_sellout_count'])} / 积压 {format_num(product_sales['backlog_count'])}</div>
              <p>售罄率 {format_num(product_sales['sellout_rate'] * 100, 1)}%，库存结构主要压在 {html.escape(product_sales['top_stock_labels'])}。</p>
            </article>
            """
        )
    if member_rank:
        support_cards.append(
            f"""
            <article class="support-card">
              <h3>会员经营提醒</h3>
              <div class="support-value">{html.escape(member_rank['top_names'])}</div>
              <p>前 10 位会员贡献 {format_num(member_rank['top10_share'] * 100, 1)}% 销额，适合做重点回访。</p>
            </article>
            """
        )
    if category_highlight:
        growth_rows = category_highlight.get("growth_rows") or []
        growth_text = "、".join(row["name"] for row in growth_rows[:3]) if growth_rows else "暂无明显增长品类"
        support_cards.append(
            f"""
            <article class="support-card">
              <h3>品类结构提醒</h3>
              <div class="support-value">{html.escape(category_highlight['top_category_names'])}</div>
              <p>前两品类集中度 {format_num(category_highlight['top2_share'] * 100, 1)}%，近期增长更快的是 {html.escape(growth_text)}。</p>
            </article>
            """
        )
    if vip_analysis:
        support_cards.append(
            f"""
            <article class="support-card">
              <h3>会员基盘提醒</h3>
              <div class="support-value">{format_num(vip_analysis['member_count'])} 位会员</div>
              <p>近 60 天活跃 {format_num(vip_analysis['active_recent_count'])} 位，沉默占比 {format_num(vip_analysis['dormant_ratio'] * 100, 1)}%。</p>
            </article>
            """
        )
    if guide_report:
        support_cards.append(
            f"""
            <article class="support-card">
              <h3>店员执行提醒</h3>
              <div class="support-value">{html.escape(guide_report['top_guide_name'])}</div>
              <p>销售占比 {format_num(guide_report['top_guide_share'] * 100, 1)}%，VIP 销售占比 {format_num(guide_report['vip_sales_share'] * 100, 1)}。</p>
            </article>
            """
        )
    if retail_detail:
        support_cards.append(
            f"""
            <article class="support-card">
              <h3>折扣与尺码提醒</h3>
              <div class="support-value">{format_num(retail_detail['weighted_discount_rate'] * 10, 1)} 折 / {html.escape(retail_detail['core_size_names'])}</div>
              <p>{html.escape(retail_detail['discount_category_names'])} 折扣依赖更明显，补货先保 {html.escape(retail_detail['core_size_names'])} 这些主销尺码。</p>
            </article>
            """
        )
    if period_summary["purchase_guidance"]:
        support_cards.append(
            f"""
            <article class="support-card">
              <h3>进货预算与顺序</h3>
              <div class="support-value">先保主销，再控折扣</div>
              <p>{html.escape(period_summary['purchase_guidance'][0])}</p>
            </article>
            """
        )
    if profit:
        support_cards.append(
            f"""
            <article class="support-card">
              <h3>利润与保本提醒</h3>
              <div class="support-value">{html.escape(profit['headline'])}</div>
              <p>总费用 {format_num(profit['total_expense'], 2)} 元，月末净利预测 {format_num(profit['projected_month_net_profit'], 2)} 元。当前更适合{'先稳利润和客单' if profit['projected_month_net_profit'] < 0 else '稳毛利放大主销'}。</p>
            </article>
            """
        )
    support_html = "".join(support_cards) if support_cards else render_empty("当前还没有足够的补充分析。")
    consulting_html = render_consulting_analysis_html(
        consulting_analysis,
        f"{period_label}经营分析与销售建议",
        "period-consulting",
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{cards['store_name']} {period_label}经营页</title>
  <style>
    :root {{
      color-scheme: light;
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; padding: 0; background: #f8fafc; color: #0f172a; font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", sans-serif; }}
    .page {{ max-width: 1440px; margin: 0 auto; padding: 18px; }}
    .top-nav {{ display:flex; justify-content:flex-start; margin-bottom:16px; }}
    .top-nav-links {{ display:flex; gap:10px; flex-wrap:wrap; }}
    .top-nav-link {{ display:inline-flex; align-items:center; justify-content:center; border-radius:999px; padding:9px 14px; font-size:13px; font-weight:800; color:#334155; background:#fff; border:1px solid #dbe4f0; text-decoration:none; }}
    .top-nav-link.is-active {{ background:#dbeafe; color:#1d4ed8; border-color:#bfdbfe; }}
    .hero {{ background:linear-gradient(135deg, #0f172a 0%, #1d4ed8 100%); color:#fff; padding:24px; border-radius:22px; box-shadow:0 18px 48px rgba(15, 23, 42, 0.18); margin-bottom:18px; }}
    .hero h1 {{ margin:0 0 10px; font-size:30px; line-height:1.25; }}
    .hero p {{ margin:0; line-height:1.8; opacity:0.95; }}
    .hero-note {{ margin-top:12px; font-size:13px; opacity:0.9; }}
    .hero-status {{ display:flex; gap:10px; flex-wrap:wrap; margin-top:12px; }}
    .hero-status-chip {{ display:inline-flex; align-items:center; justify-content:center; border-radius:999px; padding:8px 12px; font-size:12px; font-weight:700; background:rgba(255,255,255,0.12); border:1px solid rgba(255,255,255,0.2); }}
    .page-shell {{ display:grid; grid-template-columns:minmax(0,1fr) 250px; gap:18px; }}
    .main-column {{ min-width:0; }}
    .side-rail {{ display:flex; flex-direction:column; gap:16px; align-self:start; }}
    .rail-card {{ position:sticky; top:88px; background:#fff; border-radius:18px; padding:16px; box-shadow:0 10px 30px rgba(15,23,42,0.08); }}
    .rail-card h3 {{ margin:0 0 8px; font-size:17px; }}
    .rail-card p {{ margin:0 0 12px; font-size:12px; line-height:1.8; color:#64748b; }}
    .rail-links {{ display:flex; flex-direction:column; gap:8px; }}
    .rail-links a {{ display:block; text-decoration:none; color:#334155; background:#f8fafc; border:1px solid #e2e8f0; border-radius:14px; padding:10px 12px; font-size:13px; font-weight:700; }}
    .rail-links a.current {{ background:#dbeafe; border-color:#bfdbfe; color:#1d4ed8; }}
    .quick-nav {{ display:flex; gap:10px; flex-wrap:wrap; margin:12px 0 18px; }}
    .quick-nav a {{ text-decoration:none; color:#1d4ed8; background:#eff6ff; border:1px solid #bfdbfe; padding:8px 12px; border-radius:999px; font-size:13px; font-weight:700; white-space:nowrap; }}
    .module {{ background:#fff; border-radius:18px; box-shadow:0 10px 30px rgba(15,23,42,0.08); padding:18px; margin-bottom:18px; }}
    .module-header {{ display:flex; justify-content:space-between; align-items:baseline; gap:12px; margin-bottom:14px; flex-wrap:wrap; }}
    .module-title {{ margin:0; font-size:22px; }}
    .module-note {{ margin:0; font-size:13px; color:#64748b; line-height:1.8; }}
    .metrics-grid, .cards-grid, .support-grid, .period-card-grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(220px,1fr)); gap:14px; }}
    .metric-card, .support-card, .period-card, .chart-card {{ background:#fff; border:1px solid #e2e8f0; border-radius:16px; padding:16px; min-width:0; }}
    .metric-card {{ box-shadow:0 8px 24px rgba(15,23,42,0.06); }}
    .metric-title {{ font-size:14px; color:#64748b; margin-bottom:8px; }}
    .metric-value {{ font-size:28px; font-weight:800; margin-bottom:6px; color:#0f172a; line-height:1.3; }}
    .metric-note {{ font-size:13px; color:#64748b; line-height:1.7; }}
    .inline-tip {{
      display:inline-flex;
      align-items:center;
      justify-content:center;
      margin-left:6px;
      padding:1px 8px;
      border-radius:999px;
      border:1px solid #bfdbfe;
      background:#eff6ff;
      color:#1d4ed8;
      font-size:11px;
      font-weight:800;
      line-height:1.6;
      vertical-align:middle;
      white-space:nowrap;
    }}
    .metric-green {{ border-color:#bbf7d0; background:#f0fdf4; }}
    .metric-green .metric-value {{ color:#166534; }}
    .metric-yellow {{ border-color:#fde68a; background:#fffbeb; }}
    .metric-yellow .metric-value {{ color:#92400e; }}
    .metric-red {{ border-color:#fecaca; background:#fff7f7; }}
    .metric-red .metric-value {{ color:#991b1b; }}
    .overview-card {{ background:#fffdf7; border:1px solid #fde68a; border-radius:16px; padding:18px; }}
    .overview-headline {{ font-size:26px; font-weight:800; color:#92400e; margin:0 0 10px; line-height:1.35; }}
    .overview-summary {{ margin:0; font-size:14px; line-height:1.8; color:#5b4636; }}
    .guidance-list {{ margin:0; padding-left:18px; line-height:1.9; color:#334155; font-size:14px; }}
    .chart-card {{ overflow:hidden; }}
    .period-card-head {{ display:flex; justify-content:space-between; align-items:center; gap:10px; margin-bottom:12px; flex-wrap:wrap; }}
    .period-card-title {{ font-size:18px; font-weight:800; color:#0f172a; }}
    .period-card-note {{ margin-top:10px; font-size:12px; color:#64748b; line-height:1.7; }}
    .period-stat-grid {{ display:grid; gap:8px; }}
    .period-stat {{ display:flex; justify-content:space-between; align-items:center; gap:12px; font-size:14px; color:#475569; }}
    .period-stat strong {{ color:#0f172a; }}
    .support-card h3 {{ margin:0 0 8px; font-size:16px; }}
    .support-value {{ font-size:22px; font-weight:800; margin-bottom:8px; color:#0f172a; line-height:1.35; }}
    .support-card p {{ margin:0; font-size:13px; line-height:1.8; color:#64748b; }}
    .mini-chip {{ display:inline-flex; align-items:center; border-radius:999px; padding:6px 12px; font-size:12px; font-weight:700; white-space:nowrap; }}
    .mini-chip-neutral, .mini-chip-soft {{ background:#f1f5f9; color:#334155; }}
    .mini-chip-green {{ background:#dcfce7; color:#166534; }}
    .mini-chip-yellow {{ background:#fef3c7; color:#92400e; }}
    .mini-chip-red {{ background:#fee2e2; color:#991b1b; }}
    .empty-card {{ border:1px dashed #cbd5e1; border-radius:16px; padding:20px; color:#64748b; background:#f8fafc; font-size:14px; line-height:1.8; }}
    .analysis-grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(260px, 1fr)); gap:14px; }}
    .analysis-card {{ background:#ffffff; border:1px solid #e2e8f0; border-radius:16px; padding:16px; min-width:0; }}
    .analysis-card h3 {{ margin:0 0 10px; font-size:17px; color:#0f172a; }}
    .analysis-list {{ margin:0; padding-left:18px; color:#334155; font-size:14px; line-height:1.9; }}
    .priority-red {{ background:#fff7f7; border-color:#fecaca; }}
    .priority-yellow {{ background:#fffbeb; border-color:#fde68a; }}
    .priority-neutral {{ background:#f8fafc; border-color:#cbd5e1; }}
    .priority-green {{ background:#f0fdf4; border-color:#bbf7d0; }}
    @media (max-width: 960px) {{
      .page-shell {{ grid-template-columns:1fr; }}
      .rail-card {{ position:static; }}
      .rail-links {{ display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); }}
    }}
    @media (max-width: 640px) {{
      .page {{ padding:12px; }}
      .hero {{ padding:18px; border-radius:16px; }}
      .hero h1 {{ font-size:24px; }}
      .hero-status-chip, .top-nav-link {{ width:100%; }}
      .top-nav-links {{ width:100%; }}
      .quick-nav {{ flex-wrap:nowrap; overflow-x:auto; -webkit-overflow-scrolling:touch; padding-bottom:2px; }}
      .module {{ padding:14px; margin-bottom:14px; }}
      .overview-headline {{ font-size:22px; }}
      .metric-value {{ font-size:24px; }}
      .rail-links {{ grid-template-columns:1fr; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <nav class="top-nav">
      <div class="top-nav-links">
        <a class="top-nav-link" href="../index.html">首页</a>
        <a class="top-nav-link" href="./index.html">仪表盘</a>
        <a class="top-nav-link" href="./details.html">详细页</a>
        <a class="top-nav-link" href="./relationship.html">库存销售关系页</a>
        <a class="top-nav-link {'is-active' if period_type == 'monthly' else ''}" href="./monthly.html">月度页</a>
        <a class="top-nav-link {'is-active' if period_type == 'quarterly' else ''}" href="./quarterly.html">季度页</a>
        <a class="top-nav-link" href="../manuals/index.html">文档中心</a>
        <a class="top-nav-link" href="../costs/index.html">成本维护台</a>
      </div>
    </nav>
    <section class="hero">
      <h1>{cards['store_name']} {period_label}经营页</h1>
      <p>这里专门看 {period_label}趋势、结构和建议。首页负责今天先做什么，这里负责判断这个月或这个季度整体方向对不对。</p>
      <div class="hero-note">{period_summary['overview_text']}</div>
      <div class="hero-status">
        <div class="hero-status-chip">最近抓取日期：{pd.Timestamp(cards['data_capture_at']).strftime('%Y-%m-%d')}（北京时间）</div>
        <div class="hero-status-chip">当前季节：{cards['current_season_name']} / {cards['phase_name']}</div>
      </div>
    </section>
    <div class="page-shell">
      <div class="main-column">
        <nav class="quick-nav">
          <a href="#period-overview">总览</a>
          <a href="#period-metrics">核心统计</a>
          <a href="#period-charts">趋势图表</a>
          <a href="#period-cards">阶段明细</a>
          <a href="#period-guidance">经营建议</a>
          <a href="#period-consulting">经营分析</a>
          <a href="#period-purchase">进货建议</a>
        </nav>
        <section class="module" id="period-overview">
          <div class="module-header">
            <h2 class="module-title">{period_label}总览</h2>
            <p class="module-note">根据全量销售、当前库存结构、会员贡献和利润保本状态，自动给出这一阶段的经营判断。</p>
          </div>
          <div class="overview-card">
            <div class="overview-headline">{period_summary['delta_text'] if latest else '等待数据'}</div>
            <p class="overview-summary">{period_summary['overview_text']}</p>
          </div>
        </section>
        <section class="module" id="period-metrics">
          <div class="module-header">
            <h2 class="module-title">核心统计</h2>
            <p class="module-note">先看这一阶段卖得怎么样、会员贡献如何、库存压力有没有跟着变化。</p>
          </div>
          <div class="metrics-grid">{metric_html}</div>
        </section>
        <section class="module" id="period-charts">
          <div class="module-header">
            <h2 class="module-title">趋势图表</h2>
            <p class="module-note">销售额、订单数、客单价和会员占比放在一起看，更容易判断阶段节奏。</p>
          </div>
          <div class="cards-grid">{charts_html}</div>
        </section>
        <section class="module" id="period-cards">
          <div class="module-header">
            <h2 class="module-title">阶段明细</h2>
            <p class="module-note">最近 6 个{'月' if period_type == 'monthly' else '季度'}放成卡片，更方便快速对比。</p>
          </div>
          {period_cards_html}
        </section>
        <section class="module" id="period-guidance">
          <div class="module-header">
            <h2 class="module-title">经营建议</h2>
            <p class="module-note">建议会结合销售趋势、库存动态、会员贡献和利润保本状态自动变化。</p>
          </div>
          <ul class="guidance-list">{guidance_html}</ul>
          <div class="support-grid" style="margin-top:16px;">{support_html}</div>
        </section>
        {consulting_html}
        <section class="module" id="period-purchase">
          <div class="module-header">
            <h2 class="module-title">{period_label}进货建议</h2>
            <p class="module-note">这里专门看销售、补货和库存之间的关系，帮助老板决定这个月或这个季度该怎么进货。</p>
          </div>
          <ul class="guidance-list">{purchase_guidance_html}</ul>
        </section>
      </div>
      <aside class="side-rail">
        <section class="rail-card">
          <h3>常用导航</h3>
          <p>固定入口放这里，老板看完趋势页可以直接跳回首页、仪表盘或详细页。</p>
          <div class="rail-links">
            <a href="../index.html">返回首页</a>
            <a href="./index.html">进入仪表盘</a>
            <a href="./details.html">进入详细页</a>
            <a href="./relationship.html">进入关系页</a>
            <a class="current" href="./{current_nav}">当前{period_label}页</a>
            <a href="./{other_period_nav}">进入{other_period_label}页</a>
          </div>
        </section>
        <section class="rail-card">
          <h3>本页定位</h3>
          <p>如果只想快速看某一块，点这里直接跳，不用整页来回找。</p>
          <div class="rail-links">
            <a href="#period-overview">{period_label}总览</a>
            <a href="#period-metrics">核心统计</a>
            <a href="#period-charts">趋势图表</a>
            <a href="#period-cards">阶段明细</a>
            <a href="#period-guidance">经营建议</a>
            <a href="#period-consulting">经营分析</a>
            <a href="#period-purchase">进货建议</a>
          </div>
        </section>
      </aside>
    </div>
  </div>
</body>
</html>
"""


def build_inventory_sales_relationship(metrics: dict) -> dict[str, object]:
    cards = metrics["summary_cards"]
    actions = metrics["action_summary"]
    decision = build_decision_engine(metrics)
    time_strategy = build_time_strategy(metrics)
    profit = cards.get("profit_snapshot")
    category_risks = metrics.get("category_risks", pd.DataFrame()).copy()
    replenish_categories = metrics.get("replenish_categories", pd.DataFrame()).copy()
    clearance_categories = metrics.get("clearance_categories", pd.DataFrame()).copy()
    quality_checks = metrics.get("quality_checks", pd.DataFrame()).copy()

    sales_trend = decision["sales_trend"]
    top_category_risk = category_risks.iloc[0] if not category_risks.empty else None
    top_replenish = replenish_categories.iloc[0] if not replenish_categories.empty else None
    top_clearance = clearance_categories.iloc[0] if not clearance_categories.empty else None

    if cards["negative_sku_count"] >= 30:
        tone = "red"
        mode = "库存口径先纠偏"
        headline = "库存和销售关系先别急着下结论，先校库存。"
    elif cards["estimated_inventory_days"] >= 180 and sales_trend["direction"] != "up":
        tone = "red"
        mode = "库存压销售"
        headline = "库存明显压过销售，先去库存再谈放量。"
    elif actions["replenish_count"] >= 100 and cards["estimated_inventory_days"] < 180:
        tone = "yellow"
        mode = "销售在跑但结构偏紧"
        headline = "主销还在跑，先保不断码，同时别让慢销库存继续堆高。"
    elif actions["high_risk_category_count"] > 0 or actions["clearance_count"] >= 80:
        tone = "yellow"
        mode = "结构失衡"
        headline = "不是没销量，而是库存和销售结构还没对齐。"
    else:
        tone = "green"
        mode = "关系相对平衡"
        headline = "库存和销售关系整体可控，重点做结构优化。"

    summary_parts = [
        f"近 {cards['sales_days']} 天经营销售额 {format_num(cards['sales_amount'], 2)} 元，",
        f"当前经营库存额 {format_num(cards['inventory_amount'], 2)} 元，",
        f"库存覆盖天数约 {format_num(cards['estimated_inventory_days'], 1)} 天。",
    ]
    if top_category_risk is not None:
        summary_parts.append(
            f" 当前最需要盯的压货品类是 {top_category_risk['大类']}，库存金额/销售金额约 {format_num(top_category_risk['库存金额/销售金额'], 2)}。"
        )
    if top_replenish is not None:
        summary_parts.append(
            f" 补货机会先看 {top_replenish['中类']}，建议补货量约 {format_num(top_replenish['建议补货量'])}。"
        )
    if top_clearance is not None:
        summary_parts.append(
            f" 去化先盯 {top_clearance['大类']}，当前实际库存约 {format_num(top_clearance['实际库存'])}。"
        )
    summary = "".join(summary_parts)

    metric_cards = [
        {
            "title": "近段经营销售额",
            "value": f"{format_num(cards['sales_amount'], 2)} 元",
            "note": f"近 {cards['sales_days']} 天，直接来自校准销售主表。",
            "tone": "neutral",
            "value_type": "直接观察",
        },
        {
            "title": "当前经营库存额",
            "value": f"{format_num(cards['inventory_amount'], 2)} 元",
            "note": "来自最新库存快照，当前仍是零售价口径库存额。",
            "tone": "neutral",
            "value_type": "直接观察",
        },
        {
            "title": "库存覆盖天数",
            "value": f"{format_num(cards['estimated_inventory_days'], 1)} 天",
            "note": "用最近销售速度估算库存还能卖多久。",
            "tone": tone,
            "value_type": "估算",
        },
        {
            "title": "高压货品类数",
            "value": format_num(actions["high_risk_category_count"]),
            "note": "库存金额明显高于销售金额的品类数量。",
            "tone": "red" if actions["high_risk_category_count"] > 0 else "green",
            "value_type": "估算",
        },
        {
            "title": "建议补货 SKU",
            "value": format_num(actions["replenish_count"]),
            "note": "卖得动但库存偏浅，先保不断码。",
            "tone": "yellow" if actions["replenish_count"] > 0 else "neutral",
            "value_type": "估算",
        },
        {
            "title": "建议去化 SKU",
            "value": format_num(actions["clearance_count"]),
            "note": "库存高、近期卖得慢，先停补再去化。",
            "tone": "red" if actions["clearance_count"] > 0 else "green",
            "value_type": "估算",
        },
        {
            "title": "负库存 SKU",
            "value": format_num(cards["negative_sku_count"]),
            "note": "账货不一致会直接扭曲补货和去化判断。",
            "tone": "red" if cards["negative_sku_count"] > 0 else "green",
            "value_type": "直接观察",
        },
    ]
    if profit:
        metric_cards.append(
            {
                "title": "月末净利预测",
                "value": f"{format_num(profit['projected_month_net_profit'], 2)} 元",
                "note": "库存动作要同时兼顾利润和保本节奏。",
                "tone": "green" if profit["projected_month_net_profit"] > 0 else "red",
                "value_type": "预测",
            }
        )

    findings: list[dict[str, str]] = [
        {
            "value_type": "估算",
            "tone": tone,
            "title": "整体库存覆盖",
            "conclusion": headline,
            "evidence": (
                f"最近销售趋势为 {sales_trend['label']}，当前库存覆盖 {format_num(cards['estimated_inventory_days'], 1)} 天，"
                f"经营库存额 {format_num(cards['inventory_amount'], 2)} 元。"
            ),
            "action": (
                "先盯高压货和负库存，再决定补货节奏。"
                if cards["estimated_inventory_days"] >= 180
                else "先保主销不断码，再按周复盘库存结构。"
            ),
        }
    ]
    if top_category_risk is not None:
        findings.append(
            {
                "value_type": "直接观察",
                "tone": "red" if str(top_category_risk["状态"]) == "高压货" else "yellow",
                "title": "压货最重的品类",
                "conclusion": f"{top_category_risk['大类']} 当前最需要先处理。",
                "evidence": (
                    f"库存金额/销售金额 {format_num(top_category_risk['库存金额/销售金额'], 2)}，"
                    f"库存量/销售量 {format_num(top_category_risk['库存量/销售量'], 2)}。"
                ),
                "action": "先停补、看货位、做组合去化，再决定是否恢复补货。",
            }
        )
    if top_replenish is not None:
        findings.append(
            {
                "value_type": "估算",
                "tone": "yellow",
                "title": "补货机会",
                "conclusion": f"{top_replenish['中类']} 还在跑量，先保不断码。",
                "evidence": (
                    f"当前建议补货量约 {format_num(top_replenish['建议补货量'])}，"
                    f"对应销售额约 {format_num(top_replenish['销售额'], 2)} 元。"
                ),
                "action": "先补核心尺码和主销色，不要把补货预算平均铺开。",
            }
        )
    if top_clearance is not None:
        findings.append(
            {
                "value_type": "估算",
                "tone": "red",
                "title": "去化压力",
                "conclusion": f"{top_clearance['大类']} 更适合先去化，不适合继续深补。",
                "evidence": (
                    f"当前去化清单里约 {format_num(top_clearance['SKU数'])} 个 SKU，"
                    f"实际库存约 {format_num(top_clearance['实际库存'])}，近期零售约 {format_num(top_clearance['近期零售'])}。"
                ),
                "action": "今天先做陈列前移和组合促销，把预算让给主销品类。",
            }
        )
    if cards["negative_sku_count"] > 0:
        findings.append(
            {
                "value_type": "直接观察",
                "tone": "red",
                "title": "库存口径风险",
                "conclusion": "负库存会让库存和销售关系判断失真。",
                "evidence": (
                    f"当前负库存 SKU {format_num(cards['negative_sku_count'])} 个，"
                    f"负库存金额约 {format_num(cards['negative_inventory_amount'], 2)} 元。"
                ),
                "action": "先查账、查盘点、查调拨，再执行补货和去化。",
            }
        )
    if profit:
        findings.append(
            {
                "value_type": "预测",
                "tone": "red" if profit["projected_month_net_profit"] < 0 else "green",
                "title": "利润约束",
                "conclusion": (
                    "当前库存动作要优先服务利润，不适合靠深折扣硬撑。"
                    if profit["projected_month_net_profit"] < 0
                    else "利润口径已相对可控，可以在守毛利前提下保主销。"
                ),
                "evidence": (
                    f"当前总费用约 {format_num(profit['total_expense'], 2)} 元，"
                    f"月末净利预测约 {format_num(profit['projected_month_net_profit'], 2)} 元。"
                ),
                "action": (
                    "先保高毛利主销和快周转，再决定活动和补货预算。"
                    if profit["projected_month_net_profit"] < 0
                    else "主销可以更主动快返，但仍然别平均补货。"
                ),
            }
        )

    category_matrix = category_risks.copy()
    if not category_matrix.empty:
        category_matrix["关系判断"] = category_matrix.apply(
            lambda row: (
                "库存明显压销售"
                if safe_float(row.get("库存金额/销售金额")) >= 3
                else "库存偏重"
                if safe_float(row.get("库存金额/销售金额")) >= 1.5
                else "销售快于库存"
                if safe_float(row.get("库存金额/销售金额")) < 0.8 and safe_float(row.get("零售额")) > 0
                else "库存与销售相对平衡"
            ),
            axis=1,
        )
        category_matrix["建议动作"] = category_matrix.apply(
            lambda row: (
                "先停补再去化"
                if safe_float(row.get("库存金额/销售金额")) >= 3
                else "观察并做组合去化"
                if safe_float(row.get("库存金额/销售金额")) >= 1.5
                else "优先补货"
                if safe_float(row.get("库存金额/销售金额")) < 0.8 and safe_float(row.get("零售额")) > 0
                else "暂缓补货"
            ),
            axis=1,
        )
        category_matrix = category_matrix[
            ["大类", "零售额", "库存额", "库存金额/销售金额", "库存量/销售量", "状态", "关系判断", "建议动作"]
        ].copy()

    quality_warning_map = {
        "retail_validation_tail_gap_days": "店铺零售校验尾段缺口",
        "movement_has_sku_detail": "出入库缺少 SKU 行级明细",
        "master_vs_store_retail_daily": "主表与店铺零售按天校验",
        "master_vs_store_retail_orders": "主表与店铺零售按订单校验",
        "master_vs_product_core_amount": "主表与商品销售累计销额校验",
        "master_vs_product_core_qty": "主表与商品销售累计销量校验",
        "master_vs_flow_orders": "主表与每日流水按订单校验",
    }
    quality_alerts: list[str] = []
    if not quality_checks.empty and {"check_name", "status", "observed_value"}.issubset(quality_checks.columns):
        warning_rows = quality_checks[quality_checks["status"].astype(str).isin(["warning", "fail"])].copy()
        for _, row in warning_rows.head(5).iterrows():
            check_name = quality_warning_map.get(str(row["check_name"]), str(row["check_name"]))
            observed = str(row.get("observed_value", "") or "").strip()
            quality_alerts.append(f"{check_name}：{observed or '需人工复核'}")

    data_basis = {
        "direct": [
            f"近 {cards['sales_days']} 天经营销售额、订单数和客单价来自 SQLite 校准销售主表。",
            "当前库存额、库存量、库存金额/销售金额来自最新库存与库存零售快照。",
            "负库存、去化清单、慢销清单都来自最新库存和进销存快照的直接结果。",
        ],
        "estimated": [
            "库存覆盖天数是按最近销售速度估算的，不是未来实际销量承诺。",
            "补货、去化、跨季处理属于规则型建议，适合当经营决策参考，不是自动下单结果。",
            "品类关系判断是把销售和库存放在同一个画面里做结构解释，方便老板优先级排序。",
        ],
        "forecast": [
            (
                f"当前月末净利预测约 {format_num(profit['projected_month_net_profit'], 2)} 元，"
                "这里只用于提醒库存动作要不要更保守。"
                if profit
                else "本页不单独输出销量预测，主要基于当前库存与销售关系给动作建议。"
            )
        ],
        "caveats": quality_alerts
        or [
            "库存金额当前还是零售价口径，不是进货成本口径。",
            "出入库单据还没有 SKU 行级明细，所以库存原因解释仍然有盲区。",
        ],
    }

    recommendations = [
        {
            "title": "今天先做什么",
            "tone": "red" if tone == "red" else "yellow",
            "items": dedupe_preserve_order(
                [
                    (
                        "先纠偏负库存和断码，再看补货与去化。"
                        if cards["negative_sku_count"] > 0
                        else "先看去化重点品类和低库存畅销款。"
                    )
                ]
                + list(time_strategy["daily_actions"])
            )[:4],
        },
        {
            "title": "未来 7 天重点",
            "tone": "yellow",
            "items": dedupe_preserve_order(
                [
                    (
                        f"本周重点盯 {top_category_risk['大类']} 的库存压力。"
                        if top_category_risk is not None
                        else "本周继续按品类复盘库存和销售关系。"
                    )
                ]
                + list(time_strategy["weekly_actions"])
            )[:4],
        },
        {
            "title": "未来 30 天重点",
            "tone": "green" if tone == "green" else "yellow",
            "items": dedupe_preserve_order(
                [
                    (
                        "本月目标是把库存结构拉回到更适合当前销售节奏的位置。"
                        if cards["estimated_inventory_days"] >= 120
                        else "本月目标是稳住主销库存结构，同时避免慢销货继续堆高。"
                    )
                ]
                + list(time_strategy["monthly_actions"])
            )[:4],
        },
    ]

    return {
        "mode": mode,
        "tone": tone,
        "headline": headline,
        "summary": summary,
        "metric_cards": metric_cards,
        "findings": findings[:5],
        "recommendations": recommendations,
        "category_matrix": category_matrix.fillna("").to_dict(orient="records") if not category_matrix.empty else [],
        "top_risk_category": str(top_category_risk["大类"]) if top_category_risk is not None else "",
        "top_replenish_category": str(top_replenish["中类"]) if top_replenish is not None else "",
        "top_clearance_category": str(top_clearance["大类"]) if top_clearance is not None else "",
        "data_basis": data_basis,
    }


def build_inventory_sales_charts(metrics: dict) -> list[str]:
    charts: list[str] = []
    category_risks = metrics.get("category_risks", pd.DataFrame()).head(10).copy()
    color_map = {
        "高压货": "#dc2626",
        "需关注": "#f59e0b",
        "相对健康": "#16a34a",
    }

    if not category_risks.empty:
        marker_sizes = [
            max(18.0, min(46.0, 14.0 + safe_float(value) * 8.0))
            for value in category_risks["库存金额/销售金额"].tolist()
        ]
        marker_colors = [color_map.get(str(value), "#2563eb") for value in category_risks["状态"].tolist()]
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=category_risks["零售额"],
                y=category_risks["库存额"],
                mode="markers+text",
                text=category_risks["大类"],
                textposition="top center",
                marker=dict(
                    size=marker_sizes,
                    color=marker_colors,
                    opacity=0.82,
                    line=dict(color="#ffffff", width=1.5),
                ),
                hovertemplate=(
                    "<b>%{text}</b><br>"
                    "销售额：%{x:.2f}<br>"
                    "库存额：%{y:.2f}<br>"
                    "库存金额/销售金额：%{customdata[0]:.2f}<br>"
                    "库存量/销售量：%{customdata[1]:.2f}<br>"
                    "状态：%{customdata[2]}<extra></extra>"
                ),
                customdata=category_risks[["库存金额/销售金额", "库存量/销售量", "状态"]].to_numpy(),
                name="品类关系",
            )
        )
        fig.update_layout(
            title="品类库存额 vs 销售额",
            height=420,
            margin=dict(l=20, r=20, t=60, b=20),
            xaxis_title="销售额",
            yaxis_title="库存额",
        )
        charts.append(fig_to_html(fig, include_js=True))

        ratio_frame = category_risks.sort_values("库存金额/销售金额", ascending=True)
        fig2 = go.Figure(
            go.Bar(
                x=ratio_frame["库存金额/销售金额"],
                y=ratio_frame["大类"],
                orientation="h",
                marker_color=[color_map.get(str(value), "#2563eb") for value in ratio_frame["状态"].tolist()],
                text=[format_num(value, 2) for value in ratio_frame["库存金额/销售金额"].tolist()],
                textposition="outside",
                hovertemplate=(
                    "<b>%{y}</b><br>库存金额/销售金额：%{x:.2f}<br>"
                    "<extra></extra>"
                ),
            )
        )
        fig2.update_layout(
            title="品类库存金额/销售金额排序",
            height=420,
            margin=dict(l=20, r=40, t=60, b=20),
            xaxis_title="库存金额 / 销售金额",
            yaxis_title="品类",
        )
        charts.append(fig_to_html(fig2))

    action_frame = pd.DataFrame(
        [
            {"维度": "建议补货 SKU", "数量": metrics["action_summary"]["replenish_count"], "颜色": "#f59e0b"},
            {"维度": "建议去化 SKU", "数量": metrics["action_summary"]["clearance_count"], "颜色": "#dc2626"},
            {"维度": "跨季处理 SKU", "数量": metrics["action_summary"]["seasonal_hold_count"], "颜色": "#2563eb"},
            {"维度": "负库存 SKU", "数量": metrics["summary_cards"]["negative_sku_count"], "颜色": "#7c3aed"},
        ]
    )
    if not action_frame.empty:
        fig3 = go.Figure(
            go.Bar(
                x=action_frame["维度"],
                y=action_frame["数量"],
                marker_color=action_frame["颜色"],
                text=[format_num(value) for value in action_frame["数量"].tolist()],
                textposition="outside",
            )
        )
        fig3.update_layout(
            title="库存与销售关系的动作数量分布",
            height=360,
            margin=dict(l=20, r=20, t=60, b=40),
            yaxis_title="数量",
        )
        charts.append(fig_to_html(fig3))

    return charts


def build_relationship_html(metrics: dict) -> str:
    cards = metrics["summary_cards"]
    relationship = build_inventory_sales_relationship(metrics)
    charts = build_inventory_sales_charts(metrics)
    category_matrix = pd.DataFrame(relationship["category_matrix"])
    replenish_category_table = metrics["replenish_categories"][
        ["中类", "季节策略", "SKU数", "销售额", "库存", "建议补货量", "补货原则", "主销尺码"]
    ].copy()
    clearance_category_table = metrics["clearance_categories"][
        ["大类", "建议动作", "SKU数", "实际库存", "近期零售"]
    ].copy()
    low_stock_table = metrics["low_stock_bestsellers"][
        ["款号", "颜色", "中类", "季节", "销售数", "销售金额", "库存", "周期售罄"]
    ].copy()
    slow_moving_table = metrics["slow_moving"][
        ["商品款号", "商品名称", "大类", "中类", "实际库存", "近期零售", "动销率", "零售价"]
    ].copy()
    negative_table = metrics["negative_inventory"].copy()

    if not slow_moving_table.empty and "商品名称" in slow_moving_table.columns:
        slow_moving_table["商品名称"] = slow_moving_table["商品名称"].apply(
            lambda value: table_text_with_tip(value, 10, "详情")
        )

    metric_html = "".join(
        f"""
        <div class="metric-card metric-{item['tone']}">
          <div class="metric-meta">{item['value_type']}</div>
          <div class="metric-title">{item['title']}</div>
          <div class="metric-value">{item['value']}</div>
          <div class="metric-note">{item['note']}</div>
        </div>
        """
        for item in relationship["metric_cards"]
    )
    finding_html = "".join(
        f"""
        <article class="finding-card finding-{item['tone']}">
          <div class="finding-top">
            <span class="mini-chip mini-chip-{item['tone']}">{html.escape(item['value_type'])}</span>
            <h3>{html.escape(item['title'])}</h3>
          </div>
          <p class="finding-conclusion">{html.escape(item['conclusion'])}</p>
          <p class="finding-text"><strong>证据：</strong>{html.escape(item['evidence'])}</p>
          <p class="finding-text"><strong>建议动作：</strong>{html.escape(item['action'])}</p>
        </article>
        """
        for item in relationship["findings"]
    ) or render_empty("当前还没有可展示的关系结论。")
    recommendation_html = "".join(
        f"""
        <article class="analysis-card priority-{item['tone']}">
          <h3>{html.escape(item['title'])}</h3>
          <ul class="analysis-list">
            {"".join(f"<li>{html.escape(entry)}</li>" for entry in item['items'])}
          </ul>
        </article>
        """
        for item in relationship["recommendations"]
    )
    chart_html = "".join(f"<section class='chart-card'>{chart}</section>" for chart in charts) or render_empty("当前还没有可展示的库存-销售关系图表。")

    category_matrix_html = (
        table_html(
            category_matrix,
            "库存和销售关系总表",
            12,
            "先看库存金额/销售金额，再看关系判断和建议动作，老板可以先按品类定优先级。",
        )
        if not category_matrix.empty
        else render_empty("当前还没有可展示的库存和销售关系总表。")
    )
    detail_tables_html = "".join(
        [
            category_matrix_html,
            table_html(
                replenish_category_table,
                "补货重点品类",
                12,
                "这些品类说明销售还在跑，但库存已经偏浅，先保主销不断码。",
            ),
            table_html(
                clearance_category_table,
                "去化重点品类",
                12,
                "这些品类说明库存承压更明显，先停补、再看陈列和组合去化。",
            ),
            table_html(
                low_stock_table,
                "低库存畅销款",
                14,
                "这里适合老板或店员直接挑具体款，优先保销量高、库存浅的 SKU。",
            ),
            table_html(
                slow_moving_table,
                "高库存慢销款",
                14,
                "这里先看实际库存和近期零售，再决定清货位、组合价还是暂缓补货。",
            ),
            table_html(
                negative_table,
                "负库存异常清单",
                12,
                "先查账、查盘点、查调拨。这个问题不先处理，库存和销售关系就会继续失真。",
            ),
        ]
    )
    data_basis_html = "".join(
        f"""
        <article class="analysis-card">
          <h3>{html.escape(title)}</h3>
          <ul class="analysis-list">
            {"".join(f"<li>{html.escape(item)}</li>" for item in values)}
          </ul>
        </article>
        """
        for title, values in [
            ("直接观察", relationship["data_basis"]["direct"]),
            ("估算口径", relationship["data_basis"]["estimated"]),
            ("预测口径", relationship["data_basis"]["forecast"]),
            ("提醒与缺口", relationship["data_basis"]["caveats"]),
        ]
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{cards['store_name']} 库存和销售关系页</title>
  <style>
    :root {{
      color-scheme: light;
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ margin:0; padding:0; background:#f8fafc; color:#0f172a; font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    body {{ line-height:1.7; }}
    .page {{ max-width:1440px; margin:0 auto; padding:18px; }}
    .top-nav {{ display:flex; justify-content:flex-start; margin-bottom:16px; }}
    .top-nav-links {{ display:flex; gap:10px; flex-wrap:wrap; }}
    .top-nav-link {{ display:inline-flex; align-items:center; justify-content:center; border-radius:999px; padding:9px 14px; font-size:13px; font-weight:800; color:#334155; background:#fff; border:1px solid #dbe4f0; text-decoration:none; }}
    .top-nav-link.is-active {{ background:#dbeafe; color:#1d4ed8; border-color:#bfdbfe; }}
    .hero {{ background:linear-gradient(135deg, #0f172a 0%, #0f766e 100%); color:#fff; padding:24px; border-radius:22px; box-shadow:0 18px 48px rgba(15, 23, 42, 0.18); margin-bottom:18px; }}
    .hero h1 {{ margin:0 0 10px; font-size:30px; line-height:1.25; }}
    .hero p {{ margin:0; opacity:0.96; }}
    .hero-note {{ margin-top:12px; font-size:13px; opacity:0.88; }}
    .hero-status {{ display:flex; gap:10px; flex-wrap:wrap; margin-top:14px; }}
    .hero-status-chip {{ display:inline-flex; align-items:center; justify-content:center; border-radius:999px; padding:8px 12px; font-size:12px; font-weight:700; background:rgba(255,255,255,0.12); border:1px solid rgba(255,255,255,0.18); }}
    .page-shell {{ display:grid; grid-template-columns:minmax(0, 1fr) 260px; gap:18px; }}
    .main-column {{ min-width:0; }}
    .side-rail {{ display:flex; flex-direction:column; gap:16px; align-self:start; }}
    .rail-card {{ position:sticky; top:88px; background:#fff; border-radius:18px; padding:16px; box-shadow:0 10px 30px rgba(15,23,42,0.08); }}
    .rail-card h3 {{ margin:0 0 8px; font-size:17px; }}
    .rail-card p {{ margin:0 0 12px; font-size:12px; line-height:1.8; color:#64748b; }}
    .rail-links {{ display:flex; flex-direction:column; gap:8px; }}
    .rail-links a {{ display:block; text-decoration:none; color:#334155; background:#f8fafc; border:1px solid #e2e8f0; border-radius:14px; padding:10px 12px; font-size:13px; font-weight:700; }}
    .rail-links a.current {{ background:#dbeafe; border-color:#bfdbfe; color:#1d4ed8; }}
    .quick-nav {{ display:flex; gap:10px; flex-wrap:wrap; margin:12px 0 18px; }}
    .quick-nav a {{ text-decoration:none; color:#1d4ed8; background:#eff6ff; border:1px solid #bfdbfe; padding:8px 12px; border-radius:999px; font-size:13px; font-weight:700; white-space:nowrap; }}
    .module {{ background:#fff; border-radius:18px; box-shadow:0 10px 30px rgba(15,23,42,0.08); padding:18px; margin-bottom:18px; }}
    .module-header {{ display:flex; justify-content:space-between; align-items:baseline; gap:12px; margin-bottom:14px; flex-wrap:wrap; }}
    .module-title {{ margin:0; font-size:22px; }}
    .module-note {{ margin:0; font-size:13px; color:#64748b; line-height:1.8; }}
    .overview-card {{ background:#fffdf7; border:1px solid #fde68a; border-radius:16px; padding:18px; }}
    .overview-headline {{ font-size:26px; font-weight:800; color:#92400e; margin:0 0 10px; line-height:1.35; }}
    .overview-summary {{ margin:0; font-size:14px; line-height:1.8; color:#5b4636; }}
    .metrics-grid, .analysis-grid, .findings-grid, .cards-grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); gap:14px; }}
    .metric-card, .analysis-card, .finding-card, .chart-card {{ background:#fff; border:1px solid #e2e8f0; border-radius:16px; padding:16px; min-width:0; }}
    .metric-card {{ box-shadow:0 8px 24px rgba(15,23,42,0.06); }}
    .metric-meta {{ font-size:11px; font-weight:800; letter-spacing:0.04em; text-transform:uppercase; color:#2563eb; margin-bottom:8px; }}
    .metric-title {{ font-size:14px; color:#64748b; margin-bottom:8px; }}
    .metric-value {{ font-size:28px; font-weight:800; margin-bottom:6px; color:#0f172a; line-height:1.3; }}
    .metric-note {{ font-size:13px; color:#64748b; line-height:1.7; }}
    .metric-green {{ border-color:#bbf7d0; background:#f0fdf4; }}
    .metric-green .metric-value {{ color:#166534; }}
    .metric-yellow {{ border-color:#fde68a; background:#fffbeb; }}
    .metric-yellow .metric-value {{ color:#92400e; }}
    .metric-red {{ border-color:#fecaca; background:#fff7f7; }}
    .metric-red .metric-value {{ color:#991b1b; }}
    .analysis-card h3, .finding-card h3 {{ margin:0; font-size:17px; color:#0f172a; }}
    .analysis-list {{ margin:0; padding-left:18px; color:#334155; font-size:14px; line-height:1.9; }}
    .priority-red {{ background:#fff7f7; border-color:#fecaca; }}
    .priority-yellow {{ background:#fffbeb; border-color:#fde68a; }}
    .priority-green {{ background:#f0fdf4; border-color:#bbf7d0; }}
    .finding-red {{ background:#fff7f7; border-color:#fecaca; }}
    .finding-yellow {{ background:#fffbeb; border-color:#fde68a; }}
    .finding-green {{ background:#f0fdf4; border-color:#bbf7d0; }}
    .finding-top {{ display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:10px; }}
    .finding-conclusion {{ margin:0 0 10px; font-size:16px; font-weight:800; color:#0f172a; line-height:1.6; }}
    .finding-text {{ margin:0 0 8px; font-size:13px; color:#475569; line-height:1.8; }}
    .chart-card {{ overflow:hidden; }}
    .mini-chip {{ display:inline-flex; align-items:center; border-radius:999px; padding:6px 12px; font-size:12px; font-weight:700; white-space:nowrap; }}
    .mini-chip-green {{ background:#dcfce7; color:#166534; }}
    .mini-chip-yellow {{ background:#fef3c7; color:#92400e; }}
    .mini-chip-red {{ background:#fee2e2; color:#991b1b; }}
    .mini-chip-neutral, .mini-chip-soft {{ background:#f1f5f9; color:#334155; }}
    .empty-card {{ border:1px dashed #cbd5e1; border-radius:16px; padding:20px; color:#64748b; background:#f8fafc; font-size:14px; line-height:1.8; }}
    {floating_tooltip_css()}
    @media (max-width: 960px) {{
      .page-shell {{ grid-template-columns:1fr; }}
      .rail-card {{ position:static; }}
      .rail-links {{ display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); }}
    }}
    @media (max-width: 640px) {{
      .page {{ padding:12px; }}
      .hero {{ padding:18px; border-radius:16px; }}
      .hero h1 {{ font-size:24px; }}
      .hero-status-chip, .top-nav-link {{ width:100%; }}
      .top-nav-links {{ width:100%; }}
      .quick-nav {{ flex-wrap:nowrap; overflow-x:auto; -webkit-overflow-scrolling:touch; padding-bottom:2px; }}
      .module {{ padding:14px; margin-bottom:14px; }}
      .overview-headline {{ font-size:22px; }}
      .metric-value {{ font-size:24px; }}
      .rail-links {{ grid-template-columns:1fr; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <nav class="top-nav">
      <div class="top-nav-links">
        <a class="top-nav-link" href="../index.html">首页</a>
        <a class="top-nav-link" href="./index.html">仪表盘</a>
        <a class="top-nav-link" href="./details.html">详细页</a>
        <a class="top-nav-link is-active" href="./relationship.html">库存销售关系页</a>
        <a class="top-nav-link" href="./monthly.html">月度页</a>
        <a class="top-nav-link" href="./quarterly.html">季度页</a>
        <a class="top-nav-link" href="../manuals/index.html">文档中心</a>
        <a class="top-nav-link" href="../costs/index.html">成本维护台</a>
      </div>
    </nav>
    <section class="hero">
      <h1>{cards['store_name']} 库存和销售关系页</h1>
      <p>这个页面不再把库存和销售分开看，而是直接回答三个问题：库存有没有压过销售、哪些品类该补、哪些品类该先去化。</p>
      <div class="hero-note">当前判断：{relationship['headline']} {relationship['summary']}</div>
      <div class="hero-status">
        <div class="hero-status-chip">关系模式：{relationship['mode']}</div>
        <div class="hero-status-chip">数据时间：{pd.Timestamp(cards['data_capture_at']).strftime('%Y-%m-%d')}（北京时间）</div>
        <div class="hero-status-chip">当前季节：{cards['current_season_name']} / {cards['phase_name']}</div>
      </div>
    </section>
    <div class="page-shell">
      <div class="main-column">
        <nav class="quick-nav">
          <a href="#relationship-overview">关系结论</a>
          <a href="#relationship-metrics">核心指标</a>
          <a href="#relationship-actions">关键建议</a>
          <a href="#relationship-findings">关键发现</a>
          <a href="#relationship-charts">关系图表</a>
          <a href="#relationship-details">详细信息</a>
          <a href="#relationship-basis">数据口径</a>
        </nav>
        <section class="module" id="relationship-overview">
          <div class="module-header">
            <h2 class="module-title">关系结论</h2>
            <p class="module-note">先看一句话结论，再看证据和动作，不需要先钻明细表。</p>
          </div>
          <div class="overview-card">
            <div class="overview-headline">{relationship['headline']}</div>
            <p class="overview-summary">{relationship['summary']}</p>
          </div>
        </section>
        <section class="module" id="relationship-metrics">
          <div class="module-header">
            <h2 class="module-title">核心指标</h2>
            <p class="module-note">把库存、销售、补货、去化和口径风险放在一张屏里看，先判断问题重心在哪。</p>
          </div>
          <div class="metrics-grid">{metric_html}</div>
        </section>
        <section class="module" id="relationship-actions">
          <div class="module-header">
            <h2 class="module-title">关键建议</h2>
            <p class="module-note">今天、未来 7 天、未来 30 天分别做什么，直接从库存和销售的关系倒推动作。</p>
          </div>
          <div class="analysis-grid">{recommendation_html}</div>
        </section>
        <section class="module" id="relationship-findings">
          <div class="module-header">
            <h2 class="module-title">关键发现</h2>
            <p class="module-note">每条都拆成结论、证据和动作，方便老板拍板，也方便店员执行。</p>
          </div>
          <div class="findings-grid">{finding_html}</div>
        </section>
        <section class="module" id="relationship-charts">
          <div class="module-header">
            <h2 class="module-title">关系图表</h2>
            <p class="module-note">先看品类库存额和销售额的关系，再看动作数量分布，就知道预算该往哪边倾斜。</p>
          </div>
          <div class="cards-grid">{chart_html}</div>
        </section>
        <section class="module" id="relationship-details">
          <div class="module-header">
            <h2 class="module-title">详细信息</h2>
            <p class="module-note">先看品类，再下钻到补货款、去化款和负库存款，执行时按这个顺序走更稳。</p>
          </div>
          <div class="tables tables-single">{detail_tables_html}</div>
        </section>
        <section class="module" id="relationship-basis">
          <div class="module-header">
            <h2 class="module-title">数据口径与提醒</h2>
            <p class="module-note">这里明确哪些是直接观察、哪些是估算、哪些带预测性质，避免把页面结论当成绝对真值。</p>
          </div>
          <div class="analysis-grid">{data_basis_html}</div>
        </section>
      </div>
      <aside class="side-rail">
        <section class="rail-card">
          <h3>常用导航</h3>
          <p>老板平时切页主要看这几个入口，关系页适合放在“看完首页之后、下钻详细页之前”。</p>
          <div class="rail-links">
            <a href="../index.html">返回首页</a>
            <a href="./index.html">进入仪表盘</a>
            <a href="./details.html">进入详细页</a>
            <a class="current" href="./relationship.html">当前关系页</a>
            <a href="./monthly.html">进入月度页</a>
            <a href="./quarterly.html">进入季度页</a>
          </div>
        </section>
        <section class="rail-card">
          <h3>本页定位</h3>
          <p>如果只想快速看某一块，点这里直接跳，不用来回滚动。</p>
          <div class="rail-links">
            <a href="#relationship-overview">关系结论</a>
            <a href="#relationship-metrics">核心指标</a>
            <a href="#relationship-actions">关键建议</a>
            <a href="#relationship-findings">关键发现</a>
            <a href="#relationship-charts">关系图表</a>
            <a href="#relationship-details">详细信息</a>
            <a href="#relationship-basis">数据口径</a>
          </div>
        </section>
      </aside>
    </div>
  </div>
  {floating_tooltip_script()}
</body>
</html>
"""


def build_monthly_html(metrics: dict) -> str:
    return build_period_page(metrics, "monthly")


def build_quarterly_html(metrics: dict) -> str:
    return build_period_page(metrics, "quarterly")


def build_markdown_summary(metrics: dict) -> str:
    cards = metrics["summary_cards"]
    actions = metrics["action_summary"]
    profit = cards.get("profit_snapshot")
    pos_highlights = metrics.get("yeusoft_highlights")
    health_lights = build_health_lights(cards, actions)
    dashboard_tips = build_dashboard_tips(cards, actions)[:7]
    time_strategy = build_time_strategy(metrics)
    playbooks = build_operational_playbooks(metrics)
    boss_board = build_boss_action_board(metrics)
    decision = build_decision_engine(metrics)
    replenish = metrics["replenish"].head(5)
    replenish_categories = metrics["replenish_categories"].head(5)
    seasonal_actions = metrics["seasonal_actions"].head(5)
    seasonal_categories = metrics["seasonal_categories"].head(5)
    clearance = metrics["clearance"].head(5)
    clearance_categories = metrics["clearance_categories"].head(5)
    primary_reference = metrics["primary_reference"]
    level_map = {"red": "红灯", "yellow": "黄灯", "green": "绿灯"}
    if profit:
        if profit["projected_month_net_profit"] < 0:
            current_priority = "先稳利润、提连带、控补货。"
        elif not profit["passed_breakeven"]:
            current_priority = "先冲保本线，优先高毛利主销和会员复购。"
        else:
            current_priority = "已过保本线，稳毛利的前提下放大主销营业额。"
    else:
        current_priority = f"先按 {decision['mode']} 推进，再继续补利润口径。"
    lines = [
        f"# {cards['store_name']} 库存销售摘要",
        "",
        "## 老板一分钟结论",
        f"- 结论：{boss_board['headline']}",
        f"- 说明：{boss_board['summary']}",
        f"- 当前经营阶段：{decision['stage']} / {decision['phase']}",
        f"- 日销趋势：{decision['sales_trend']['detail']}",
        f"- 当前经营优先级：{current_priority}",
        "",
        "### 今天先做",
    ]
    lines.extend(f"- {item['title']}：{item['body']}" for item in boss_board["actions_today"])
    lines.extend([
        "",
        "### 今天先别做",
    ])
    lines.extend(f"- {item}" for item in boss_board["dont_do"])
    lines.extend([
        "",
        "### 看板阅读顺序",
    ])
    lines.extend(f"- {item}" for item in boss_board["reading_order"])
    lines.extend([
        "",
        "## 核心指标",
        f"- 经营销售额：{format_num(cards['sales_amount'], 2)} 元",
        f"- 销售明细时间范围：{cards['sales_detail_start'].strftime('%Y-%m-%d')} 到 {cards['sales_detail_end'].strftime('%Y-%m-%d')}",
        f"- 短期销售口径：{cards.get('sales_source_label', '销售清单')}",
        f"- 订单数：{format_num(cards['sales_orders'])}",
        f"- 客单价：{format_num(cards['avg_order_value'], 2)} 元",
        f"- 历史累计销售额：{format_num(cards['cumulative_sales_amount'], 2)} 元",
        f"- 历史累计销量：{format_num(cards['cumulative_sales_qty'])}",
        f"- 历史累计口径：{cards.get('cumulative_sales_source_label', '商品销售情况')}",
        f"- 历史首次销售日期：{cards['history_first_sale'].strftime('%Y-%m-%d')}",
        f"- 经营库存额：{format_num(cards['inventory_amount'], 2)} 元",
        f"- 经营库存件数：{format_num(cards['inventory_qty'])}",
        f"- 负库存 SKU：{format_num(cards['negative_sku_count'])}",
        f"- 会员销售额占比：{format_num(cards['member_sales_ratio'] * 100, 1)}%",
        f"- 建议补货 SKU：{format_num(actions['replenish_count'])}",
        f"- 跨季处理 SKU：{format_num(actions['seasonal_hold_count'])}",
        f"- 建议去化 SKU：{format_num(actions['clearance_count'])}",
        "",
    ])
    if pos_highlights:
        stock_analysis = pos_highlights.get("stock_analysis")
        movement = pos_highlights.get("movement")
        daily_flow = pos_highlights.get("daily_flow")
        category_highlight = pos_highlights.get("category_analysis")
        retail_detail = pos_highlights.get("retail_detail")
        vip_analysis = pos_highlights.get("vip_analysis")
        guide_report = pos_highlights.get("guide_report")
        lines.extend([
            "## POS 高价值数据",
        ])
        if stock_analysis:
            lines.append(
                f"- 库存结构：主要压在 {stock_analysis['top_labels']}，"
                f"当季库存占比 {format_num(stock_analysis['current_season_inventory_share'] * 100, 1)}%，"
                f"跨季库存占比 {format_num(stock_analysis['cross_season_inventory_share'] * 100, 1)}%。"
            )
        if movement:
            lines.append(
                f"- 最近出入库：入库 {format_num(movement['inbound_qty'])} 件 / {format_num(movement['inbound_amount'], 2)} 元，"
                f"出库 {format_num(movement['outbound_qty'])} 件 / {format_num(movement['outbound_amount'], 2)} 元，"
                f"净入库 {format_num(movement['net_qty'])} 件。"
            )
        if daily_flow:
            dominant_payment = daily_flow.get("dominant_payment")
            payment_text = (
                f"{dominant_payment['label']}占比 {format_num(dominant_payment['share'] * 100, 1)}%"
                if dominant_payment
                else "暂无明显主支付方式"
            )
            lines.append(
                f"- 当日流水：{format_num(daily_flow['actual_money'], 2)} 元，"
                f"{format_num(daily_flow['order_count'])} 单 / {format_num(daily_flow['sales_qty'])} 件，{payment_text}。"
            )
        if category_highlight:
            lines.append(
                f"- 品类结构：前两品类贡献约 {format_num(category_highlight['top2_share'] * 100, 1)}%，主要集中在 {category_highlight['top_category_names']}。"
            )
        if retail_detail:
            lines.append(
                f"- 折扣与尺码：当前实销折扣约 {format_num(retail_detail['weighted_discount_rate'] * 10, 1)} 折，"
                f"{retail_detail['discount_category_names']} 折扣依赖偏重，主销尺码集中在 {retail_detail['core_size_names']}。"
            )
        if vip_analysis:
            lines.append(
                f"- 会员基盘：会员 {format_num(vip_analysis['member_count'])} 位，近60天活跃 {format_num(vip_analysis['active_recent_count'])} 位，沉默占比 {format_num(vip_analysis['dormant_ratio'] * 100, 1)}%。"
            )
        if guide_report:
            lines.append(
                f"- 店员执行：主力导购 {guide_report['top_guide_name']}，销售占比 {format_num(guide_report['top_guide_share'] * 100, 1)}%，VIP 销售占比 {format_num(guide_report['vip_sales_share'] * 100, 1)}。"
            )
        lines.append("")

    if profit:
        lines.extend([
            "## 利润与保本",
            f"- 毛利额：{format_num(profit['gross_profit'], 2)} 元，毛利率 {format_num(profit['gross_margin_rate'] * 100, 1)}%，销售口径 {profit.get('sales_source', '未标记')}，毛利率口径 {profit.get('gross_margin_source', '未标记')}",
            f"- 固定费用：{format_num(profit['monthly_operating_expense'], 2)} 元，人工费用：{format_num(profit['salary_total'], 2)} 元",
            f"- 总费用：{format_num(profit['total_expense'], 2)} 元，净利润：{format_num(profit['net_profit'], 2)} 元",
        ])
        if profit.get("breakeven_available"):
            lines.extend([
                f"- 保本销售额：{format_num(profit['breakeven_sales'], 2)} 元，保本进度：{format_num(profit['breakeven_progress_ratio'] * 100, 1)}%",
                f"- 保本日销：{format_num(profit['breakeven_daily_sales'], 2)} 元，当前平均日销：{format_num(profit['average_daily_sales'], 2)} 元",
            ])
        else:
            lines.append("- 当前缺少有效毛利率，保本销售额和保本进度先按保守口径处理。")
        lines.extend([
            f"- 月末净利预测：{format_num(profit['projected_month_net_profit'], 2)} 元，判断：{profit['forecast_headline']}",
            f"- 预测拆解：已实现销售 {format_num(profit['sales_amount'], 2)} 元 + 剩余 {format_num(profit['remaining_days'], 1)} 天预计销售 {format_num(profit['projected_remaining_sales'], 2)} 元",
            "",
        ])

    lines.append("## 输入人 / 店铺逻辑")
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
    ])
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
    lines.extend(f"- {item}" for item in render_insights_markdown(metrics["insights"]))
    lines.append("")
    lines.append("## 最值得先处理的表")
    lines.append("- 补货重点品类：先定补货优先级，再下钻具体款")
    lines.append("- 跨季处理重点品类：先判断哪些品类当前不该补")
    lines.append("- 去化重点品类：先看哪些品类库存深、动销弱")
    lines.append("- 负库存异常清单：优先纠偏")
    if not replenish_categories.empty:
        lines.append("")
        lines.append("## 补货重点品类 Top 5")
        for _, row in replenish_categories.iterrows():
            lines.append(
                f"- {row['中类']} / {row['季节策略']}：SKU数 {format_num(row['SKU数'])}，销售额 {format_num(row['销售额'], 2)}，建议补货量 {format_num(row['建议补货量'])}，补货原则 {row['补货原则']}，主销尺码 {row['主销尺码']}，控折扣原则 {row['控折扣原则']}，预算建议 {row['预算建议']}"
            )
    if not seasonal_categories.empty:
        lines.append("")
        lines.append("## 跨季处理重点品类 Top 5")
        for _, row in seasonal_categories.iterrows():
            lines.append(
                f"- {row['中类']} / {row['季节策略']}：SKU数 {format_num(row['SKU数'])}，库存 {format_num(row['库存'])}，建议 {row['建议动作']}"
            )
    if not clearance_categories.empty:
        lines.append("")
        lines.append("## 去化重点品类 Top 5")
        for _, row in clearance_categories.iterrows():
            lines.append(
                f"- {row['大类']}：SKU数 {format_num(row['SKU数'])}，实际库存 {format_num(row['实际库存'])}，建议 {row['建议动作']}"
            )
    if not replenish.empty:
        lines.append("")
        lines.append("## 补货 SKU 明细 Top 5")
        for _, row in replenish.iterrows():
            lines.append(
                f"- {row['款号']} / {row['颜色']}：库存 {format_num(row['库存'])}，周均销量 {format_num(row['周均销量'], 1)}，建议补货 {format_num(row['建议补货量'])}，补货原则 {row['补货原则']}，主销尺码 {row['主销尺码']}，控折扣原则 {row['控折扣原则']}，预算建议 {row['预算建议']}，顺序 {row['进货顺序']}，提醒 {row['进货提醒']}"
            )
    if not seasonal_actions.empty:
        lines.append("")
        lines.append("## 跨季处理 SKU 明细 Top 5")
        for _, row in seasonal_actions.iterrows():
            lines.append(
                f"- {row['款号']} / {row['颜色']} / {row['季节']}：季节策略 {row['季节策略']}，库存 {format_num(row['库存'])}，建议 {row['建议动作']}"
            )
    if not clearance.empty:
        lines.append("")
        lines.append("## 去化 SKU 明细 Top 5")
        for _, row in clearance.iterrows():
            lines.append(
                f"- {row['商品款号']} / {row['商品名称']}：实际库存 {format_num(row['实际库存'])}，近期零售 {format_num(row['近期零售'])}，建议 {row['建议动作']}"
            )
    return "\n".join(lines)


def build_business_report(metrics: dict) -> str:
    cards = metrics["summary_cards"]
    profit = cards.get("profit_snapshot")
    pos_highlights = metrics.get("yeusoft_highlights")
    sales_top = metrics["sales_by_category_ex_props"].head(4)
    category_risks = metrics["category_risks"].head(4)
    guides = metrics["guide_perf"].head(3)
    seasonal_actions = metrics["seasonal_actions"].head(5)
    replenish_categories = metrics["replenish_categories"].head(5)
    seasonal_categories = metrics["seasonal_categories"].head(5)
    clearance_categories = metrics["clearance_categories"].head(5)
    health_lights = build_health_lights(cards, metrics["action_summary"])
    time_strategy = build_time_strategy(metrics)
    playbooks = build_operational_playbooks(metrics)
    boss_board = build_boss_action_board(metrics)
    decision = build_decision_engine(metrics)
    consulting_analysis = build_retail_consulting_analysis(metrics)
    primary_reference = metrics["primary_reference"]
    level_map = {"red": "红灯", "yellow": "黄灯", "green": "绿灯"}
    if profit:
        if profit["projected_month_net_profit"] < 0:
            current_priority = "先稳利润、提连带、控补货，再谈放大营业额。"
        elif not profit["passed_breakeven"]:
            current_priority = "先冲保本线，优先高毛利主销、会员复购和断码补位。"
        else:
            current_priority = "已过保本线，守住毛利的前提下继续放大主销营业额。"
    else:
        current_priority = f"先按 {decision['mode']} 推进，利润口径补齐后再进一步复盘。"

    lines = [
        f"# {cards['store_name']} 库存销售分析报告",
        "",
        f"日期：{pd.Timestamp.today().strftime('%Y-%m-%d')}",
        "",
        "## 老板一分钟结论",
        "",
        f"- 结论：{boss_board['headline']}",
        f"- 说明：{boss_board['summary']}",
        f"- 当前经营阶段：{decision['stage']} / {decision['phase']}",
        f"- 日销趋势：{decision['sales_trend']['detail']}",
        f"- 当前经营优先级：{current_priority}",
        "",
        "### 今天先做",
    ]

    for item in boss_board["actions_today"]:
        lines.append(f"- {item['title']}：{item['body']}")

    lines.extend([
        "",
        "### 今天先别做",
    ])

    for item in boss_board["dont_do"]:
        lines.append(f"- {item}")

    lines.extend([
        "",
        "### 看板阅读顺序",
    ])

    for item in boss_board["reading_order"]:
        lines.append(f"- {item}")

    lines.extend([
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
    ])
    if pos_highlights:
        stock_analysis = pos_highlights.get("stock_analysis")
        movement = pos_highlights.get("movement")
        daily_flow = pos_highlights.get("daily_flow")
        category_highlight = pos_highlights.get("category_analysis")
        retail_detail = pos_highlights.get("retail_detail")
        vip_analysis = pos_highlights.get("vip_analysis")
        guide_report = pos_highlights.get("guide_report")
        lines.extend([
            "## POS 高价值数据",
            "",
        ])
        if stock_analysis:
            lines.append(
                f"- 库存结构：主要压在 {stock_analysis['top_labels']}，"
                f"当季库存占比 {format_num(stock_analysis['current_season_inventory_share'] * 100, 1)}%，"
                f"跨季库存占比 {format_num(stock_analysis['cross_season_inventory_share'] * 100, 1)}%。"
            )
        if movement:
            lines.append(
                f"- 最近出入库：入库 {format_num(movement['inbound_qty'])} 件 / {format_num(movement['inbound_amount'], 2)} 元，"
                f"出库 {format_num(movement['outbound_qty'])} 件 / {format_num(movement['outbound_amount'], 2)} 元，"
                f"净入库 {format_num(movement['net_qty'])} 件 / {format_num(movement['net_amount'], 2)} 元。"
            )
        if daily_flow:
            dominant_payment = daily_flow.get("dominant_payment")
            payment_text = (
                f"{dominant_payment['label']}占比 {format_num(dominant_payment['share'] * 100, 1)}%"
                if dominant_payment
                else "暂无明显主支付方式"
            )
            lines.append(
                f"- 当日流水：{format_num(daily_flow['actual_money'], 2)} 元，"
                f"{format_num(daily_flow['order_count'])} 单 / {format_num(daily_flow['sales_qty'])} 件，{payment_text}。"
            )
        if category_highlight:
            lines.append(
                f"- 品类结构：前两品类贡献约 {format_num(category_highlight['top2_share'] * 100, 1)}%，主要集中在 {category_highlight['top_category_names']}。"
            )
        if retail_detail:
            lines.append(
                f"- 折扣与尺码：当前实销折扣约 {format_num(retail_detail['weighted_discount_rate'] * 10, 1)} 折，"
                f"{retail_detail['discount_category_names']} 折扣依赖偏重，主销尺码集中在 {retail_detail['core_size_names']}。"
            )
        if vip_analysis:
            lines.append(
                f"- 会员基盘：会员 {format_num(vip_analysis['member_count'])} 位，近60天活跃 {format_num(vip_analysis['active_recent_count'])} 位，沉默占比 {format_num(vip_analysis['dormant_ratio'] * 100, 1)}%。"
            )
        if guide_report:
            lines.append(
                f"- 店员执行：主力导购 {guide_report['top_guide_name']}，销售占比 {format_num(guide_report['top_guide_share'] * 100, 1)}%，VIP 销售占比 {format_num(guide_report['vip_sales_share'] * 100, 1)}。"
            )
        lines.append("")

    if profit:
        lines.extend([
            "## 利润与保本",
            "",
            f"- 毛利额：{format_num(profit['gross_profit'], 2)} 元，毛利率 {format_num(profit['gross_margin_rate'] * 100, 1)}%，销售口径 {profit.get('sales_source', '未标记')}，毛利率口径 {profit.get('gross_margin_source', '未标记')}",
            f"- 固定费用：{format_num(profit['monthly_operating_expense'], 2)} 元，人工费用：{format_num(profit['salary_total'], 2)} 元",
            f"- 总费用：{format_num(profit['total_expense'], 2)} 元，净利润：{format_num(profit['net_profit'], 2)} 元",
        ])
        if profit.get("breakeven_available"):
            lines.extend([
                f"- 保本销售额：{format_num(profit['breakeven_sales'], 2)} 元，保本进度：{format_num(profit['breakeven_progress_ratio'] * 100, 1)}%",
                f"- 保本日销：{format_num(profit['breakeven_daily_sales'], 2)} 元，当前平均日销：{format_num(profit['average_daily_sales'], 2)} 元",
            ])
        else:
            lines.append("- 当前缺少有效毛利率，保本销售额和保本进度先按保守口径处理。")
        lines.extend([
            f"- 月末销售预测：{format_num(profit['projected_month_sales'], 2)} 元，月末净利预测：{format_num(profit['projected_month_net_profit'], 2)} 元",
            f"- 预测拆解：已实现销售 {format_num(profit['sales_amount'], 2)} 元 + 剩余 {format_num(profit['remaining_days'], 1)} 天预计销售 {format_num(profit['projected_remaining_sales'], 2)} 元",
            f"- 最大费用项：{(profit.get('top_expense_item') or {}).get('name', '未记录')} / {format_num(float((profit.get('top_expense_item') or {}).get('amount', 0) or 0), 2)} 元",
            f"- 最高工资项：{(profit.get('top_salary_item') or {}).get('name', '未记录')} / {format_num(float((profit.get('top_salary_item') or {}).get('amount', 0) or 0), 2)} 元",
            "",
        ])
    lines.extend([
        "## 输入人 / 店铺逻辑",
        "",
    ])

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
    ])

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

    append_consulting_analysis_markdown(lines, consulting_analysis)
    lines.append("")

    if not replenish_categories.empty:
        lines.append("## 补货重点品类 Top 5")
        lines.append("")
        for _, row in replenish_categories.iterrows():
            lines.append(
                f"- {row['中类']} / {row['季节策略']}：SKU数 {format_num(row['SKU数'])}，销售额 {format_num(row['销售额'], 2)}，建议补货量 {format_num(row['建议补货量'])}，补货原则 {row['补货原则']}，主销尺码 {row['主销尺码']}"
            )
        lines.append("")

    if not seasonal_categories.empty:
        lines.append("## 跨季处理重点品类 Top 5")
        lines.append("")
        for _, row in seasonal_categories.iterrows():
            lines.append(
                f"- {row['中类']} / {row['季节策略']}：SKU数 {format_num(row['SKU数'])}，库存 {format_num(row['库存'])}，建议 {row['建议动作']}"
            )
        lines.append("")

    if not clearance_categories.empty:
        lines.append("## 去化重点品类 Top 5")
        lines.append("")
        for _, row in clearance_categories.iterrows():
            lines.append(
                f"- {row['大类']}：SKU数 {format_num(row['SKU数'])}，实际库存 {format_num(row['实际库存'])}，建议 {row['建议动作']}"
            )
        lines.append("")

    if not seasonal_actions.empty:
        lines.append("## 跨季处理 SKU 明细 Top 5")
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


def json_ready_value(value: object) -> object:
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): json_ready_value(inner) for key, inner in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready_value(item) for item in value]
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return float(value)
    if pd.isna(value):
        return None
    return value


def frame_to_json_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    if frame.empty:
        return []
    cleaned = frame.copy()
    cleaned = cleaned.where(pd.notna(cleaned), None)
    return [
        {str(column): json_ready_value(value) for column, value in row.items()}
        for row in cleaned.to_dict(orient="records")
    ]


def build_export_payload(
    metrics: dict,
    *,
    page_type: str,
    generated_at: datetime,
) -> dict[str, object]:
    cards = metrics["summary_cards"]
    actions = metrics["action_summary"]
    period_type = None
    if page_type == "monthly":
        period_type = "monthly"
    elif page_type == "quarterly":
        period_type = "quarterly"

    payload = {
        "meta": {
            "page_type": page_type,
            "generated_at": generated_at.isoformat(),
            "store_name": cards.get("store_name"),
            "analysis_batch_id": cards.get("analysis_batch_id"),
            "data_capture_at": json_ready_value(cards.get("data_capture_at")),
            "pipeline": [
                "抓取 JSON",
                "数据同步",
                "SQLite",
                "本地分析",
                "导出 JSON",
                "Pages 展示",
            ],
            "sales_source_label": cards.get("sales_source_label"),
            "cumulative_sales_source_label": cards.get("cumulative_sales_source_label"),
        },
        "summary_cards": json_ready_value(cards),
        "inventory_sales_relationship": json_ready_value(
            build_inventory_sales_relationship(metrics)
        ),
        "today_focus": json_ready_value(build_today_focus(metrics)),
        "health_lights": json_ready_value(build_health_lights(cards, actions)),
        "time_strategy": json_ready_value(build_time_strategy(metrics)),
        "decision": json_ready_value(build_decision_engine(metrics)),
        "consulting_analysis": json_ready_value(
            build_retail_consulting_analysis(metrics, period_type)
        ),
        "dashboard_tips": json_ready_value(build_dashboard_tips(cards, actions)),
        "insights": json_ready_value(metrics.get("insights", [])),
        "tables": {
            "sales_daily": frame_to_json_records(metrics.get("sales_daily", pd.DataFrame())),
            "sales_by_category": frame_to_json_records(metrics.get("sales_by_category", pd.DataFrame())),
            "sales_by_category_ex_props": frame_to_json_records(
                metrics.get("sales_by_category_ex_props", pd.DataFrame())
            ),
            "inventory_by_category": frame_to_json_records(metrics.get("inventory_by_category", pd.DataFrame())),
            "stock_sales_ratio": frame_to_json_records(metrics.get("stock_sales_ratio", pd.DataFrame())),
            "guide_perf": frame_to_json_records(metrics.get("guide_perf", pd.DataFrame())),
            "top_members": frame_to_json_records(metrics.get("top_members", pd.DataFrame())),
            "primary_reference": frame_to_json_records(metrics.get("primary_reference", pd.DataFrame())),
            "other_references": frame_to_json_records(metrics.get("other_references", pd.DataFrame())),
            "negative_inventory": frame_to_json_records(metrics.get("negative_inventory", pd.DataFrame())),
            "low_stock_bestsellers": frame_to_json_records(
                metrics.get("low_stock_bestsellers", pd.DataFrame())
            ),
            "slow_moving": frame_to_json_records(metrics.get("slow_moving", pd.DataFrame())),
            "category_risks": frame_to_json_records(metrics.get("category_risks", pd.DataFrame())),
            "replenish": frame_to_json_records(metrics.get("replenish", pd.DataFrame())),
            "replenish_categories": frame_to_json_records(
                metrics.get("replenish_categories", pd.DataFrame())
            ),
            "seasonal_actions": frame_to_json_records(metrics.get("seasonal_actions", pd.DataFrame())),
            "seasonal_categories": frame_to_json_records(
                metrics.get("seasonal_categories", pd.DataFrame())
            ),
            "clearance": frame_to_json_records(metrics.get("clearance", pd.DataFrame())),
            "clearance_categories": frame_to_json_records(
                metrics.get("clearance_categories", pd.DataFrame())
            ),
        },
    }
    return payload


def write_outputs(metrics: dict, output_dir: Path, pages_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    pages_dir.mkdir(parents=True, exist_ok=True)
    date_tag = pd.Timestamp.today().strftime("%Y-%m-%d")
    generated_at = get_beijing_now()
    output_data_dir = output_dir / "data"
    pages_data_dir = pages_dir / "data"
    output_data_dir.mkdir(parents=True, exist_ok=True)
    pages_data_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / f"库存销售看板_{date_tag}.html"
    detail_html_path = output_dir / f"库存销售详细页_{date_tag}.html"
    monthly_html_path = output_dir / f"库存销售月度页_{date_tag}.html"
    quarterly_html_path = output_dir / f"库存销售季度页_{date_tag}.html"
    relationship_html_path = output_dir / f"库存销售关系页_{date_tag}.html"
    latest_html_path = output_dir / "index.html"
    latest_detail_html_path = output_dir / "details.html"
    latest_monthly_html_path = output_dir / "monthly.html"
    latest_quarterly_html_path = output_dir / "quarterly.html"
    latest_relationship_html_path = output_dir / "relationship.html"
    md_path = output_dir / f"库存销售摘要_{date_tag}.md"
    report_path = output_dir / f"库存销售分析报告_{date_tag}.md"
    replenish_csv = output_dir / f"补货建议清单_{date_tag}.csv"
    clearance_csv = output_dir / f"去化建议清单_{date_tag}.csv"
    category_csv = output_dir / f"品类风险概览_{date_tag}.csv"
    pages_html_path = pages_dir / "index.html"
    pages_detail_html_path = pages_dir / "details.html"
    pages_monthly_html_path = pages_dir / "monthly.html"
    pages_quarterly_html_path = pages_dir / "quarterly.html"
    pages_relationship_html_path = pages_dir / "relationship.html"
    pages_md_path = pages_dir / "summary.md"
    pages_report_path = pages_dir / "report.md"
    pages_replenish_csv = pages_dir / "补货建议清单.csv"
    pages_clearance_csv = pages_dir / "去化建议清单.csv"
    pages_category_csv = pages_dir / "品类风险概览.csv"
    dashboard_json_path = output_data_dir / f"dashboard_{date_tag}.json"
    detail_json_path = output_data_dir / f"details_{date_tag}.json"
    monthly_json_path = output_data_dir / f"monthly_{date_tag}.json"
    quarterly_json_path = output_data_dir / f"quarterly_{date_tag}.json"
    relationship_json_path = output_data_dir / f"relationship_{date_tag}.json"
    manifest_json_path = output_data_dir / f"manifest_{date_tag}.json"
    latest_dashboard_json_path = output_data_dir / "dashboard.json"
    latest_detail_json_path = output_data_dir / "details.json"
    latest_monthly_json_path = output_data_dir / "monthly.json"
    latest_quarterly_json_path = output_data_dir / "quarterly.json"
    latest_relationship_json_path = output_data_dir / "relationship.json"
    latest_manifest_json_path = output_data_dir / "manifest.json"
    pages_dashboard_json_path = pages_data_dir / "dashboard.json"
    pages_detail_json_path = pages_data_dir / "details.json"
    pages_monthly_json_path = pages_data_dir / "monthly.json"
    pages_quarterly_json_path = pages_data_dir / "quarterly.json"
    pages_relationship_json_path = pages_data_dir / "relationship.json"
    pages_manifest_json_path = pages_data_dir / "manifest.json"
    html_output = build_html(metrics)
    detail_html_output = build_detail_html(metrics)
    monthly_html_output = build_monthly_html(metrics)
    quarterly_html_output = build_quarterly_html(metrics)
    relationship_html_output = build_relationship_html(metrics)
    markdown_output = build_markdown_summary(metrics)
    report_output = build_business_report(metrics)
    dashboard_payload = build_export_payload(metrics, page_type="dashboard", generated_at=generated_at)
    detail_payload = build_export_payload(metrics, page_type="details", generated_at=generated_at)
    monthly_payload = build_export_payload(metrics, page_type="monthly", generated_at=generated_at)
    quarterly_payload = build_export_payload(metrics, page_type="quarterly", generated_at=generated_at)
    relationship_payload = build_export_payload(metrics, page_type="relationship", generated_at=generated_at)
    manifest_payload = {
        "generated_at": generated_at.isoformat(),
        "date_tag": date_tag,
        "store_name": metrics["summary_cards"].get("store_name"),
        "analysis_batch_id": metrics["summary_cards"].get("analysis_batch_id"),
        "available_pages": {
            "dashboard": "data/dashboard.json",
            "details": "data/details.json",
            "monthly": "data/monthly.json",
            "quarterly": "data/quarterly.json",
            "relationship": "data/relationship.json",
        },
        "available_exports": {
            "summary_markdown": "summary.md",
            "report_markdown": "report.md",
            "replenish_csv": "补货建议清单.csv",
            "clearance_csv": "去化建议清单.csv",
            "category_risk_csv": "品类风险概览.csv",
        },
        "pipeline": [
            "抓取 JSON",
            "数据同步",
            "SQLite",
            "本地分析",
            "导出 JSON",
            "Pages 展示",
        ],
    }
    html_path.write_text(html_output, encoding="utf-8")
    detail_html_path.write_text(detail_html_output, encoding="utf-8")
    monthly_html_path.write_text(monthly_html_output, encoding="utf-8")
    quarterly_html_path.write_text(quarterly_html_output, encoding="utf-8")
    relationship_html_path.write_text(relationship_html_output, encoding="utf-8")
    latest_html_path.write_text(html_output, encoding="utf-8")
    latest_detail_html_path.write_text(detail_html_output, encoding="utf-8")
    latest_monthly_html_path.write_text(monthly_html_output, encoding="utf-8")
    latest_quarterly_html_path.write_text(quarterly_html_output, encoding="utf-8")
    latest_relationship_html_path.write_text(relationship_html_output, encoding="utf-8")
    md_path.write_text(markdown_output, encoding="utf-8")
    report_path.write_text(report_output, encoding="utf-8")
    dashboard_json_path.write_text(json.dumps(dashboard_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    detail_json_path.write_text(json.dumps(detail_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    monthly_json_path.write_text(json.dumps(monthly_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    quarterly_json_path.write_text(json.dumps(quarterly_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    relationship_json_path.write_text(
        json.dumps(relationship_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    manifest_json_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_dashboard_json_path.write_text(
        json.dumps(dashboard_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    latest_detail_json_path.write_text(
        json.dumps(detail_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    latest_monthly_json_path.write_text(
        json.dumps(monthly_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    latest_quarterly_json_path.write_text(
        json.dumps(quarterly_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    latest_relationship_json_path.write_text(
        json.dumps(relationship_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    latest_manifest_json_path.write_text(
        json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    metrics["replenish"].to_csv(replenish_csv, index=False, encoding="utf-8-sig")
    metrics["clearance"].to_csv(clearance_csv, index=False, encoding="utf-8-sig")
    metrics["category_risks"].to_csv(category_csv, index=False, encoding="utf-8-sig")
    pages_html_path.write_text(html_output, encoding="utf-8")
    pages_detail_html_path.write_text(detail_html_output, encoding="utf-8")
    pages_monthly_html_path.write_text(monthly_html_output, encoding="utf-8")
    pages_quarterly_html_path.write_text(quarterly_html_output, encoding="utf-8")
    pages_relationship_html_path.write_text(relationship_html_output, encoding="utf-8")
    pages_md_path.write_text(markdown_output, encoding="utf-8")
    pages_report_path.write_text(report_output, encoding="utf-8")
    pages_dashboard_json_path.write_text(
        json.dumps(dashboard_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    pages_detail_json_path.write_text(
        json.dumps(detail_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    pages_monthly_json_path.write_text(
        json.dumps(monthly_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    pages_quarterly_json_path.write_text(
        json.dumps(quarterly_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    pages_relationship_json_path.write_text(
        json.dumps(relationship_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    pages_manifest_json_path.write_text(
        json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    metrics["replenish"].to_csv(pages_replenish_csv, index=False, encoding="utf-8-sig")
    metrics["clearance"].to_csv(pages_clearance_csv, index=False, encoding="utf-8-sig")
    metrics["category_risks"].to_csv(pages_category_csv, index=False, encoding="utf-8-sig")
    return {
        "html": html_path,
        "detail_html": detail_html_path,
        "latest_html": latest_html_path,
        "latest_detail_html": latest_detail_html_path,
        "monthly_html": monthly_html_path,
        "quarterly_html": quarterly_html_path,
        "latest_monthly_html": latest_monthly_html_path,
        "latest_quarterly_html": latest_quarterly_html_path,
        "relationship_html": relationship_html_path,
        "latest_relationship_html": latest_relationship_html_path,
        "pages_html": pages_html_path,
        "pages_detail_html": pages_detail_html_path,
        "pages_monthly_html": pages_monthly_html_path,
        "pages_quarterly_html": pages_quarterly_html_path,
        "pages_relationship_html": pages_relationship_html_path,
        "markdown": md_path,
        "pages_markdown": pages_md_path,
        "report": report_path,
        "pages_report": pages_report_path,
        "replenish_csv": replenish_csv,
        "pages_replenish_csv": pages_replenish_csv,
        "clearance_csv": clearance_csv,
        "pages_clearance_csv": pages_clearance_csv,
        "category_csv": category_csv,
        "pages_category_csv": pages_category_csv,
        "dashboard_json": latest_dashboard_json_path,
        "detail_json": latest_detail_json_path,
        "monthly_json": latest_monthly_json_path,
        "quarterly_json": latest_quarterly_json_path,
        "relationship_json": latest_relationship_json_path,
        "manifest_json": latest_manifest_json_path,
        "pages_dashboard_json": pages_dashboard_json_path,
        "pages_detail_json": pages_detail_json_path,
        "pages_monthly_json": pages_monthly_json_path,
        "pages_quarterly_json": pages_quarterly_json_path,
        "pages_relationship_json": pages_relationship_json_path,
        "pages_manifest_json": pages_manifest_json_path,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--pages-dir", type=Path, default=DEFAULT_PAGES_DIR)
    parser.add_argument("--cost-file", type=Path, default=DEFAULT_COST_FILE)
    parser.add_argument("--cost-history-file", type=Path, default=DEFAULT_COST_HISTORY_FILE)
    parser.add_argument("--yeusoft-capture-dir", type=Path, default=DEFAULT_YEU_CAPTURE_DIR)
    parser.add_argument("--analysis-db-file", type=Path, default=DEFAULT_ANALYSIS_DB_FILE)
    parser.add_argument("--store", default=None, help="Optional store name override")
    args = parser.parse_args()
    cost_snapshot = load_cost_snapshot(args.cost_file)
    cost_history_raw = load_cost_history(args.cost_history_file)
    yeusoft_capture_bundle = load_yeusoft_capture_bundle(args.yeusoft_capture_dir)
    cleaned, store_name, analysis_snapshot = load_dashboard_data_from_analysis(
        args.analysis_db_file,
        args.store,
    )
    metrics = build_metrics(
        cleaned,
        store_name,
        cost_snapshot=cost_snapshot,
        cost_history_raw=cost_history_raw,
        yeusoft_capture_bundle=yeusoft_capture_bundle,
        analysis_db_file=args.analysis_db_file,
        analysis_snapshot=analysis_snapshot,
    )
    outputs = write_outputs(metrics, args.output_dir, args.pages_dir)

    print(f"Store: {store_name}")
    print(f"HTML dashboard: {outputs['html']}")
    print(f"Latest HTML dashboard: {outputs['latest_html']}")
    print(f"Pages HTML dashboard: {outputs['pages_html']}")
    print(f"Monthly HTML dashboard: {outputs['monthly_html']}")
    print(f"Quarterly HTML dashboard: {outputs['quarterly_html']}")
    print(f"Relationship HTML dashboard: {outputs['relationship_html']}")
    print(f"Pages monthly dashboard: {outputs['pages_monthly_html']}")
    print(f"Pages quarterly dashboard: {outputs['pages_quarterly_html']}")
    print(f"Pages relationship dashboard: {outputs['pages_relationship_html']}")
    print(f"Markdown summary: {outputs['markdown']}")
    print(f"Pages Markdown summary: {outputs['pages_markdown']}")
    print(f"Business report: {outputs['report']}")
    print(f"Pages business report: {outputs['pages_report']}")
    print(f"Replenish CSV: {outputs['replenish_csv']}")
    print(f"Pages replenish CSV: {outputs['pages_replenish_csv']}")
    print(f"Clearance CSV: {outputs['clearance_csv']}")
    print(f"Pages clearance CSV: {outputs['pages_clearance_csv']}")
    print(f"Category risk CSV: {outputs['category_csv']}")
    print(f"Pages category risk CSV: {outputs['pages_category_csv']}")
    print(f"Relationship JSON: {outputs['relationship_json']}")
    print(f"Pages relationship JSON: {outputs['pages_relationship_json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
