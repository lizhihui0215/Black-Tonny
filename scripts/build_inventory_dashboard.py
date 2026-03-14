#!/usr/bin/env python3
"""Build a non-technical inventory and sales dashboard from exported reports."""

from __future__ import annotations

import argparse
import calendar
import html
import json
import math
import re
import tempfile
import zipfile
import urllib.parse
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
DEFAULT_PAGES_DIR = ROOT / "docs" / "dashboard"
DEFAULT_COST_FILE = ROOT / "data" / "store_cost_snapshot.json"
DEFAULT_YEU_CAPTURE_DIR = ROOT / "reports" / "yeusoft_report_capture"
BEIJING_TZ = ZoneInfo("Asia/Shanghai")
PRIMARY_INPUT = "郭文攀"
SEASON_STRATEGY_TOOLTIPS = {
    "当季主推": "这类商品现在正处于主销季，可以作为主补货方向。先看品类，再补销售高、库存低的具体款。",
    "下一季试补": "这类商品接近主销季，可以小量试补。先补 1-2 个颜色或核心尺码，不要一次压深。",
    "跨季去化": "这类商品已经偏离当前主销季。手里有库存就优先做去化，没有库存就先别追补。",
    "暂缓补货": "这类商品当前不是重点，不建议马上追加。等季节、销售和陈列位置更合适时再看。",
}
STATUS_TOOLTIPS = {
    "高压货": "这个品类库存金额明显高于销售金额。先停补，再安排组合促销或清货位去化。",
    "需关注": "这个品类已经有库存压力，但还没到最严重。建议连续观察 1-2 周，必要时先收紧补货。",
    "相对健康": "这个品类的库存和销售关系还算正常，当前维持节奏即可。",
}
ACTION_TOOLTIPS = {
    "立即补货": "这是当前主销且库存非常低的款。今天就补，优先补核心尺码和卖得快的颜色。",
    "优先补货": "这类商品需要尽快补，但不一定要今天全部补完。先保最能带营业额的款。",
    "先校库存再补货": "系统库存不准。先查盘点、调拨和销售回写，确认真实库存后再决定是否补货。",
    "小量试补": "可以少量补货试销。先小批量补，不要一次压很多库存。",
    "先停补再去化": "先暂停这个品类的新补货，把现有库存先卖掉。适合做组合价、第二件优惠或门口清货位。",
    "观察并做组合去化": "先不要深补。可以用搭配销售、组合价和会员提醒慢慢去化。",
    "优先去化": "这类库存当前更适合先卖掉，不适合继续补。先做陈列前移、组合促销、会员触达。",
    "跨季不补货": "当前不是这个品类的主销季。即使历史卖过，现在也先别补，等回到主销季再判断。",
    "暂缓补货": "先不要急着补，把预算和货位留给当前主销品类。",
}
HIGH_FREQUENCY_ACTION_TOOLTIPS = {
    "先处理负库存": "今天先查库存为负的款。先核对盘点、调拨和销售回写，别直接按系统数去补货。",
    "先去库存": "先暂停深补，把高库存慢销货先卖掉。优先做清货位、组合价和会员定向去化。",
    "控制库存量": "先收紧进货和补货节奏，把预算留给主销品类，避免继续压货。",
    "处理跨季品类": "把已经跨季的品类单独拎出来。有库存先去化，没库存先别追补。",
    "联系高价值会员": "优先联系购买金额高、消费次数多的会员，用换季提醒和到店试穿带动复购。",
    "安排去库存动作": "今天要明确哪些品类先停补、哪些品类上清货位、哪些品类做组合促销。",
    "确认跨季处理": "由老板拍板跨季品类是去化、暂缓还是等下季，不要混进当季补货里。",
    "停止补货": "这个动作表示先别继续进货，把现有库存先卖掉，再决定要不要恢复补货。",
    "组合促销": "把高库存品类和低决策商品搭在一起卖，比如第二件折扣、两件组合价、满额换购。",
    "清货陈列": "把需要优先卖掉的货放到门口或主通道陈列位，让顾客先看到。",
    "控制补货": "补货可以做，但要收紧节奏。先补销量高、库存低的主销款，别平均补。",
    "组合去化": "不要单独硬推慢销货，和基础款、袜品、家居服做搭配更容易成交。",
    "调整陈列": "通过前移、压缩、分区等方式，让主销品类更显眼，慢销品类不占主位置。",
    "稳住会员复购": "用换季提醒、到店试穿和组合推荐，先把老客的复购频率稳住。",
}


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


def infer_primary_store_from_retail(data: dict[str, pd.DataFrame], primary_input: str = PRIMARY_INPUT) -> str | None:
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
    for report_name in ("库存综合分析", "出入库单据", "每日流水单"):
        capture_path = capture_dir / f"{report_name}.json"
        if capture_path.exists():
            try:
                bundle[report_name] = json.loads(capture_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
    return bundle


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
        "window_start": pd.to_datetime(request_payload.get("BeginDate"), errors="coerce"),
        "window_end": pd.to_datetime(request_payload.get("EndDate"), errors="coerce"),
        "order_count": len(normalized_rows),
        "sales_qty": total_sales_qty,
        "tag_money": total_tag_money,
        "actual_money": total_actual_money,
        "average_discount": safe_ratio(total_discount, len(normalized_rows)),
        "payment_breakdown": payment_breakdown,
        "dominant_payment": dominant_payment,
        "latest_make_date": latest_make_date,
    }


def build_yeusoft_report_highlights(
    capture_bundle: dict[str, dict], current_season: str, next_season: str
) -> dict | None:
    if not capture_bundle:
        return None

    stock_analysis = parse_yeusoft_stock_analysis(
        capture_bundle.get("库存综合分析"), current_season, next_season
    )
    movement = parse_yeusoft_movement_report(capture_bundle.get("出入库单据"))
    daily_flow = parse_yeusoft_daily_flow(capture_bundle.get("每日流水单"))

    capture_dates = [
        value.get("capture_at")
        for value in (stock_analysis, movement, daily_flow)
        if value and pd.notna(value.get("capture_at"))
    ]

    return {
        "stock_analysis": stock_analysis,
        "movement": movement,
        "daily_flow": daily_flow,
        "capture_at": max(capture_dates) if capture_dates else pd.NaT,
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
    total_expense = float(expense_snapshot.get("total_expense", monthly_operating_expense + salary_total) or 0)
    net_profit = float(raw_snapshot.get("net_profit", gross_profit - total_expense) or 0)

    month_days = calendar.monthrange(snapshot_dt.year, snapshot_dt.month)[1]
    elapsed_days = snapshot_dt.day + safe_ratio(snapshot_dt.hour * 60 + snapshot_dt.minute, 1440)
    remaining_days = max(month_days - elapsed_days, 0)

    breakeven_sales = safe_ratio(total_expense, gross_margin_rate)
    breakeven_daily_sales = safe_ratio(breakeven_sales, month_days)
    average_daily_sales = safe_ratio(sales_amount, elapsed_days)
    average_daily_gross_profit = safe_ratio(gross_profit, elapsed_days)
    remaining_sales_to_breakeven = max(0.0, breakeven_sales - sales_amount)
    remaining_daily_sales_needed = safe_ratio(remaining_sales_to_breakeven, remaining_days)
    passed_breakeven = sales_amount >= breakeven_sales if breakeven_sales else False
    net_margin_rate = safe_ratio(net_profit, sales_amount)
    expense_ratio = safe_ratio(total_expense, sales_amount)
    salary_ratio = safe_ratio(salary_total, sales_amount)
    operating_expense_ratio = safe_ratio(monthly_operating_expense, sales_amount)
    expense_coverage_ratio = safe_ratio(gross_profit, total_expense)
    breakeven_progress_ratio = safe_ratio(sales_amount, breakeven_sales) if breakeven_sales else 0.0
    projected_month_sales = average_daily_sales * month_days
    projected_month_gross_profit = projected_month_sales * gross_margin_rate
    projected_month_net_profit = projected_month_gross_profit - total_expense
    projected_monthly_status = (
        "green" if projected_month_net_profit > 0 else "yellow" if projected_month_gross_profit >= total_expense * 0.9 else "red"
    )
    fixed_cost_daily_burden = safe_ratio(monthly_operating_expense, month_days)
    salary_daily_burden = safe_ratio(salary_total, month_days)
    top_expense_item = max(expense_items, key=lambda item: float(item.get("amount", 0) or 0), default=None)
    top_salary_item = max(salary_items, key=lambda item: float(item.get("amount", 0) or 0), default=None)

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
        "average_daily_sales": average_daily_sales,
        "remaining_days": remaining_days,
        "remaining_sales_to_breakeven": remaining_sales_to_breakeven,
        "remaining_daily_sales_needed": remaining_daily_sales_needed,
        "projected_month_sales": projected_month_sales,
        "projected_month_gross_profit": projected_month_gross_profit,
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


def build_metrics(
    data: dict[str, pd.DataFrame],
    store_name: str,
    cost_snapshot: dict | None = None,
    yeusoft_capture_bundle: dict[str, dict] | None = None,
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
    profit_snapshot = build_profit_snapshot(cost_snapshot)
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
    }

    capture_candidates = [
        summary_cards["sales_detail_end"],
        movement["发货时间"].max() if not movement.empty else pd.NaT,
        store_retail["销售日期"].max() if not store_retail.empty and "销售日期" in store_retail.columns else pd.NaT,
    ]
    if yeusoft_highlights and pd.notna(yeusoft_highlights.get("capture_at")):
        capture_candidates.append(yeusoft_highlights["capture_at"])
    valid_capture_dates = [normalize_compare_timestamp(item) for item in capture_candidates if pd.notna(item)]
    summary_cards["data_capture_at"] = max(valid_capture_dates) if valid_capture_dates else pd.Timestamp(now.date())
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
    replenish_categories = (
        replenish.groupby(["中类", "季节策略"])
        .agg(
            SKU数=("款号", "count"),
            销售额=("销售金额", "sum"),
            库存=("库存", "sum"),
            建议补货量=("建议补货量", "sum"),
        )
        .reset_index()
        .sort_values(["销售额", "建议补货量", "SKU数"], ascending=[False, False, False])
        if not replenish.empty
        else pd.DataFrame(columns=["中类", "季节策略", "SKU数", "销售额", "库存", "建议补货量"])
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
    if yeusoft_highlights:
        stock_analysis = yeusoft_highlights.get("stock_analysis")
        movement_highlight = yeusoft_highlights.get("movement")
        daily_flow = yeusoft_highlights.get("daily_flow")
        if stock_analysis:
            top_labels = stock_analysis["top_labels"]
            cross_share = stock_analysis["cross_season_inventory_share"] * 100
            current_share = stock_analysis["current_season_inventory_share"] * 100
            insights.append(
                f"POS 库存综合分析显示，当前库存金额主要压在 {top_labels}；"
                f"其中当季库存约占 {format_num(current_share, 1)}%，跨季库存约占 {format_num(cross_share, 1)}%。"
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
                f"POS 出入库单据显示 {window_label} 内入库 {format_num(movement_highlight['inbound_qty'])} 件 / "
                f"{format_num(movement_highlight['inbound_amount'], 2)} 元，出库 {format_num(movement_highlight['outbound_qty'])} 件 / "
                f"{format_num(movement_highlight['outbound_amount'], 2)} 元，净入库 {format_num(movement_highlight['net_qty'])} 件。"
            )
        if daily_flow:
            dominant_payment = daily_flow.get("dominant_payment")
            payment_text = (
                f"{dominant_payment['label']}占比 {format_num(dominant_payment['share'] * 100, 1)}%"
                if dominant_payment
                else "暂无明显支付方式集中"
            )
            insights.append(
                f"POS 每日流水单显示，当日流水 {format_num(daily_flow['actual_money'], 2)} 元，"
                f"{format_num(daily_flow['order_count'])} 单 / {format_num(daily_flow['sales_qty'])} 件，{payment_text}。"
            )
    if profit_snapshot:
        insights.append(
            f"按最近一版成本快照，毛利约 {format_num(profit_snapshot['gross_profit'], 2)} 元，"
            f"总费用约 {format_num(profit_snapshot['total_expense'], 2)} 元，"
            f"净利润约 {format_num(profit_snapshot['net_profit'], 2)} 元。"
        )
        insights.append(
            f"当前保本销售额约 {format_num(profit_snapshot['breakeven_sales'], 2)} 元，"
            f"平均每天至少要卖 {format_num(profit_snapshot['breakeven_daily_sales'], 2)} 元。"
        )
        insights.append(
            f"固定费用约 {format_num(profit_snapshot['monthly_operating_expense'], 2)} 元，"
            f"人工费用约 {format_num(profit_snapshot['salary_total'], 2)} 元；"
            f"目前保本进度约 {format_num(profit_snapshot['breakeven_progress_ratio'] * 100, 1)}%。"
        )
        insights.append(
            f"按当前平均日销推算，月末销售约 {format_num(profit_snapshot['projected_month_sales'], 2)} 元，"
            f"月末净利润约 {format_num(profit_snapshot['projected_month_net_profit'], 2)} 元。"
        )
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
        "replenish_categories": replenish_categories,
        "seasonal_actions": seasonal_actions,
        "seasonal_categories": seasonal_categories,
        "clearance": clearance,
        "clearance_categories": clearance_categories,
        "action_summary": action_summary,
        "insights": insights,
        "yeusoft_highlights": yeusoft_highlights,
    }


def fig_to_html(fig: go.Figure, include_js: bool = False) -> str:
    return fig.to_html(
        full_html=False,
        include_plotlyjs="cdn" if include_js else False,
        config={
            "responsive": True,
            "displaylogo": False,
            "scrollZoom": False,
            "modeBarButtonsToRemove": [
                "lasso2d",
                "select2d",
                "autoScale2d",
                "toggleSpikelines",
                "hoverClosestCartesian",
                "hoverCompareCartesian",
            ],
        },
    )


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


def format_badge(value: str, level: str, tip: str | None = None) -> str:
    safe_value = html.escape(value)
    classes = f"badge badge-{level}"
    attrs = ""
    if tip:
        safe_tip = html.escape(tip, quote=True)
        classes += " tooltip-badge"
        attrs = f' title="{safe_tip}" data-tip="{safe_tip}" tabindex="0" role="note"'
    return f"<span class='{classes}'{attrs}>{safe_value}</span>"


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

    top_replenish = top_labels_from_series(metrics["replenish_categories"]["中类"], time_strategy["top_replenish_category"], 2)
    top_clearance = top_labels_from_series(metrics["clearance_categories"]["大类"], time_strategy["top_clearance_category"], 2)
    top_seasonal = top_labels_from_series(metrics["seasonal_categories"]["中类"], "跨季品类", 2)

    if cards["negative_sku_count"] >= 50:
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


def build_boss_action_board(metrics: dict) -> dict[str, object]:
    cards = metrics["summary_cards"]
    profit = cards.get("profit_snapshot")
    pos_highlights = metrics.get("yeusoft_highlights")
    decision = build_decision_engine(metrics)
    time_strategy = build_time_strategy(metrics)
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

    actions_today = [
        {
            "title": "先看哪张表",
            "body": (
                "先打开“去化重点品类”和“负库存异常清单”。"
                if cards["negative_sku_count"] >= 30
                else "先打开“去化重点品类”，确认今天最该先处理的品类。"
            ),
        },
        {
            "title": "今天怎么做",
            "body": (
                f"先处理 {top_clearance_categories} 的库存压力；"
                f"补货只看 {top_replenish_categories} 这些当季主销品类。"
            ),
        },
        {
            "title": "老板今天拍板什么",
            "body": (
                f"单独看 {top_seasonal_categories} 这些跨季品类，决定是去化、暂缓，还是等回到主销季再补。"
            ),
        },
    ]

    dont_do = [
        "不要先看单款，先看品类，再下钻到 SKU。",
        "不要把道具金额和库存算进正常经营判断。",
        "不要把其他输入人的店铺数据当成本店结论。",
    ]
    if not seasonal_categories.empty:
        dont_do.append("不要因为某个冬款历史卖过，就在春夏阶段继续追补。")

    reading_order = [
        "先看“老板一分钟结论”，确认今天的主任务。",
        "再看“经营健康灯”，判断先救火还是先放大机会。",
        "再看“补货重点品类 / 去化重点品类 / 跨季处理重点品类”。",
        "最后再下钻到具体 SKU 明细表执行。",
    ]

    meeting_script = [
        f"今天主任务：{headline}",
        f"今天主盯品类：去化看 {top_clearance_categories}，补货看 {top_replenish_categories}。",
        "今天执行顺序：先纠偏，再去化，再补货。",
    ]

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
    if actions["clearance_count"] > 50 or actions["high_risk_category_count"] > 0:
        conclusions.append(trim_text(f"先停补{top_clearance}", 12))
    if actions["replenish_count"] > 100:
        conclusions.append(trim_text(f"优先补{top_replenish}", 12))
    if seasonal_categories.shape[0] > 0:
        conclusions.append("处理跨季品类")
    if cards["member_sales_ratio"] >= 0.6:
        conclusions.append("联系高价值会员")
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


def safe_cell_html(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value)
    if "<" in text and ">" in text:
        return text
    return html.escape(text)


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


def render_empty(message: str) -> str:
    return f"<div class='empty-card'>{html.escape(message)}</div>"


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


def compact_list_html(
    df: pd.DataFrame,
    title: str,
    rows: int,
    tip: str,
    title_fn,
    subtitle_fn,
    stats_fn,
    detail_fn=None,
) -> str:
    preview = df.head(rows).copy()
    if preview.empty:
        return render_empty(f"{title} 当前没有可展示数据。")

    items_html: list[str] = []
    for _, row in preview.iterrows():
        stats = "".join(stats_fn(row))
        detail_html = ""
        if detail_fn is not None:
            details = [item for item in detail_fn(row) if item]
            if details:
                detail_html = (
                    "<details class='compact-more'>"
                    "<summary>查看补充信息</summary>"
                    f"<ul class='compact-detail-list'>{''.join(f'<li>{html.escape(str(item))}</li>' for item in details)}</ul>"
                    "</details>"
                )
        items_html.append(
            f"""
            <article class="compact-item">
              <div class="compact-item-head">
                <div class="compact-item-title">{html.escape(str(title_fn(row)))}</div>
                <div class="compact-item-subtitle">{html.escape(str(subtitle_fn(row)))}</div>
              </div>
              <div class="compact-stats">{stats}</div>
              {detail_html}
            </article>
            """
        )

    return f"""
    <section class="table-card compact-card">
      <div class="table-header">
        <h3>{title}</h3>
      </div>
      <p class="table-tip">{tip}</p>
      <div class="compact-list">
        {''.join(items_html)}
      </div>
    </section>
    """


def build_yeusoft_highlight_cards(pos_highlights: dict | None) -> list[dict[str, str]]:
    if not pos_highlights:
        return []

    cards: list[dict[str, str]] = []
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

    return cards


def build_profit_card_defs(profit: dict | None) -> list[tuple[str, str, str, str]]:
    if not profit:
        return []

    progress_text = (
        "已过保本线"
        if profit["passed_breakeven"]
        else f"还差 {format_num(profit['remaining_sales_to_breakeven'], 2)} 元"
    )
    progress_tone = "green" if profit["passed_breakeven"] else "yellow"
    projection_tone = profit.get("projected_monthly_status", "neutral")
    top_expense = profit.get("top_expense_item") or {}
    top_salary = profit.get("top_salary_item") or {}

    return [
        ("净利润", f"{format_num(profit['net_profit'], 2)} 元", profit["headline"], profit["status"]),
        (
            "毛利额",
            f"{format_num(profit['gross_profit'], 2)} 元",
            f"毛利率 {format_num(profit['gross_margin_rate'] * 100, 1)}%",
            "neutral",
        ),
        (
            "固定费用",
            f"{format_num(profit['monthly_operating_expense'], 2)} 元",
            (
                f"每天固定支出约 {format_num(profit['fixed_cost_daily_burden'], 2)} 元"
                if profit["monthly_operating_expense"]
                else "当前没有固定费用数据"
            ),
            "neutral",
        ),
        (
            "人工费用",
            f"{format_num(profit['salary_total'], 2)} 元",
            (
                f"每天人工成本约 {format_num(profit['salary_daily_burden'], 2)} 元"
                if profit["salary_total"]
                else "当前没有人工成本数据"
            ),
            "neutral",
        ),
        (
            "保本销售额",
            f"{format_num(profit['breakeven_sales'], 2)} 元",
            f"保本日销约 {format_num(profit['breakeven_daily_sales'], 2)} 元",
            "neutral",
        ),
        (
            "保本进度",
            f"{format_num(min(profit['breakeven_progress_ratio'], 9.99) * 100, 1)}%",
            progress_text,
            progress_tone,
        ),
        (
            "月末净利预测",
            f"{format_num(profit['projected_month_net_profit'], 2)} 元",
            profit["forecast_headline"],
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
    insights_html = "".join(f"<li>{item}</li>" for item in metrics["insights"])
    chart_html = "".join(f"<section class='chart-card'>{chart}</section>" for chart in charts)
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
          <ul class="insight-list">
            <li>北京时间：{time_strategy['beijing_time']}</li>
            <li>当前判断：{time_strategy['headline']}</li>
            {"".join(f"<li>{item}</li>" for item in time_strategy['daily_actions'])}
            {"".join(f"<li>{item}</li>" for item in time_strategy['weekly_actions'])}
            {"".join(f"<li>{item}</li>" for item in time_strategy['monthly_actions'])}
          </ul>
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

    inventory_tables_html = "".join(
        [
            compact_list_html(
                metrics["replenish_categories"],
                "补货重点品类",
                8,
                "先按品类定补货优先级，再下钻到单款。",
                lambda row: row["中类"],
                lambda row: f"{row['季节策略']} / 建议补货 SKU {format_num(row['SKU数'])}",
                lambda row: [
                    compact_stat_row("销售额", f"{format_num(row['销售额'], 2)} 元"),
                    compact_stat_row("当前库存", format_num(row["库存"])),
                    compact_stat_row("建议补货量", format_num(row["建议补货量"])),
                ],
                lambda row: [
                    f"季节策略：{row['季节策略']}",
                    f"建议补货 SKU：{format_num(row['SKU数'])}",
                ],
            ),
            compact_list_html(
                metrics["seasonal_categories"],
                "跨季处理重点品类",
                8,
                "先看哪些品类已经跨季，再决定暂缓还是去化。",
                lambda row: row["中类"],
                lambda row: f"{row['季节策略']} / {row['建议动作']}",
                lambda row: [
                    compact_stat_row("库存", format_num(row["库存"])),
                    compact_stat_row("SKU数", format_num(row["SKU数"])),
                    compact_stat_row("建议动作", row["建议动作"], is_badge=True, tone="warn"),
                ],
                lambda row: [
                    f"季节策略：{row['季节策略']}",
                    f"建议动作：{row['建议动作']}",
                ],
            ),
            compact_list_html(
                metrics["clearance_categories"],
                "去化重点品类",
                8,
                "先按品类看库存压力，再安排陈列和促销动作。",
                lambda row: row["大类"],
                lambda row: f"{row['建议动作']} / 高库存低动销",
                lambda row: [
                    compact_stat_row("实际库存", format_num(row["实际库存"])),
                    compact_stat_row("近期零售", format_num(row["近期零售"])),
                    compact_stat_row("建议动作", row["建议动作"], is_badge=True, tone="danger"),
                ],
                lambda row: [
                    f"SKU数：{format_num(row['SKU数'])}",
                ],
            ),
            compact_list_html(
                metrics["replenish"],
                "补货 SKU 明细",
                10,
                "确定品类要补后，再来这里挑具体款。",
                lambda row: row["款号"],
                lambda row: f"{row['中类']} / {row['颜色']}",
                lambda row: [
                    compact_stat_row("库存", format_num(row["库存"])),
                    compact_stat_row("周均销量", format_num(row["周均销量"], 1)),
                    compact_stat_row("建议补货", format_num(row["建议补货量"])),
                ],
                lambda row: [
                    f"销售金额：{format_num(row['销售金额'], 2)} 元",
                    f"库存周数：{format_num(row['库存周数'], 2)}",
                    f"建议动作：{row['建议动作']}",
                ],
            ),
            compact_list_html(
                metrics["seasonal_actions"],
                "跨季处理 SKU 明细",
                10,
                "老板做二次判断时使用，先看库存，再看建议动作。",
                lambda row: row["款号"],
                lambda row: f"{row['中类']} / {row['颜色']} / {row['季节']}",
                lambda row: [
                    compact_stat_row("库存", format_num(row["库存"])),
                    compact_stat_row("销售金额", f"{format_num(row['销售金额'], 2)} 元"),
                    compact_stat_row("建议动作", row["建议动作"], is_badge=True, tone="warn"),
                ],
                lambda row: [
                    f"季节策略：{row['季节策略']}",
                    f"库存周数：{format_num(row['库存周数'], 2)}",
                ],
            ),
            compact_list_html(
                metrics["clearance"],
                "去化 SKU 明细",
                10,
                "执行去化时再下钻到具体款，优先看库存深但近期零售弱的款。",
                lambda row: row["商品款号"],
                lambda row: " / ".join(
                    [
                        str(part)
                        for part in [row.get("商品名称", ""), row.get("商品颜色", "")]
                        if str(part).strip()
                    ]
                ),
                lambda row: [
                    compact_stat_row("实际库存", format_num(row["实际库存"])),
                    compact_stat_row("近期零售", format_num(row["近期零售"])),
                    compact_stat_row("建议动作", row["建议动作"], is_badge=True, tone="danger"),
                ],
                lambda row: [
                    f"大类：{row['大类']}",
                    f"中类：{row['中类']}" if row.get("中类") else "",
                    f"小类：{row['小类']}" if row.get("小类") else "",
                    f"零售价：{format_num(row['零售价'], 2)} 元" if row.get("零售价") is not None else "",
                ],
            ),
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
            <a class="download-link" href="./">返回首页</a>
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
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <h1>{cards['store_name']} 老板经营仪表盘</h1>
      <p>首页只保留老板 10 秒内最该知道的事情。总览、经营策略、图表和明细已经拆到详细页，首页更适合每天快速拍板。</p>
      <div class="hero-note">{store_note} · 当前季节：{time_strategy['season']} / {time_strategy['phase']} · 当前阶段：{decision['stage']} · 日销趋势：{decision['sales_trend']['label']}</div>
      <div class="hero-status">
        <div class="hero-status-chip">最近抓取日期：{capture_date}（北京时间）</div>
        <div class="hero-status-chip">数据导入日期：{capture_date}（北京时间）</div>
      </div>
    </section>

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
    insights_html = "".join(f"<li>{item}</li>" for item in metrics["insights"])
    chart_html = "".join(f"<section class='chart-card'>{chart}</section>" for chart in charts)
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
        cost_breakdown_html = "".join(
            [
                compact_list_html(
                    expense_df,
                    "固定费用拆解",
                    10,
                    "这里放的是月固定或分摊后的费用，帮助老板知道利润为什么会被吃掉。",
                    lambda row: row["name"],
                    lambda row: row.get("note", "") or "固定费用项",
                    lambda row: [
                        compact_stat_row("金额", f"{format_num(row['amount'], 2)} 元"),
                    ],
                )
                if not expense_df.empty
                else render_empty("当前没有固定费用明细。"),
                compact_list_html(
                    salary_df,
                    "工资拆解",
                    10,
                    "这里按人员拆工资，方便老板判断人工成本占比和排班压力。",
                    lambda row: row["name"],
                    lambda row: row.get("note", "") or "工资项",
                    lambda row: [
                        compact_stat_row("金额", f"{format_num(row['amount'], 2)} 元"),
                    ],
                )
                if not salary_df.empty
                else render_empty("当前没有工资明细。"),
            ]
        )

    overview_panels_html = f"""
      <div class="detail-grid">
        <div class="module detail-module" style="margin:0;">
          <div class="module-header">
            <h3 class="module-title" style="font-size:18px;">经营健康灯</h3>
            <p class="module-note">红色优先处理，黄色持续盯住，绿色维持节奏。</p>
          </div>
          <div class="health-grid">{health_html}</div>
        </div>
        <div class="module detail-module" style="margin:0;">
          <div class="module-header">
            <h3 class="module-title" style="font-size:18px;">北京时间与季节节奏</h3>
            <p class="module-note">今天 / 本周 / 本月的季节动作参考。</p>
          </div>
          <ul class="insight-list">
            <li>北京时间：{time_strategy['beijing_time']}</li>
            <li>当前判断：{time_strategy['headline']}</li>
            {"".join(f"<li>{item}</li>" for item in time_strategy['daily_actions'])}
            {"".join(f"<li>{item}</li>" for item in time_strategy['weekly_actions'])}
            {"".join(f"<li>{item}</li>" for item in time_strategy['monthly_actions'])}
          </ul>
        </div>
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
      <div class="detail-grid">
        <div class="module detail-module" style="margin:0;">
          <div class="module-header">
            <h3 class="module-title" style="font-size:18px;">道具参考口径</h3>
            <p class="module-note">道具已从主经营指标剥离，只保留为参考值。</p>
          </div>
          <div class="metrics-grid">{reference_html}</div>
        </div>
      </div>
      {f"<div class='detail-grid'>{cost_breakdown_html}</div>" if cost_breakdown_html else ""}
    """
    strategy_panels_html = f"""
      <div class="module detail-module" style="margin:0;">
        <div class="module-header">
          <h3 class="module-title" style="font-size:18px;">自动生成经营方案</h3>
          <p class="module-note">基于当前数据生成的处理方案，适合老板拍板。</p>
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
    inventory_tables_html = "".join(
        [
            compact_list_html(
                metrics["replenish_categories"],
                "补货重点品类",
                8,
                "先按品类定补货优先级，再下钻到单款。",
                lambda row: row["中类"],
                lambda row: f"{row['季节策略']} / 建议补货 SKU {format_num(row['SKU数'])}",
                lambda row: [
                    compact_stat_row("销售额", f"{format_num(row['销售额'], 2)} 元"),
                    compact_stat_row("当前库存", format_num(row["库存"])),
                    compact_stat_row("建议补货量", format_num(row["建议补货量"])),
                ],
                lambda row: [
                    f"季节策略：{row['季节策略']}",
                    f"建议补货 SKU：{format_num(row['SKU数'])}",
                ],
            ),
            compact_list_html(
                metrics["seasonal_categories"],
                "跨季处理重点品类",
                8,
                "先看哪些品类已经跨季，再决定暂缓还是去化。",
                lambda row: row["中类"],
                lambda row: f"{row['季节策略']} / {row['建议动作']}",
                lambda row: [
                    compact_stat_row("库存", format_num(row["库存"])),
                    compact_stat_row("SKU数", format_num(row["SKU数"])),
                    compact_stat_row("建议动作", row["建议动作"], is_badge=True, tone="warn"),
                ],
                lambda row: [
                    f"季节策略：{row['季节策略']}",
                    f"建议动作：{row['建议动作']}",
                ],
            ),
            compact_list_html(
                metrics["clearance_categories"],
                "去化重点品类",
                8,
                "先按品类看库存压力，再安排陈列和促销动作。",
                lambda row: row["大类"],
                lambda row: f"{row['建议动作']} / 高库存低动销",
                lambda row: [
                    compact_stat_row("实际库存", format_num(row["实际库存"])),
                    compact_stat_row("近期零售", format_num(row["近期零售"])),
                    compact_stat_row("建议动作", row["建议动作"], is_badge=True, tone="danger"),
                ],
                lambda row: [
                    f"SKU数：{format_num(row['SKU数'])}",
                ],
            ),
            compact_list_html(
                metrics["replenish"],
                "补货 SKU 明细",
                10,
                "确定品类要补后，再来这里挑具体款。",
                lambda row: row["款号"],
                lambda row: f"{row['中类']} / {row['颜色']}",
                lambda row: [
                    compact_stat_row("库存", format_num(row["库存"])),
                    compact_stat_row("周均销量", format_num(row["周均销量"], 1)),
                    compact_stat_row("建议补货", format_num(row["建议补货量"])),
                ],
                lambda row: [
                    f"销售金额：{format_num(row['销售金额'], 2)} 元",
                    f"库存周数：{format_num(row['库存周数'], 2)}",
                    f"建议动作：{row['建议动作']}",
                ],
            ),
            compact_list_html(
                metrics["seasonal_actions"],
                "跨季处理 SKU 明细",
                10,
                "老板做二次判断时使用，先看库存，再看建议动作。",
                lambda row: row["款号"],
                lambda row: f"{row['中类']} / {row['颜色']} / {row['季节']}",
                lambda row: [
                    compact_stat_row("库存", format_num(row["库存"])),
                    compact_stat_row("销售金额", f"{format_num(row['销售金额'], 2)} 元"),
                    compact_stat_row("建议动作", row["建议动作"], is_badge=True, tone="warn"),
                ],
                lambda row: [
                    f"季节策略：{row['季节策略']}",
                    f"库存周数：{format_num(row['库存周数'], 2)}",
                ],
            ),
            compact_list_html(
                metrics["clearance"],
                "去化 SKU 明细",
                10,
                "执行去化时再下钻到具体款，优先看库存深但近期零售弱的款。",
                lambda row: row["商品款号"],
                lambda row: " / ".join(
                    [
                        str(part)
                        for part in [row.get("商品名称", ""), row.get("商品颜色", "")]
                        if str(part).strip()
                    ]
                ),
                lambda row: [
                    compact_stat_row("实际库存", format_num(row["实际库存"])),
                    compact_stat_row("近期零售", format_num(row["近期零售"])),
                    compact_stat_row("建议动作", row["建议动作"], is_badge=True, tone="danger"),
                ],
                lambda row: [
                    f"大类：{row['大类']}",
                    f"中类：{row['中类']}" if row.get("中类") else "",
                    f"小类：{row['小类']}" if row.get("小类") else "",
                    f"零售价：{format_num(row['零售价'], 2)} 元" if row.get("零售价") is not None else "",
                ],
            ),
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
            <a class="download-link" href="./">打开当前页</a>
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
            "<a href='./'>返回首页</a>",
            "<a href='#overview-section'>总览</a>",
            "<a href='#strategy-section'>经营策略</a>",
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
    .detail-grid, .health-grid, .tip-grid, .playbook-grid, .charts, .tables {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 14px;
      margin-top: 14px;
      min-width: 0;
      max-width: 100%;
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
      .detail-sidebar-card:last-child {{
        display: none;
      }}
      .detail-pane-title {{
        font-size: 18px;
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
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <h1>{cards['store_name']} 详细经营页</h1>
      <p>这是长版详细页。总览和经营策略放在最上面，后面依次看图表、补货去化、会员店员和下载区，更适合复盘和细看。</p>
      <div class="hero-note">{store_note} · 当前季节：{time_strategy['season']} / {time_strategy['phase']} · 日销趋势：{decision['sales_trend']['label']}</div>
      <div class="hero-status">
        <div class="hero-status-chip">最近抓取日期：{capture_date}（北京时间）</div>
        <div class="hero-status-chip">数据导入日期：{capture_date}（北京时间）</div>
      </div>
    </section>

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

    <section class="module" id="charts-section">
      <div class="module-header">
        <h2 class="module-title">图表</h2>
        <p class="module-note">适合看趋势、结构和变化，不适合第一眼就下结论。</p>
      </div>
      <div class="charts">{chart_html}</div>
    </section>

    <section class="module" id="inventory-section">
      <div class="module-header">
        <h2 class="module-title">补货 / 去化</h2>
        <p class="module-note">先看品类，再看 SKU，再看负库存异常。执行时从这里往下钻。</p>
      </div>
      <div class="tables">{inventory_tables_html}</div>
    </section>

    <section class="module" id="people-section">
      <div class="module-header">
        <h2 class="module-title">会员 / 店员 / 参考店</h2>
        <p class="module-note">这一组适合复盘复购、导购执行和其他店铺对比，不参与主店第一页结论。</p>
      </div>
      <div class="tables">{people_tables_html}</div>
    </section>

    <section class="module" id="downloads-section">
      <div class="module-header">
        <h2 class="module-title">下载</h2>
        <p class="module-note">需要转发、导出或交给执行层时，从这里拿 HTML 和 CSV。</p>
      </div>
      {download_cards_html}
    </section>
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
</body>
</html>
"""


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
    lines = [
        f"# {cards['store_name']} 库存销售摘要",
        "",
        "## 老板一分钟结论",
        f"- 结论：{boss_board['headline']}",
        f"- 说明：{boss_board['summary']}",
        f"- 当前经营阶段：{decision['stage']} / {decision['phase']}",
        f"- 日销趋势：{decision['sales_trend']['detail']}",
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
    ])
    if pos_highlights:
        stock_analysis = pos_highlights.get("stock_analysis")
        movement = pos_highlights.get("movement")
        daily_flow = pos_highlights.get("daily_flow")
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
        lines.append("")

    if profit:
        lines.extend([
            "## 利润与保本",
            f"- 毛利额：{format_num(profit['gross_profit'], 2)} 元，毛利率 {format_num(profit['gross_margin_rate'] * 100, 1)}%",
            f"- 固定费用：{format_num(profit['monthly_operating_expense'], 2)} 元，人工费用：{format_num(profit['salary_total'], 2)} 元",
            f"- 总费用：{format_num(profit['total_expense'], 2)} 元，净利润：{format_num(profit['net_profit'], 2)} 元",
            f"- 保本销售额：{format_num(profit['breakeven_sales'], 2)} 元，保本进度：{format_num(profit['breakeven_progress_ratio'] * 100, 1)}%",
            f"- 保本日销：{format_num(profit['breakeven_daily_sales'], 2)} 元，当前平均日销：{format_num(profit['average_daily_sales'], 2)} 元",
            f"- 月末净利预测：{format_num(profit['projected_month_net_profit'], 2)} 元，判断：{profit['forecast_headline']}",
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
    lines.extend(f"- {item}" for item in metrics["insights"])
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
                f"- {row['中类']} / {row['季节策略']}：SKU数 {format_num(row['SKU数'])}，销售额 {format_num(row['销售额'], 2)}，建议补货量 {format_num(row['建议补货量'])}"
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
                f"- {row['款号']} / {row['颜色']}：库存 {format_num(row['库存'])}，周均销量 {format_num(row['周均销量'], 1)}，建议补货 {format_num(row['建议补货量'])}"
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
    primary_reference = metrics["primary_reference"]
    level_map = {"red": "红灯", "yellow": "黄灯", "green": "绿灯"}

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
        lines.append("")

    if profit:
        lines.extend([
            "## 利润与保本",
            "",
            f"- 毛利额：{format_num(profit['gross_profit'], 2)} 元，毛利率 {format_num(profit['gross_margin_rate'] * 100, 1)}%",
            f"- 固定费用：{format_num(profit['monthly_operating_expense'], 2)} 元，人工费用：{format_num(profit['salary_total'], 2)} 元",
            f"- 总费用：{format_num(profit['total_expense'], 2)} 元，净利润：{format_num(profit['net_profit'], 2)} 元",
            f"- 保本销售额：{format_num(profit['breakeven_sales'], 2)} 元，保本进度：{format_num(profit['breakeven_progress_ratio'] * 100, 1)}%",
            f"- 保本日销：{format_num(profit['breakeven_daily_sales'], 2)} 元，当前平均日销：{format_num(profit['average_daily_sales'], 2)} 元",
            f"- 月末销售预测：{format_num(profit['projected_month_sales'], 2)} 元，月末净利预测：{format_num(profit['projected_month_net_profit'], 2)} 元",
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

    if not replenish_categories.empty:
        lines.append("## 补货重点品类 Top 5")
        lines.append("")
        for _, row in replenish_categories.iterrows():
            lines.append(
                f"- {row['中类']} / {row['季节策略']}：SKU数 {format_num(row['SKU数'])}，销售额 {format_num(row['销售额'], 2)}，建议补货量 {format_num(row['建议补货量'])}"
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


def write_outputs(metrics: dict, output_dir: Path, pages_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    pages_dir.mkdir(parents=True, exist_ok=True)
    date_tag = pd.Timestamp.today().strftime("%Y-%m-%d")
    html_path = output_dir / f"库存销售看板_{date_tag}.html"
    detail_html_path = output_dir / f"库存销售详细页_{date_tag}.html"
    latest_html_path = output_dir / "index.html"
    latest_detail_html_path = output_dir / "details.html"
    md_path = output_dir / f"库存销售摘要_{date_tag}.md"
    report_path = output_dir / f"库存销售分析报告_{date_tag}.md"
    replenish_csv = output_dir / f"补货建议清单_{date_tag}.csv"
    clearance_csv = output_dir / f"去化建议清单_{date_tag}.csv"
    category_csv = output_dir / f"品类风险概览_{date_tag}.csv"
    pages_html_path = pages_dir / "index.html"
    pages_detail_html_path = pages_dir / "details.html"
    pages_md_path = pages_dir / "summary.md"
    pages_report_path = pages_dir / "report.md"
    pages_replenish_csv = pages_dir / "补货建议清单.csv"
    pages_clearance_csv = pages_dir / "去化建议清单.csv"
    pages_category_csv = pages_dir / "品类风险概览.csv"
    html_output = build_html(metrics)
    detail_html_output = build_detail_html(metrics)
    markdown_output = build_markdown_summary(metrics)
    report_output = build_business_report(metrics)
    html_path.write_text(html_output, encoding="utf-8")
    detail_html_path.write_text(detail_html_output, encoding="utf-8")
    latest_html_path.write_text(html_output, encoding="utf-8")
    latest_detail_html_path.write_text(detail_html_output, encoding="utf-8")
    md_path.write_text(markdown_output, encoding="utf-8")
    report_path.write_text(report_output, encoding="utf-8")
    metrics["replenish"].to_csv(replenish_csv, index=False, encoding="utf-8-sig")
    metrics["clearance"].to_csv(clearance_csv, index=False, encoding="utf-8-sig")
    metrics["category_risks"].to_csv(category_csv, index=False, encoding="utf-8-sig")
    pages_html_path.write_text(html_output, encoding="utf-8")
    pages_detail_html_path.write_text(detail_html_output, encoding="utf-8")
    pages_md_path.write_text(markdown_output, encoding="utf-8")
    pages_report_path.write_text(report_output, encoding="utf-8")
    metrics["replenish"].to_csv(pages_replenish_csv, index=False, encoding="utf-8-sig")
    metrics["clearance"].to_csv(pages_clearance_csv, index=False, encoding="utf-8-sig")
    metrics["category_risks"].to_csv(pages_category_csv, index=False, encoding="utf-8-sig")
    return {
        "html": html_path,
        "detail_html": detail_html_path,
        "latest_html": latest_html_path,
        "latest_detail_html": latest_detail_html_path,
        "pages_html": pages_html_path,
        "pages_detail_html": pages_detail_html_path,
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
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--pages-dir", type=Path, default=DEFAULT_PAGES_DIR)
    parser.add_argument("--cost-file", type=Path, default=DEFAULT_COST_FILE)
    parser.add_argument("--yeusoft-capture-dir", type=Path, default=DEFAULT_YEU_CAPTURE_DIR)
    parser.add_argument("--store", default=None, help="Optional store name override")
    parser.add_argument("--zip-file", type=Path, default=None, help="Optional zip export to extract and analyze")
    args = parser.parse_args()
    cost_snapshot = load_cost_snapshot(args.cost_file)
    yeusoft_capture_bundle = load_yeusoft_capture_bundle(args.yeusoft_capture_dir)

    if args.zip_file:
        with tempfile.TemporaryDirectory(prefix="inventory_zip_") as temp_dir:
            extract_dir = Path(temp_dir)
            with zipfile.ZipFile(args.zip_file) as zf:
                zf.extractall(extract_dir)

            reports = resolve_reports(extract_dir)
            raw = load_data(reports)
            store_name = infer_store_name(raw, args.store)
            cleaned = clean_data(raw, store_name)
            metrics = build_metrics(
                cleaned,
                store_name,
                cost_snapshot=cost_snapshot,
                yeusoft_capture_bundle=yeusoft_capture_bundle,
            )
            outputs = write_outputs(metrics, args.output_dir, args.pages_dir)
    else:
        reports = resolve_reports(args.input_dir)
        raw = load_data(reports)
        store_name = infer_store_name(raw, args.store)
        cleaned = clean_data(raw, store_name)
        metrics = build_metrics(
            cleaned,
            store_name,
            cost_snapshot=cost_snapshot,
            yeusoft_capture_bundle=yeusoft_capture_bundle,
        )
        outputs = write_outputs(metrics, args.output_dir, args.pages_dir)

    print(f"Store: {store_name}")
    print(f"HTML dashboard: {outputs['html']}")
    print(f"Latest HTML dashboard: {outputs['latest_html']}")
    print(f"Pages HTML dashboard: {outputs['pages_html']}")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
