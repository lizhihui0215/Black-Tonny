#!/usr/bin/env python3
"""Build a reproducible SQLite analysis database from calibrated sales sources."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.tools.calibrate_sales import (  # noqa: E402
    DEFAULT_STORE_NAME,
    PRIMARY_INPUT,
    build_daily_sales,
    build_monthly_sales,
    build_sku_sales,
    compare_master_to_flow,
    compare_master_to_product,
    compare_sales_overlap,
    load_capture_daily_flow,
    load_capture_movement,
    load_capture_product_sales,
    load_capture_sales_master,
    load_capture_store_retail_validation,
)
from scripts.dashboard.yeusoft import (  # noqa: E402
    decode_yeusoft_text,
    extract_capture_request,
    extract_capture_response,
    extract_capture_rows,
    normalize_yeusoft_frame,
)


DEFAULT_CAPTURE_DIR = ROOT / "reports" / "capture-cache"
DEFAULT_DB_PATH = ROOT / "reports" / "calibration" / "black_tony_analysis.sqlite"


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS import_batches (
    batch_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    store_name TEXT NOT NULL,
    primary_input TEXT NOT NULL,
    inferred_store_name TEXT,
    capture_dir TEXT NOT NULL,
    input_dir TEXT NOT NULL,
    script_path TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS source_files (
    batch_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_role TEXT NOT NULL,
    source_path TEXT NOT NULL,
    file_sha256 TEXT,
    captured_at TEXT,
    requested_range_json TEXT,
    row_count_before INTEGER,
    row_count_after INTEGER,
    removed_total_like_rows INTEGER,
    removed_blank_key_rows INTEGER,
    metadata_json TEXT,
    PRIMARY KEY (batch_id, source_name),
    FOREIGN KEY (batch_id) REFERENCES import_batches(batch_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sales_order_lines (
    line_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_role TEXT NOT NULL,
    is_master_source INTEGER NOT NULL,
    is_primary_store INTEGER NOT NULL,
    store_name TEXT,
    input_user TEXT,
    sale_date TEXT,
    sale_day TEXT,
    sale_month TEXT,
    order_no TEXT,
    line_no TEXT,
    sale_line_key TEXT,
    style_color_key TEXT,
    sku_size_key TEXT,
    sku TEXT,
    color TEXT,
    size TEXT,
    qty REAL,
    sales_amount REAL,
    tag_amount REAL,
    unit_price REAL,
    discount_rate REAL,
    doc_type TEXT,
    flow_doc_type TEXT,
    member_card TEXT,
    guide_name TEXT,
    product_major_type TEXT,
    product_middle_type TEXT,
    product_minor_type TEXT,
    is_prop INTEGER NOT NULL,
    is_return INTEGER NOT NULL,
    gross_sales_amount REAL,
    return_offset_amount REAL,
    net_sales_amount REAL,
    gross_sales_qty REAL,
    return_offset_qty REAL,
    net_sales_qty REAL,
    FOREIGN KEY (batch_id) REFERENCES import_batches(batch_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS daily_flow_docs (
    flow_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    store_name TEXT NOT NULL,
    sale_date TEXT,
    sale_day TEXT,
    sale_month TEXT,
    order_no TEXT,
    doc_type TEXT,
    actual_money REAL,
    sales_qty REAL,
    tag_amount REAL,
    cash_money REAL,
    wx_money REAL,
    alipay_money REAL,
    coupon_money REAL,
    activity_money REAL,
    other_money REAL,
    FOREIGN KEY (batch_id) REFERENCES import_batches(batch_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS product_sales_snapshot (
    snapshot_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    store_name TEXT NOT NULL,
    sku TEXT,
    color TEXT,
    style_color_key TEXT,
    cumulative_sales_qty REAL,
    cumulative_sales_amount REAL,
    cumulative_return_qty REAL,
    current_stock_qty REAL,
    arrival_qty REAL,
    category_name TEXT,
    first_arrival_date TEXT,
    first_sale_date TEXT,
    is_prop INTEGER NOT NULL,
    FOREIGN KEY (batch_id) REFERENCES import_batches(batch_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS movement_docs (
    movement_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    store_name TEXT NOT NULL,
    doc_type TEXT,
    doc_status TEXT,
    transfer_type TEXT,
    from_store TEXT,
    to_store TEXT,
    qty REAL,
    amount REAL,
    come_date TEXT,
    receive_date TEXT,
    FOREIGN KEY (batch_id) REFERENCES import_batches(batch_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS inventory_detail_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    store_name TEXT NOT NULL,
    department_name TEXT,
    sku TEXT,
    product_name TEXT,
    color TEXT,
    product_major_type TEXT,
    product_middle_type TEXT,
    product_minor_type TEXT,
    year_label TEXT,
    season TEXT,
    period_label TEXT,
    retail_price REAL,
    brand_name TEXT,
    sex_label TEXT,
    total_stock_qty REAL,
    total_stock_amount REAL,
    total_retail_qty REAL,
    total_retail_amount REAL,
    size_json TEXT,
    FOREIGN KEY (batch_id) REFERENCES import_batches(batch_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS inventory_sales_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    store_name TEXT NOT NULL,
    department_name TEXT,
    sku TEXT,
    product_name TEXT,
    color TEXT,
    product_major_type TEXT,
    product_middle_type TEXT,
    product_minor_type TEXT,
    year_label TEXT,
    season TEXT,
    period_label TEXT,
    retail_price REAL,
    brand_name TEXT,
    stock_sale_ratio REAL,
    total_retail_qty REAL,
    total_retail_amount REAL,
    size_json TEXT,
    FOREIGN KEY (batch_id) REFERENCES import_batches(batch_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS stock_flow_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    store_name TEXT NOT NULL,
    brand_name TEXT,
    product_major_type TEXT,
    product_middle_type TEXT,
    product_minor_type TEXT,
    sku TEXT,
    product_name TEXT,
    retail_price REAL,
    opening_qty REAL,
    arrival_qty REAL,
    transfer_in_qty REAL,
    return_qty REAL,
    transfer_out_qty REAL,
    sale_qty REAL,
    ledger_stock_qty REAL,
    damage_qty REAL,
    actual_stock_qty REAL,
    wait_stock_qty REAL,
    sell_through_rate REAL,
    year_label TEXT,
    season TEXT,
    period_label TEXT,
    sex_label TEXT,
    color TEXT,
    color_code TEXT,
    image_url TEXT,
    FOREIGN KEY (batch_id) REFERENCES import_batches(batch_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS size_metric_breakdowns (
    breakdown_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    store_name TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    metric_scope TEXT NOT NULL,
    size_column TEXT NOT NULL,
    size_label TEXT,
    metric_value REAL,
    FOREIGN KEY (batch_id) REFERENCES import_batches(batch_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS vip_analysis_members (
    member_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    store_name TEXT NOT NULL,
    operator_name TEXT,
    vip_name TEXT,
    vip_card_id TEXT,
    vip_grade TEXT,
    vip_card_type TEXT,
    birth_date TEXT,
    current_point REAL,
    total_point REAL,
    return_money REAL,
    stored_value_spend REAL,
    stored_value_balance REAL,
    vip_pos_card_num REAL,
    input_date TEXT,
    last_sale_date TEXT,
    avg_sale_amount REAL,
    sale_count_per_year REAL,
    sale_stock_qty REAL,
    sale_order_count REAL,
    total_sale_amount REAL,
    sale_week TEXT,
    sale_gap_days REAL,
    vip_type TEXT,
    vip_tag TEXT,
    FOREIGN KEY (batch_id) REFERENCES import_batches(batch_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS member_sales_rank (
    rank_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    store_name TEXT NOT NULL,
    rank_no REAL,
    user_name TEXT,
    vip_card_id TEXT,
    order_count REAL,
    style_count REAL,
    sale_qty REAL,
    sale_amount REAL,
    sale_share REAL,
    image_url TEXT,
    FOREIGN KEY (batch_id) REFERENCES import_batches(batch_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS guide_report_summary (
    guide_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    store_name TEXT NOT NULL,
    guide_name TEXT,
    sale_qty REAL,
    retail_amount REAL,
    discount_rate REAL,
    sale_amount REAL,
    cash_amount REAL,
    card_amount REAL,
    order_money REAL,
    stored_value_amount REAL,
    return_amount REAL,
    activity_amount REAL,
    coupon_amount REAL,
    wechat_amount REAL,
    alipay_amount REAL,
    other_amount REAL,
    wipe_zero_amount REAL,
    vip_sale_qty REAL,
    vip_sale_amount REAL,
    order_count REAL,
    recharge_amount REAL,
    average_ticket REAL,
    attachment_rate REAL,
    sale_amount_ratio REAL,
    sale_qty_ratio REAL,
    rebate_amount REAL,
    FOREIGN KEY (batch_id) REFERENCES import_batches(batch_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS retail_detail_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    store_name TEXT NOT NULL,
    department_name TEXT,
    sku TEXT,
    product_name TEXT,
    color TEXT,
    retail_price REAL,
    total_qty REAL,
    total_retail_amount REAL,
    total_sale_amount REAL,
    discount_rate REAL,
    brand_name TEXT,
    product_major_type TEXT,
    product_middle_type TEXT,
    product_minor_type TEXT,
    year_label TEXT,
    season TEXT,
    period_label TEXT,
    sex_label TEXT,
    size_json TEXT,
    FOREIGN KEY (batch_id) REFERENCES import_batches(batch_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS daily_sales_summary (
    batch_id TEXT NOT NULL,
    sale_date TEXT NOT NULL,
    gross_sales_amount REAL,
    return_offset_amount REAL,
    net_sales_amount REAL,
    prop_gross_sales_amount REAL,
    prop_return_offset_amount REAL,
    prop_net_sales_amount REAL,
    all_goods_net_sales_amount REAL,
    flow_sales_related_actual_money REAL,
    flow_sales_related_cash_money REAL,
    flow_sales_actual_money REAL,
    flow_exchange_actual_money REAL,
    flow_return_actual_money REAL,
    flow_stored_value_actual_money REAL,
    gross_sales_qty REAL,
    return_offset_qty REAL,
    net_sales_qty REAL,
    core_order_count REAL,
    all_goods_order_count REAL,
    is_trusted_core_sales INTEGER NOT NULL,
    cash_scope TEXT,
    PRIMARY KEY (batch_id, sale_date),
    FOREIGN KEY (batch_id) REFERENCES import_batches(batch_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS monthly_sales_summary (
    batch_id TEXT NOT NULL,
    month TEXT NOT NULL,
    gross_sales_amount REAL,
    return_offset_amount REAL,
    net_sales_amount REAL,
    prop_gross_sales_amount REAL,
    prop_return_offset_amount REAL,
    prop_net_sales_amount REAL,
    all_goods_net_sales_amount REAL,
    flow_sales_related_actual_money REAL,
    flow_sales_related_cash_money REAL,
    flow_sales_actual_money REAL,
    flow_exchange_actual_money REAL,
    flow_return_actual_money REAL,
    flow_stored_value_actual_money REAL,
    gross_sales_qty REAL,
    return_offset_qty REAL,
    net_sales_qty REAL,
    core_order_count REAL,
    all_goods_order_count REAL,
    is_trusted_core_sales INTEGER NOT NULL,
    cash_scope TEXT,
    PRIMARY KEY (batch_id, month),
    FOREIGN KEY (batch_id) REFERENCES import_batches(batch_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sku_sales_summary (
    batch_id TEXT NOT NULL,
    sku TEXT NOT NULL,
    color TEXT NOT NULL,
    product_major_type TEXT,
    product_middle_type TEXT,
    gross_sales_amount REAL,
    return_offset_amount REAL,
    net_sales_amount REAL,
    gross_sales_qty REAL,
    return_offset_qty REAL,
    net_sales_qty REAL,
    order_count INTEGER,
    PRIMARY KEY (batch_id, sku, color, product_major_type, product_middle_type),
    FOREIGN KEY (batch_id) REFERENCES import_batches(batch_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS quality_checks (
    check_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    check_name TEXT NOT NULL,
    check_scope TEXT NOT NULL,
    status TEXT NOT NULL,
    severity TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    observed_value TEXT,
    expected_value TEXT,
    diff_value REAL,
    threshold_value REAL,
    detail_json TEXT,
    FOREIGN KEY (batch_id) REFERENCES import_batches(batch_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS order_reconciliation_results (
    result_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    comparison_label TEXT NOT NULL,
    flow_doc_type TEXT,
    order_no TEXT NOT NULL,
    left_amount REAL,
    right_amount REAL,
    amount_diff REAL,
    amount_diff_ratio REAL,
    left_qty REAL,
    right_qty REAL,
    qty_diff REAL,
    left_line_count REAL,
    right_line_count REAL,
    line_count_diff REAL,
    is_problem INTEGER NOT NULL,
    FOREIGN KEY (batch_id) REFERENCES import_batches(batch_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS daily_reconciliation_results (
    result_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    comparison_label TEXT NOT NULL,
    flow_doc_type TEXT,
    sale_day TEXT NOT NULL,
    left_amount REAL,
    right_amount REAL,
    amount_diff REAL,
    left_qty REAL,
    right_qty REAL,
    qty_diff REAL,
    left_orders REAL,
    right_orders REAL,
    order_diff REAL,
    is_problem INTEGER NOT NULL,
    FOREIGN KEY (batch_id) REFERENCES import_batches(batch_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sku_reconciliation_results (
    result_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    comparison_label TEXT NOT NULL,
    sku TEXT NOT NULL,
    color TEXT NOT NULL,
    left_amount REAL,
    right_amount REAL,
    amount_diff REAL,
    left_qty REAL,
    right_qty REAL,
    qty_diff REAL,
    right_return_qty REAL,
    is_problem INTEGER NOT NULL,
    FOREIGN KEY (batch_id) REFERENCES import_batches(batch_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sales_lines_batch_source ON sales_order_lines(batch_id, source_name);
CREATE INDEX IF NOT EXISTS idx_sales_lines_sale_day ON sales_order_lines(batch_id, sale_day);
CREATE INDEX IF NOT EXISTS idx_sales_lines_sale_month ON sales_order_lines(batch_id, sale_month);
CREATE INDEX IF NOT EXISTS idx_sales_lines_order_no ON sales_order_lines(batch_id, order_no);
CREATE INDEX IF NOT EXISTS idx_sales_lines_sku ON sales_order_lines(batch_id, sku, color, size);
CREATE INDEX IF NOT EXISTS idx_flow_docs_order_no ON daily_flow_docs(batch_id, order_no, doc_type);
CREATE INDEX IF NOT EXISTS idx_flow_docs_sale_day ON daily_flow_docs(batch_id, sale_day);
CREATE INDEX IF NOT EXISTS idx_product_snapshot_sku ON product_sales_snapshot(batch_id, sku, color);
CREATE INDEX IF NOT EXISTS idx_movement_docs_type ON movement_docs(batch_id, doc_type);
CREATE INDEX IF NOT EXISTS idx_inventory_detail_sku ON inventory_detail_snapshots(batch_id, sku, color);
CREATE INDEX IF NOT EXISTS idx_inventory_sales_sku ON inventory_sales_snapshots(batch_id, sku, color);
CREATE INDEX IF NOT EXISTS idx_stock_flow_sku ON stock_flow_snapshots(batch_id, sku, color);
CREATE INDEX IF NOT EXISTS idx_size_breakdown_snapshot ON size_metric_breakdowns(batch_id, source_name, snapshot_id);
CREATE INDEX IF NOT EXISTS idx_vip_analysis_member ON vip_analysis_members(batch_id, vip_card_id);
CREATE INDEX IF NOT EXISTS idx_member_sales_rank_member ON member_sales_rank(batch_id, vip_card_id);
CREATE INDEX IF NOT EXISTS idx_guide_report_name ON guide_report_summary(batch_id, guide_name);
CREATE INDEX IF NOT EXISTS idx_retail_detail_sku ON retail_detail_snapshots(batch_id, sku, color);
CREATE INDEX IF NOT EXISTS idx_quality_checks_batch ON quality_checks(batch_id, status);

CREATE VIEW IF NOT EXISTS latest_import_batch AS
SELECT *
FROM import_batches
WHERE created_at = (SELECT MAX(created_at) FROM import_batches);

CREATE VIEW IF NOT EXISTS latest_sales_order_lines AS
SELECT sol.*
FROM sales_order_lines sol
JOIN latest_import_batch lib ON sol.batch_id = lib.batch_id;

CREATE VIEW IF NOT EXISTS latest_master_sales_order_lines AS
SELECT *
FROM latest_sales_order_lines
WHERE source_role = 'master';

CREATE VIEW IF NOT EXISTS latest_inventory_detail_snapshots AS
SELECT ids.*
FROM inventory_detail_snapshots ids
JOIN latest_import_batch lib ON ids.batch_id = lib.batch_id;

CREATE VIEW IF NOT EXISTS latest_inventory_sales_snapshots AS
SELECT iss.*
FROM inventory_sales_snapshots iss
JOIN latest_import_batch lib ON iss.batch_id = lib.batch_id;

CREATE VIEW IF NOT EXISTS latest_stock_flow_snapshots AS
SELECT sfs.*
FROM stock_flow_snapshots sfs
JOIN latest_import_batch lib ON sfs.batch_id = lib.batch_id;

CREATE VIEW IF NOT EXISTS latest_size_metric_breakdowns AS
SELECT smb.*
FROM size_metric_breakdowns smb
JOIN latest_import_batch lib ON smb.batch_id = lib.batch_id;

CREATE VIEW IF NOT EXISTS latest_vip_analysis_members AS
SELECT vam.*
FROM vip_analysis_members vam
JOIN latest_import_batch lib ON vam.batch_id = lib.batch_id;

CREATE VIEW IF NOT EXISTS latest_member_sales_rank AS
SELECT msr.*
FROM member_sales_rank msr
JOIN latest_import_batch lib ON msr.batch_id = lib.batch_id;

CREATE VIEW IF NOT EXISTS latest_guide_report_summary AS
SELECT grs.*
FROM guide_report_summary grs
JOIN latest_import_batch lib ON grs.batch_id = lib.batch_id;

CREATE VIEW IF NOT EXISTS latest_retail_detail_snapshots AS
SELECT rds.*
FROM retail_detail_snapshots rds
JOIN latest_import_batch lib ON rds.batch_id = lib.batch_id;

CREATE VIEW IF NOT EXISTS latest_daily_sales_summary AS
SELECT dss.*
FROM daily_sales_summary dss
JOIN latest_import_batch lib ON dss.batch_id = lib.batch_id;

CREATE VIEW IF NOT EXISTS latest_monthly_sales_summary AS
SELECT mss.*
FROM monthly_sales_summary mss
JOIN latest_import_batch lib ON mss.batch_id = lib.batch_id;

CREATE VIEW IF NOT EXISTS latest_sku_sales_summary AS
SELECT sss.*
FROM sku_sales_summary sss
JOIN latest_import_batch lib ON sss.batch_id = lib.batch_id;

CREATE VIEW IF NOT EXISTS latest_quality_checks AS
SELECT qc.*
FROM quality_checks qc
JOIN latest_import_batch lib ON qc.batch_id = lib.batch_id;
"""


def make_batch_id() -> str:
    return f"sales_calibration_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def ensure_text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def normalize_datetime_text(value: object) -> str | None:
    timestamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(timestamp):
        return None
    return timestamp.strftime("%Y-%m-%d %H:%M:%S")


def normalize_date_text(value: object) -> str | None:
    timestamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(timestamp):
        return None
    return timestamp.strftime("%Y-%m-%d")


def build_key(*parts: object) -> str:
    return "|".join(ensure_text(part) for part in parts)


def safe_float(value: object) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return 0.0
    return float(numeric)


def file_sha256(path_text: str) -> str | None:
    path = Path(path_text)
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_text(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def extract_report_payload(capture_payload: dict | None, url_keyword: str) -> tuple[dict, dict]:
    body = extract_capture_response(capture_payload, url_keyword) or {}
    retdata = body.get("retdata") or []
    payload = retdata[0] if retdata and isinstance(retdata[0], dict) else {}
    request_payload = extract_capture_request(capture_payload, url_keyword) or {}
    return payload, request_payload


def extract_size_label_map(title_rows: object) -> dict[str, str]:
    if not isinstance(title_rows, list) or not title_rows:
        return {}
    title_row = title_rows[0]
    if not isinstance(title_row, dict):
        return {}

    mapping: dict[str, str] = {}
    for column, raw_label in title_row.items():
        if not str(column).startswith("col"):
            continue
        decoded = decode_yeusoft_text(raw_label)
        parts = [
            part.strip()
            for part in pd.Series([decoded]).str.split(r"<br\s*/?>", regex=True).explode().tolist()
            if part and part.strip() and part.strip() != "\u3000"
        ]
        deduped: list[str] = []
        for part in parts:
            if part not in deduped:
                deduped.append(part)
        mapping[str(column)] = "/".join(deduped[:2]) if deduped else str(column)
    return mapping


def extract_size_payload(
    row: pd.Series,
    *,
    size_columns: list[str],
    size_labels: dict[str, str],
) -> tuple[str, list[dict[str, object]]]:
    size_payload: dict[str, float] = {}
    breakdown_rows: list[dict[str, object]] = []
    for column in size_columns:
        value = float(pd.to_numeric(row.get(column), errors="coerce") or 0.0)
        if abs(value) < 1e-9:
            continue
        label = size_labels.get(column, column)
        size_payload[label] = value
        breakdown_rows.append(
            {
                "size_column": column,
                "size_label": label,
                "metric_value": value,
            }
        )
    return json_text(size_payload), breakdown_rows


def load_capture_inventory_detail(capture_dir: Path, store_name: str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    capture_path = capture_dir / "库存明细统计.json"
    payload = json.loads(capture_path.read_text(encoding="utf-8"))
    rows, request_payload = extract_capture_rows(payload, "SelDeptStockWaitList")
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(), pd.DataFrame(), {
            "source_name": "capture_inventory_detail",
            "path": str(capture_path),
            "requested_range": request_payload,
            "captured_at": payload.get("capturedAt"),
            "row_count_before": 0,
            "row_count_after": 0,
            "removed_total_like_rows": 0,
            "removed_blank_key_rows": 0,
        }

    report_payload, _ = extract_report_payload(payload, "SelDeptStockWaitList")
    size_labels = extract_size_label_map(report_payload.get("Title"))
    size_columns = sorted([column for column in frame.columns if str(column).startswith("col")])
    numeric_columns = size_columns + ["RetailPrice", "NTotalNum", "NTotalMoney", "STotalNum", "STotalMoney"]
    frame = normalize_yeusoft_frame(frame, numeric_columns)
    before_count = len(frame)
    frame = frame[frame.get("Spec", "").astype(str).str.strip().ne("")].copy()
    frame = frame[frame.get("DeptName", "").astype(str).str.strip().eq(store_name)].copy()

    snapshot_rows: list[dict[str, object]] = []
    size_breakdowns: list[dict[str, object]] = []
    for _, row in frame.iterrows():
        snapshot_id = build_key("capture_inventory_detail", store_name, row.get("Spec"), row.get("ColorName"))
        size_json, size_rows = extract_size_payload(row, size_columns=size_columns, size_labels=size_labels)
        snapshot_rows.append(
            {
                "snapshot_id": snapshot_id,
                "source_name": "capture_inventory_detail",
                "store_name": store_name,
                "department_name": ensure_text(row.get("DeptName")),
                "sku": ensure_text(row.get("Spec")),
                "product_name": ensure_text(row.get("WareName")),
                "color": ensure_text(row.get("ColorName")),
                "product_major_type": ensure_text(row.get("Type")),
                "product_middle_type": ensure_text(row.get("Type1")),
                "product_minor_type": ensure_text(row.get("Type2")),
                "year_label": ensure_text(row.get("Date1")),
                "season": ensure_text(row.get("Season")),
                "period_label": ensure_text(row.get("Pd")),
                "retail_price": safe_float(row.get("RetailPrice")),
                "brand_name": ensure_text(row.get("Trade")),
                "sex_label": ensure_text(row.get("Sex")),
                "total_stock_qty": safe_float(row.get("NTotalNum")),
                "total_stock_amount": safe_float(row.get("NTotalMoney")),
                "total_retail_qty": safe_float(row.get("STotalNum")),
                "total_retail_amount": safe_float(row.get("STotalMoney")),
                "size_json": size_json,
            }
        )
        for size_row in size_rows:
            size_breakdowns.append(
                {
                    "source_name": "capture_inventory_detail",
                    "store_name": store_name,
                    "snapshot_id": snapshot_id,
                    "metric_scope": "stock_qty",
                    **size_row,
                }
            )

    return pd.DataFrame(snapshot_rows), pd.DataFrame(size_breakdowns), {
        "source_name": "capture_inventory_detail",
        "path": str(capture_path),
        "requested_range": request_payload,
        "captured_at": payload.get("capturedAt"),
        "row_count_before": before_count,
        "row_count_after": len(snapshot_rows),
        "removed_total_like_rows": 0,
        "removed_blank_key_rows": int(before_count - len(snapshot_rows)),
    }


def load_capture_inventory_sales(capture_dir: Path, store_name: str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    capture_path = capture_dir / "库存零售统计.json"
    payload = json.loads(capture_path.read_text(encoding="utf-8"))
    rows, request_payload = extract_capture_rows(payload, "SelDeptStockSaleList")
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(), pd.DataFrame(), {
            "source_name": "capture_inventory_sales",
            "path": str(capture_path),
            "requested_range": request_payload,
            "captured_at": payload.get("capturedAt"),
            "row_count_before": 0,
            "row_count_after": 0,
            "removed_total_like_rows": 0,
            "removed_blank_key_rows": 0,
        }

    report_payload, _ = extract_report_payload(payload, "SelDeptStockSaleList")
    size_labels = extract_size_label_map(report_payload.get("Title"))
    size_columns = sorted([column for column in frame.columns if str(column).startswith("col")])
    numeric_columns = size_columns + ["RetailPrice", "STotalNum", "STotalMoney", "StoU"]
    frame = normalize_yeusoft_frame(frame, numeric_columns)
    before_count = len(frame)
    frame = frame[frame.get("Spec", "").astype(str).str.strip().ne("")].copy()
    frame = frame[frame.get("DeptName", "").astype(str).str.strip().eq(store_name)].copy()

    snapshot_rows: list[dict[str, object]] = []
    size_breakdowns: list[dict[str, object]] = []
    for _, row in frame.iterrows():
        snapshot_id = build_key("capture_inventory_sales", store_name, row.get("Spec"), row.get("ColorName"))
        size_json, size_rows = extract_size_payload(row, size_columns=size_columns, size_labels=size_labels)
        snapshot_rows.append(
            {
                "snapshot_id": snapshot_id,
                "source_name": "capture_inventory_sales",
                "store_name": store_name,
                "department_name": ensure_text(row.get("DeptName")),
                "sku": ensure_text(row.get("Spec")),
                "product_name": ensure_text(row.get("WareName")),
                "color": ensure_text(row.get("ColorName")),
                "product_major_type": ensure_text(row.get("Type")),
                "product_middle_type": ensure_text(row.get("Type1")),
                "product_minor_type": ensure_text(row.get("Type2")),
                "year_label": ensure_text(row.get("Date1")),
                "season": ensure_text(row.get("Season")),
                "period_label": ensure_text(row.get("Pd")),
                "retail_price": safe_float(row.get("RetailPrice")),
                "brand_name": ensure_text(row.get("Trade")),
                "stock_sale_ratio": safe_float(row.get("StoU")),
                "total_retail_qty": safe_float(row.get("STotalNum")),
                "total_retail_amount": safe_float(row.get("STotalMoney")),
                "size_json": size_json,
            }
        )
        for size_row in size_rows:
            size_breakdowns.append(
                {
                    "source_name": "capture_inventory_sales",
                    "store_name": store_name,
                    "snapshot_id": snapshot_id,
                    "metric_scope": "retail_qty",
                    **size_row,
                }
            )

    return pd.DataFrame(snapshot_rows), pd.DataFrame(size_breakdowns), {
        "source_name": "capture_inventory_sales",
        "path": str(capture_path),
        "requested_range": request_payload,
        "captured_at": payload.get("capturedAt"),
        "row_count_before": before_count,
        "row_count_after": len(snapshot_rows),
        "removed_total_like_rows": 0,
        "removed_blank_key_rows": int(before_count - len(snapshot_rows)),
    }


def load_capture_stock_flow(capture_dir: Path) -> tuple[pd.DataFrame, dict]:
    capture_path = capture_dir / "进销存统计.json"
    payload = json.loads(capture_path.read_text(encoding="utf-8"))
    rows, request_payload = extract_capture_rows(payload, "SelInSalesReport")
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(), {
            "source_name": "capture_stock_flow",
            "path": str(capture_path),
            "requested_range": request_payload,
            "captured_at": payload.get("capturedAt"),
            "row_count_before": 0,
            "row_count_after": 0,
            "removed_total_like_rows": 0,
            "removed_blank_key_rows": 0,
        }

    numeric_columns = [
        "RetailPrice",
        "LastAmount",
        "InAmount",
        "TBInAmount",
        "RetuAmount",
        "TBOutAmount",
        "SaleAmount",
        "ZMStockNum",
        "BSOutAmount",
        "StockNum",
        "WaitStockNum",
        "dxl",
    ]
    frame = normalize_yeusoft_frame(frame, numeric_columns)
    before_count = len(frame)
    frame = frame[frame.get("SpeNum", "").astype(str).str.strip().ne("")].copy()
    standardized = pd.DataFrame(
        {
            "snapshot_id": frame.apply(
                lambda row: build_key("capture_stock_flow", row.get("SpeNum"), row.get("ColorName")),
                axis=1,
            ),
            "source_name": "capture_stock_flow",
            "brand_name": frame.get("TrademarkName", "").fillna("").astype(str).str.strip(),
            "product_major_type": frame.get("dl", "").fillna("").astype(str).str.strip(),
            "product_middle_type": frame.get("zl", "").fillna("").astype(str).str.strip(),
            "product_minor_type": frame.get("xl", "").fillna("").astype(str).str.strip(),
            "sku": frame.get("SpeNum", "").fillna("").astype(str).str.strip(),
            "product_name": frame.get("WareName", "").fillna("").astype(str).str.strip(),
            "retail_price": pd.to_numeric(frame.get("RetailPrice", 0), errors="coerce").fillna(0.0),
            "opening_qty": pd.to_numeric(frame.get("LastAmount", 0), errors="coerce").fillna(0.0),
            "arrival_qty": pd.to_numeric(frame.get("InAmount", 0), errors="coerce").fillna(0.0),
            "transfer_in_qty": pd.to_numeric(frame.get("TBInAmount", 0), errors="coerce").fillna(0.0),
            "return_qty": pd.to_numeric(frame.get("RetuAmount", 0), errors="coerce").fillna(0.0),
            "transfer_out_qty": pd.to_numeric(frame.get("TBOutAmount", 0), errors="coerce").fillna(0.0),
            "sale_qty": pd.to_numeric(frame.get("SaleAmount", 0), errors="coerce").fillna(0.0),
            "ledger_stock_qty": pd.to_numeric(frame.get("ZMStockNum", 0), errors="coerce").fillna(0.0),
            "damage_qty": pd.to_numeric(frame.get("BSOutAmount", 0), errors="coerce").fillna(0.0),
            "actual_stock_qty": pd.to_numeric(frame.get("StockNum", 0), errors="coerce").fillna(0.0),
            "wait_stock_qty": pd.to_numeric(frame.get("WaitStockNum", 0), errors="coerce").fillna(0.0),
            "sell_through_rate": pd.to_numeric(frame.get("dxl", 0), errors="coerce").fillna(0.0),
            "year_label": frame.get("Year", "").fillna("").astype(str).str.strip(),
            "season": frame.get("Season", "").fillna("").astype(str).str.strip(),
            "period_label": frame.get("PdName", "").fillna("").astype(str).str.strip(),
            "sex_label": frame.get("Sex", "").fillna("").astype(str).str.strip(),
            "color": frame.get("ColorName", "").fillna("").astype(str).str.strip(),
            "color_code": frame.get("ColorCode", "").fillna("").astype(str).str.strip(),
            "image_url": frame.get("Img", "").fillna("").astype(str).str.strip(),
        }
    )
    return standardized, {
        "source_name": "capture_stock_flow",
        "path": str(capture_path),
        "requested_range": request_payload,
        "captured_at": payload.get("capturedAt"),
        "row_count_before": before_count,
        "row_count_after": len(standardized),
        "removed_total_like_rows": 0,
        "removed_blank_key_rows": int(before_count - len(standardized)),
    }


def load_capture_vip_analysis(capture_dir: Path, store_name: str) -> tuple[pd.DataFrame, dict]:
    capture_path = capture_dir / "会员综合分析.json"
    payload = json.loads(capture_path.read_text(encoding="utf-8"))
    report_payload, request_payload = extract_report_payload(payload, "SelVipAnalysisReport")
    rows = report_payload.get("Data") or []
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(), {
            "source_name": "capture_vip_analysis",
            "path": str(capture_path),
            "requested_range": request_payload,
            "captured_at": payload.get("capturedAt"),
            "row_count_before": 0,
            "row_count_after": 0,
            "removed_total_like_rows": 0,
            "removed_blank_key_rows": 0,
        }

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
        "SaleSpace",
    ]
    frame = normalize_yeusoft_frame(frame, numeric_columns)
    before_count = len(frame)
    frame = frame[frame.get("VipCardID", "").astype(str).str.strip().ne("")].copy()
    for column in ("BirthDate", "InputDate", "LastSaleDate"):
        if column in frame.columns:
            frame[column] = pd.to_datetime(frame[column], errors="coerce")
    standardized = pd.DataFrame(
        {
            "member_id": frame.apply(
                lambda row: build_key("capture_vip_analysis", store_name, row.get("VipCardID")),
                axis=1,
            ),
            "source_name": "capture_vip_analysis",
            "store_name": store_name,
            "operator_name": frame.get("OperName", "").fillna("").astype(str).str.strip(),
            "vip_name": frame.get("VipName", "").fillna("").astype(str).str.strip(),
            "vip_card_id": frame.get("VipCardID", "").fillna("").astype(str).str.strip(),
            "vip_grade": frame.get("VipGrade", "").fillna("").astype(str).str.strip(),
            "vip_card_type": frame.get("VipCardType", "").fillna("").astype(str).str.strip(),
            "birth_date": frame.get("BirthDate"),
            "current_point": pd.to_numeric(frame.get("Point", 0), errors="coerce").fillna(0.0),
            "total_point": pd.to_numeric(frame.get("TotalPoint", 0), errors="coerce").fillna(0.0),
            "return_money": pd.to_numeric(frame.get("RetuMoney", 0), errors="coerce").fillna(0.0),
            "stored_value_spend": pd.to_numeric(frame.get("SSMoney", 0), errors="coerce").fillna(0.0),
            "stored_value_balance": pd.to_numeric(frame.get("BVMoney", 0), errors="coerce").fillna(0.0),
            "vip_pos_card_num": pd.to_numeric(frame.get("VipPosCardNum", 0), errors="coerce").fillna(0.0),
            "input_date": frame.get("InputDate"),
            "last_sale_date": frame.get("LastSaleDate"),
            "avg_sale_amount": pd.to_numeric(frame.get("EachSale", 0), errors="coerce").fillna(0.0),
            "sale_count_per_year": pd.to_numeric(frame.get("SaleNumByYear", 0), errors="coerce").fillna(0.0),
            "sale_stock_qty": pd.to_numeric(frame.get("SaleStock", 0), errors="coerce").fillna(0.0),
            "sale_order_count": pd.to_numeric(frame.get("SaleNum", 0), errors="coerce").fillna(0.0),
            "total_sale_amount": pd.to_numeric(frame.get("TotalMoney", 0), errors="coerce").fillna(0.0),
            "sale_week": frame.get("SaleWeek", "").fillna("").astype(str).str.strip(),
            "sale_gap_days": pd.to_numeric(frame.get("SaleSpace", 0), errors="coerce").fillna(0.0),
            "vip_type": frame.get("VipType", "").fillna("").astype(str).str.strip(),
            "vip_tag": frame.get("VipTag", "").fillna("").astype(str).str.strip(),
        }
    )
    return standardized, {
        "source_name": "capture_vip_analysis",
        "path": str(capture_path),
        "requested_range": request_payload,
        "captured_at": payload.get("capturedAt"),
        "row_count_before": before_count,
        "row_count_after": len(standardized),
        "removed_total_like_rows": 0,
        "removed_blank_key_rows": int(before_count - len(standardized)),
    }


def load_capture_member_rank(capture_dir: Path, store_name: str) -> tuple[pd.DataFrame, dict]:
    capture_path = capture_dir / "会员消费排行.json"
    payload = json.loads(capture_path.read_text(encoding="utf-8"))
    rows, request_payload = extract_capture_rows(payload, "SelVipSaleRank")
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(), {
            "source_name": "capture_member_rank",
            "path": str(capture_path),
            "requested_range": request_payload,
            "captured_at": payload.get("capturedAt"),
            "row_count_before": 0,
            "row_count_after": 0,
            "removed_total_like_rows": 0,
            "removed_blank_key_rows": 0,
        }

    frame = normalize_yeusoft_frame(frame, ["Num", "N", "WareCnt", "TN", "TM", "P"])
    before_count = len(frame)
    frame = frame[
        frame.get("UserName", "").astype(str).str.strip().ne("")
        | frame.get("VipCardID", "").astype(str).str.strip().ne("")
    ].copy()
    standardized = pd.DataFrame(
        {
            "rank_id": frame.apply(
                lambda row: build_key("capture_member_rank", store_name, row.get("VipCardID"), row.get("Num")),
                axis=1,
            ),
            "source_name": "capture_member_rank",
            "store_name": store_name,
            "rank_no": pd.to_numeric(frame.get("Num", 0), errors="coerce").fillna(0.0),
            "user_name": frame.get("UserName", "").fillna("").astype(str).str.strip(),
            "vip_card_id": frame.get("VipCardID", "").fillna("").astype(str).str.strip(),
            "order_count": pd.to_numeric(frame.get("N", 0), errors="coerce").fillna(0.0),
            "style_count": pd.to_numeric(frame.get("WareCnt", 0), errors="coerce").fillna(0.0),
            "sale_qty": pd.to_numeric(frame.get("TN", 0), errors="coerce").fillna(0.0),
            "sale_amount": pd.to_numeric(frame.get("TM", 0), errors="coerce").fillna(0.0),
            "sale_share": pd.to_numeric(frame.get("P", 0), errors="coerce").fillna(0.0),
            "image_url": frame.get("Img", "").fillna("").astype(str).str.strip(),
        }
    )
    return standardized, {
        "source_name": "capture_member_rank",
        "path": str(capture_path),
        "requested_range": request_payload,
        "captured_at": payload.get("capturedAt"),
        "row_count_before": before_count,
        "row_count_after": len(standardized),
        "removed_total_like_rows": 0,
        "removed_blank_key_rows": int(before_count - len(standardized)),
    }


def load_capture_guide_report(capture_dir: Path, store_name: str) -> tuple[pd.DataFrame, dict]:
    capture_path = capture_dir / "导购员报表.json"
    payload = json.loads(capture_path.read_text(encoding="utf-8"))
    report_payload, request_payload = extract_report_payload(payload, "SelPersonSale")
    rows = report_payload.get("Data") or []
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(), {
            "source_name": "capture_guide_report",
            "path": str(capture_path),
            "requested_range": request_payload,
            "captured_at": payload.get("capturedAt"),
            "row_count_before": 0,
            "row_count_after": 0,
            "removed_total_like_rows": 0,
            "removed_blank_key_rows": 0,
        }

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
    frame = normalize_yeusoft_frame(frame, numeric_columns)
    before_count = len(frame)
    frame = frame[frame.get("Name", "").astype(str).str.strip().ne("")].copy()
    standardized = pd.DataFrame(
        {
            "guide_id": frame.apply(
                lambda row: build_key("capture_guide_report", store_name, row.get("Name")),
                axis=1,
            ),
            "source_name": "capture_guide_report",
            "store_name": store_name,
            "guide_name": frame.get("Name", "").fillna("").astype(str).str.strip(),
            "sale_qty": pd.to_numeric(frame.get("Amount", 0), errors="coerce").fillna(0.0),
            "retail_amount": pd.to_numeric(frame.get("TotalRetailMoeny", 0), errors="coerce").fillna(0.0),
            "discount_rate": pd.to_numeric(frame.get("DisCount", 0), errors="coerce").fillna(0.0),
            "sale_amount": pd.to_numeric(frame.get("TotalMoney", 0), errors="coerce").fillna(0.0),
            "cash_amount": pd.to_numeric(frame.get("Cash", 0), errors="coerce").fillna(0.0),
            "card_amount": pd.to_numeric(frame.get("CreditCard", 0), errors="coerce").fillna(0.0),
            "order_money": pd.to_numeric(frame.get("OrderMoney", 0), errors="coerce").fillna(0.0),
            "stored_value_amount": pd.to_numeric(frame.get("PosMoney", 0), errors="coerce").fillna(0.0),
            "return_amount": pd.to_numeric(frame.get("RetuMoney", 0), errors="coerce").fillna(0.0),
            "activity_amount": pd.to_numeric(frame.get("ActivityMoeny", 0), errors="coerce").fillna(0.0),
            "coupon_amount": pd.to_numeric(frame.get("StockMoney", 0), errors="coerce").fillna(0.0),
            "wechat_amount": pd.to_numeric(frame.get("WxPayMoney", 0), errors="coerce").fillna(0.0),
            "alipay_amount": pd.to_numeric(frame.get("ZfbPayMoney", 0), errors="coerce").fillna(0.0),
            "other_amount": pd.to_numeric(frame.get("OddMoney", 0), errors="coerce").fillna(0.0),
            "wipe_zero_amount": pd.to_numeric(frame.get("WpZeroMoney", 0), errors="coerce").fillna(0.0),
            "vip_sale_qty": pd.to_numeric(frame.get("VipAmount", 0), errors="coerce").fillna(0.0),
            "vip_sale_amount": pd.to_numeric(frame.get("VipMoney", 0), errors="coerce").fillna(0.0),
            "order_count": pd.to_numeric(frame.get("Saleps", 0), errors="coerce").fillna(0.0),
            "recharge_amount": pd.to_numeric(frame.get("StockRechargeMoney", 0), errors="coerce").fillna(0.0),
            "average_ticket": pd.to_numeric(frame.get("DJ", 0), errors="coerce").fillna(0.0),
            "attachment_rate": pd.to_numeric(frame.get("FJ", 0), errors="coerce").fillna(0.0),
            "sale_amount_ratio": pd.to_numeric(frame.get("JEZB", 0), errors="coerce").fillna(0.0),
            "sale_qty_ratio": pd.to_numeric(frame.get("SLZB", 0), errors="coerce").fillna(0.0),
            "rebate_amount": pd.to_numeric(frame.get("ssMoneyRebate", 0), errors="coerce").fillna(0.0),
        }
    )
    return standardized, {
        "source_name": "capture_guide_report",
        "path": str(capture_path),
        "requested_range": request_payload,
        "captured_at": payload.get("capturedAt"),
        "row_count_before": before_count,
        "row_count_after": len(standardized),
        "removed_total_like_rows": 0,
        "removed_blank_key_rows": int(before_count - len(standardized)),
    }


def load_capture_retail_detail(capture_dir: Path, store_name: str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    capture_path = capture_dir / "零售明细统计.json"
    payload = json.loads(capture_path.read_text(encoding="utf-8"))
    report_payload, request_payload = extract_report_payload(payload, "SelDeptSaleList")
    rows = report_payload.get("Data") or []
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(), pd.DataFrame(), {
            "source_name": "capture_retail_detail",
            "path": str(capture_path),
            "requested_range": request_payload,
            "captured_at": payload.get("capturedAt"),
            "row_count_before": 0,
            "row_count_after": 0,
            "removed_total_like_rows": 0,
            "removed_blank_key_rows": 0,
        }

    size_labels = extract_size_label_map(report_payload.get("Title"))
    size_columns = sorted([column for column in frame.columns if str(column).startswith("col")])
    numeric_columns = size_columns + ["RetailPrice", "TotalNum", "TotalRetailMoney", "TotalMoney", "Discount"]
    frame = normalize_yeusoft_frame(frame, numeric_columns)
    before_count = len(frame)
    frame = frame[frame.get("Spec", "").astype(str).str.strip().ne("")].copy()
    frame = frame[frame.get("DeptName", "").astype(str).str.strip().eq(store_name)].copy()

    snapshot_rows: list[dict[str, object]] = []
    size_breakdowns: list[dict[str, object]] = []
    for _, row in frame.iterrows():
        snapshot_id = build_key("capture_retail_detail", store_name, row.get("Spec"), row.get("ColorName"))
        size_json, size_rows = extract_size_payload(row, size_columns=size_columns, size_labels=size_labels)
        snapshot_rows.append(
            {
                "snapshot_id": snapshot_id,
                "source_name": "capture_retail_detail",
                "store_name": store_name,
                "department_name": ensure_text(row.get("DeptName")),
                "sku": ensure_text(row.get("Spec")),
                "product_name": ensure_text(row.get("WareName")),
                "color": ensure_text(row.get("ColorName")),
                "retail_price": safe_float(row.get("RetailPrice")),
                "total_qty": safe_float(row.get("TotalNum")),
                "total_retail_amount": safe_float(row.get("TotalRetailMoney")),
                "total_sale_amount": safe_float(row.get("TotalMoney")),
                "discount_rate": safe_float(row.get("Discount")),
                "brand_name": ensure_text(row.get("Trade")),
                "product_major_type": ensure_text(row.get("Type")),
                "product_middle_type": ensure_text(row.get("Type1")),
                "product_minor_type": ensure_text(row.get("Type2")),
                "year_label": ensure_text(row.get("Years")),
                "season": ensure_text(row.get("Season")),
                "period_label": ensure_text(row.get("Pd")),
                "sex_label": ensure_text(row.get("Sex")),
                "size_json": size_json,
            }
        )
        for size_row in size_rows:
            size_breakdowns.append(
                {
                    "source_name": "capture_retail_detail",
                    "store_name": store_name,
                    "snapshot_id": snapshot_id,
                    "metric_scope": "retail_detail_qty",
                    **size_row,
                }
            )

    return pd.DataFrame(snapshot_rows), pd.DataFrame(size_breakdowns), {
        "source_name": "capture_retail_detail",
        "path": str(capture_path),
        "requested_range": request_payload,
        "captured_at": payload.get("capturedAt"),
        "row_count_before": before_count,
        "row_count_after": len(snapshot_rows),
        "removed_total_like_rows": 0,
        "removed_blank_key_rows": int(before_count - len(snapshot_rows)),
    }


def append_frame(conn: sqlite3.Connection, table_name: str, frame: pd.DataFrame) -> None:
    if frame.empty:
        return
    frame.to_sql(table_name, conn, if_exists="append", index=False)


def prepare_source_files_rows(
    batch_id: str,
    source_specs: list[tuple[str, str, dict]],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for source_name, source_role, audit in source_specs:
        path_text = ensure_text(audit.get("path", ""))
        requested_range = audit.get("requested_range", {})
        metadata = {
            key: value
            for key, value in audit.items()
            if key not in {"path", "requested_range", "captured_at", "row_count_before", "row_count_after", "removed_total_like_rows", "removed_blank_key_rows"}
        }
        rows.append(
            {
                "batch_id": batch_id,
                "source_name": source_name,
                "source_role": source_role,
                "source_path": path_text,
                "file_sha256": file_sha256(path_text) if path_text else None,
                "captured_at": normalize_datetime_text(audit.get("captured_at")),
                "requested_range_json": json_text(requested_range),
                "row_count_before": int(audit.get("row_count_before", 0) or 0),
                "row_count_after": int(audit.get("row_count_after", 0) or 0),
                "removed_total_like_rows": int(audit.get("removed_total_like_rows", 0) or 0),
                "removed_blank_key_rows": int(audit.get("removed_blank_key_rows", 0) or 0),
                "metadata_json": json_text(metadata),
            }
        )
    return pd.DataFrame(rows)


def prepare_sales_order_lines(
    frame: pd.DataFrame,
    *,
    batch_id: str,
    source_name: str,
    source_role: str,
    primary_store: str,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    prepared = frame.copy()
    prepared["store_name"] = prepared["store_name"].fillna("").astype(str).str.strip()
    prepared["input_user"] = prepared["input_user"].fillna("").astype(str).str.strip()
    prepared["line_no"] = prepared["line_no"].fillna("").astype(str).str.strip()
    prepared["sale_date"] = prepared["sale_date"].apply(normalize_datetime_text)
    prepared["sale_day"] = prepared["sale_day"].apply(normalize_date_text)
    prepared["sale_month"] = prepared["sale_month"].fillna("").astype(str)
    prepared["sale_line_key"] = prepared.apply(
        lambda row: build_key(row["store_name"], row["order_no"], row["line_no"]),
        axis=1,
    )
    prepared["style_color_key"] = prepared.apply(
        lambda row: build_key(row["store_name"], row["sku"], row["color"]),
        axis=1,
    )
    prepared["sku_size_key"] = prepared.apply(
        lambda row: build_key(row["store_name"], row["sku"], row["color"], row["size"]),
        axis=1,
    )
    prepared["line_id"] = prepared.apply(
        lambda row: build_key(batch_id, source_name, row["sale_line_key"], row["sku"], row["sale_date"]),
        axis=1,
    )
    prepared["batch_id"] = batch_id
    prepared["source_name"] = source_name
    prepared["source_role"] = source_role
    prepared["is_master_source"] = 1 if source_role == "master" else 0
    prepared["is_primary_store"] = prepared["store_name"].eq(primary_store).astype(int)
    prepared["is_prop"] = prepared["is_prop"].astype(int)
    prepared["is_return"] = prepared["is_return"].astype(int)
    columns = [
        "line_id",
        "batch_id",
        "source_name",
        "source_role",
        "is_master_source",
        "is_primary_store",
        "store_name",
        "input_user",
        "sale_date",
        "sale_day",
        "sale_month",
        "order_no",
        "line_no",
        "sale_line_key",
        "style_color_key",
        "sku_size_key",
        "sku",
        "color",
        "size",
        "qty",
        "sales_amount",
        "tag_amount",
        "unit_price",
        "discount_rate",
        "doc_type",
        "flow_doc_type",
        "member_card",
        "guide_name",
        "product_major_type",
        "product_middle_type",
        "product_minor_type",
        "is_prop",
        "is_return",
        "gross_sales_amount",
        "return_offset_amount",
        "net_sales_amount",
        "gross_sales_qty",
        "return_offset_qty",
        "net_sales_qty",
    ]
    return prepared[columns].copy()


def prepare_daily_flow_rows(
    frame: pd.DataFrame,
    *,
    batch_id: str,
    store_name: str,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    prepared = frame.copy()
    prepared["sale_date"] = prepared["sale_date"].apply(normalize_datetime_text)
    prepared["sale_day"] = prepared["sale_day"].apply(normalize_date_text)
    prepared["sale_month"] = prepared["sale_month"].fillna("").astype(str)
    prepared["flow_id"] = prepared.apply(
        lambda row: build_key(batch_id, row["source_name"], row["order_no"], row["doc_type"], row["sale_date"]),
        axis=1,
    )
    prepared["batch_id"] = batch_id
    prepared["store_name"] = store_name
    columns = [
        "flow_id",
        "batch_id",
        "source_name",
        "store_name",
        "sale_date",
        "sale_day",
        "sale_month",
        "order_no",
        "doc_type",
        "actual_money",
        "sales_qty",
        "tag_amount",
        "cash_money",
        "wx_money",
        "alipay_money",
        "coupon_money",
        "activity_money",
        "other_money",
    ]
    return prepared[columns].copy()


def prepare_product_sales_snapshot(
    frame: pd.DataFrame,
    *,
    batch_id: str,
    store_name: str,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    prepared = frame.copy()
    prepared["snapshot_id"] = prepared.apply(
        lambda row: build_key(batch_id, row["source_name"], row["sku"], row["color"]),
        axis=1,
    )
    prepared["batch_id"] = batch_id
    prepared["store_name"] = store_name
    prepared["style_color_key"] = prepared.apply(
        lambda row: build_key(store_name, row["sku"], row["color"]),
        axis=1,
    )
    prepared["first_arrival_date"] = prepared["first_arrival_date"].apply(normalize_date_text)
    prepared["first_sale_date"] = prepared["first_sale_date"].apply(normalize_date_text)
    prepared["is_prop"] = prepared["is_prop"].astype(int)
    columns = [
        "snapshot_id",
        "batch_id",
        "source_name",
        "store_name",
        "sku",
        "color",
        "style_color_key",
        "cumulative_sales_qty",
        "cumulative_sales_amount",
        "cumulative_return_qty",
        "current_stock_qty",
        "arrival_qty",
        "category_name",
        "first_arrival_date",
        "first_sale_date",
        "is_prop",
    ]
    return prepared[columns].copy()


def prepare_movement_docs(
    frame: pd.DataFrame,
    *,
    batch_id: str,
    store_name: str,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    prepared = frame.copy()
    prepared["come_date"] = prepared["come_date"].apply(normalize_datetime_text)
    prepared["receive_date"] = prepared["receive_date"].apply(normalize_datetime_text)
    prepared["movement_id"] = prepared.apply(
        lambda row: build_key(
            batch_id,
            row["source_name"],
            row["doc_type"],
            row["come_date"],
            row["receive_date"],
            row["from_store"],
            row["to_store"],
            row["qty"],
            row["amount"],
        ),
        axis=1,
    )
    prepared["batch_id"] = batch_id
    prepared["store_name"] = store_name
    columns = [
        "movement_id",
        "batch_id",
        "source_name",
        "store_name",
        "doc_type",
        "doc_status",
        "transfer_type",
        "from_store",
        "to_store",
        "qty",
        "amount",
        "come_date",
        "receive_date",
    ]
    return prepared[columns].copy()


def prepare_inventory_snapshot_rows(
    frame: pd.DataFrame,
    *,
    batch_id: str,
    store_name: str,
    value_columns: list[str],
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    prepared = frame.copy()
    prepared["snapshot_id"] = prepared["snapshot_id"].apply(lambda value: build_key(batch_id, value))
    prepared["batch_id"] = batch_id
    prepared["store_name"] = store_name
    columns = [
        "snapshot_id",
        "batch_id",
        "source_name",
        "store_name",
        "department_name",
        "sku",
        "product_name",
        "color",
        "product_major_type",
        "product_middle_type",
        "product_minor_type",
        "year_label",
        "season",
        "period_label",
        "retail_price",
        "brand_name",
    ] + value_columns + ["size_json"]
    return prepared[columns].copy()


def prepare_size_breakdown_rows(
    frame: pd.DataFrame,
    *,
    batch_id: str,
    store_name: str,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    prepared = frame.copy()
    prepared["snapshot_id"] = prepared["snapshot_id"].apply(lambda value: build_key(batch_id, value))
    prepared["breakdown_id"] = prepared.apply(
        lambda row: build_key(
            batch_id,
            row["source_name"],
            row["snapshot_id"],
            row["metric_scope"],
            row["size_column"],
        ),
        axis=1,
    )
    prepared["batch_id"] = batch_id
    prepared["store_name"] = store_name
    columns = [
        "breakdown_id",
        "batch_id",
        "source_name",
        "store_name",
        "snapshot_id",
        "metric_scope",
        "size_column",
        "size_label",
        "metric_value",
    ]
    return prepared[columns].copy()


def prepare_stock_flow_snapshot_rows(
    frame: pd.DataFrame,
    *,
    batch_id: str,
    store_name: str,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    prepared = frame.copy()
    prepared["snapshot_id"] = prepared["snapshot_id"].apply(lambda value: build_key(batch_id, value))
    prepared["batch_id"] = batch_id
    prepared["store_name"] = store_name
    columns = [
        "snapshot_id",
        "batch_id",
        "source_name",
        "store_name",
        "brand_name",
        "product_major_type",
        "product_middle_type",
        "product_minor_type",
        "sku",
        "product_name",
        "retail_price",
        "opening_qty",
        "arrival_qty",
        "transfer_in_qty",
        "return_qty",
        "transfer_out_qty",
        "sale_qty",
        "ledger_stock_qty",
        "damage_qty",
        "actual_stock_qty",
        "wait_stock_qty",
        "sell_through_rate",
        "year_label",
        "season",
        "period_label",
        "sex_label",
        "color",
        "color_code",
        "image_url",
    ]
    return prepared[columns].copy()


def prepare_vip_analysis_rows(
    frame: pd.DataFrame,
    *,
    batch_id: str,
    store_name: str,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    prepared = frame.copy()
    prepared["member_id"] = prepared["member_id"].apply(lambda value: build_key(batch_id, value))
    prepared["batch_id"] = batch_id
    prepared["store_name"] = store_name
    for column in ("birth_date", "input_date", "last_sale_date"):
        prepared[column] = prepared[column].apply(normalize_date_text)
    columns = [
        "member_id",
        "batch_id",
        "source_name",
        "store_name",
        "operator_name",
        "vip_name",
        "vip_card_id",
        "vip_grade",
        "vip_card_type",
        "birth_date",
        "current_point",
        "total_point",
        "return_money",
        "stored_value_spend",
        "stored_value_balance",
        "vip_pos_card_num",
        "input_date",
        "last_sale_date",
        "avg_sale_amount",
        "sale_count_per_year",
        "sale_stock_qty",
        "sale_order_count",
        "total_sale_amount",
        "sale_week",
        "sale_gap_days",
        "vip_type",
        "vip_tag",
    ]
    return prepared[columns].copy()


def prepare_member_rank_rows(
    frame: pd.DataFrame,
    *,
    batch_id: str,
    store_name: str,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    prepared = frame.copy()
    prepared["rank_id"] = prepared["rank_id"].apply(lambda value: build_key(batch_id, value))
    prepared["batch_id"] = batch_id
    prepared["store_name"] = store_name
    columns = [
        "rank_id",
        "batch_id",
        "source_name",
        "store_name",
        "rank_no",
        "user_name",
        "vip_card_id",
        "order_count",
        "style_count",
        "sale_qty",
        "sale_amount",
        "sale_share",
        "image_url",
    ]
    return prepared[columns].copy()


def prepare_guide_report_rows(
    frame: pd.DataFrame,
    *,
    batch_id: str,
    store_name: str,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    prepared = frame.copy()
    prepared["guide_id"] = prepared["guide_id"].apply(lambda value: build_key(batch_id, value))
    prepared["batch_id"] = batch_id
    prepared["store_name"] = store_name
    columns = [
        "guide_id",
        "batch_id",
        "source_name",
        "store_name",
        "guide_name",
        "sale_qty",
        "retail_amount",
        "discount_rate",
        "sale_amount",
        "cash_amount",
        "card_amount",
        "order_money",
        "stored_value_amount",
        "return_amount",
        "activity_amount",
        "coupon_amount",
        "wechat_amount",
        "alipay_amount",
        "other_amount",
        "wipe_zero_amount",
        "vip_sale_qty",
        "vip_sale_amount",
        "order_count",
        "recharge_amount",
        "average_ticket",
        "attachment_rate",
        "sale_amount_ratio",
        "sale_qty_ratio",
        "rebate_amount",
    ]
    return prepared[columns].copy()


def prepare_retail_detail_rows(
    frame: pd.DataFrame,
    *,
    batch_id: str,
    store_name: str,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    prepared = frame.copy()
    prepared["snapshot_id"] = prepared["snapshot_id"].apply(lambda value: build_key(batch_id, value))
    prepared["batch_id"] = batch_id
    prepared["store_name"] = store_name
    columns = [
        "snapshot_id",
        "batch_id",
        "source_name",
        "store_name",
        "department_name",
        "sku",
        "product_name",
        "color",
        "retail_price",
        "total_qty",
        "total_retail_amount",
        "total_sale_amount",
        "discount_rate",
        "brand_name",
        "product_major_type",
        "product_middle_type",
        "product_minor_type",
        "year_label",
        "season",
        "period_label",
        "sex_label",
        "size_json",
    ]
    return prepared[columns].copy()


def prepare_period_summary(frame: pd.DataFrame, *, batch_id: str, key_column: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    prepared = frame.copy()
    prepared["batch_id"] = batch_id
    prepared["is_trusted_core_sales"] = prepared["is_trusted_core_sales"].astype(int)
    ordered_columns = ["batch_id", key_column] + [column for column in prepared.columns if column not in {"batch_id", key_column}]
    return prepared[ordered_columns].copy()


def prepare_quality_checks(
    *,
    batch_id: str,
    store_name: str,
    master_lines: pd.DataFrame,
    retail_comparison: dict[str, object],
    product_comparison: dict[str, object],
    flow_comparison: dict[str, object],
    flow_rows: pd.DataFrame,
    movement_rows: pd.DataFrame,
) -> pd.DataFrame:
    latest_sale_day = normalize_date_text(master_lines["sale_day"].max()) if not master_lines.empty else None
    retail_tail_gap = 0
    if not master_lines.empty and not retail_comparison["daily_comparison"].empty:
        overlap_end = pd.to_datetime(retail_comparison["overlap_end"], errors="coerce")
        master_end = pd.to_datetime(master_lines["sale_day"].max(), errors="coerce")
        if pd.notna(overlap_end) and pd.notna(master_end):
            retail_tail_gap = max((master_end - overlap_end).days, 0)

    checks = [
        {
            "check_name": "master_vs_store_retail_daily",
            "check_scope": "validation",
            "status": "pass" if retail_comparison["max_daily_amount_diff"] <= 1 else "fail",
            "severity": "error" if retail_comparison["max_daily_amount_diff"] > 1 else "info",
            "metric_name": "max_daily_amount_diff",
            "observed_value": f"{retail_comparison['max_daily_amount_diff']:.2f}",
            "expected_value": "<= 1.00",
            "diff_value": float(retail_comparison["max_daily_amount_diff"]),
            "threshold_value": 1.0,
            "detail_json": json_text(
                {
                    "overlap_start": normalize_date_text(retail_comparison["overlap_start"]),
                    "overlap_end": normalize_date_text(retail_comparison["overlap_end"]),
                }
            ),
        },
        {
            "check_name": "master_vs_store_retail_orders",
            "check_scope": "validation",
            "status": "pass" if retail_comparison["problem_orders"].empty else "fail",
            "severity": "error" if not retail_comparison["problem_orders"].empty else "info",
            "metric_name": "problem_order_count",
            "observed_value": str(len(retail_comparison["problem_orders"])),
            "expected_value": "0",
            "diff_value": float(len(retail_comparison["problem_orders"])),
            "threshold_value": 0.0,
            "detail_json": json_text({"comparison": "master_vs_store_retail"}),
        },
        {
            "check_name": "master_vs_product_core_amount",
            "check_scope": "cumulative_validation",
            "status": "pass" if abs(product_comparison["core_amount_diff"]) <= 0.01 else "fail",
            "severity": "error" if abs(product_comparison["core_amount_diff"]) > 0.01 else "info",
            "metric_name": "core_amount_diff",
            "observed_value": f"{product_comparison['core_amount_diff']:.2f}",
            "expected_value": "0.00",
            "diff_value": float(product_comparison["core_amount_diff"]),
            "threshold_value": 0.01,
            "detail_json": json_text({"comparison": "master_vs_product_sales"}),
        },
        {
            "check_name": "master_vs_product_core_qty",
            "check_scope": "cumulative_validation",
            "status": "pass" if abs(product_comparison["core_qty_diff"]) <= 0.01 else "fail",
            "severity": "error" if abs(product_comparison["core_qty_diff"]) > 0.01 else "info",
            "metric_name": "core_qty_diff",
            "observed_value": f"{product_comparison['core_qty_diff']:.2f}",
            "expected_value": "0.00",
            "diff_value": float(product_comparison["core_qty_diff"]),
            "threshold_value": 0.01,
            "detail_json": json_text({"comparison": "master_vs_product_sales"}),
        },
        {
            "check_name": "master_vs_flow_orders",
            "check_scope": "cash_validation",
            "status": "pass" if flow_comparison["problem_orders"].empty else "fail",
            "severity": "error" if not flow_comparison["problem_orders"].empty else "info",
            "metric_name": "problem_order_count",
            "observed_value": str(len(flow_comparison["problem_orders"])),
            "expected_value": "0",
            "diff_value": float(len(flow_comparison["problem_orders"])),
            "threshold_value": 0.0,
            "detail_json": json_text({"comparison": "master_vs_daily_flow"}),
        },
        {
            "check_name": "sales_related_cash_money",
            "check_scope": "cash_validation",
            "status": "info",
            "severity": "info",
            "metric_name": "sales_related_cash_money",
            "observed_value": f"{flow_comparison['sales_related_cash_money']:.2f}",
            "expected_value": None,
            "diff_value": None,
            "threshold_value": None,
            "detail_json": json_text({"doc_types": ["销售", "换货", "退货"]}),
        },
        {
            "check_name": "stored_value_actual_money",
            "check_scope": "cash_validation",
            "status": "info",
            "severity": "info",
            "metric_name": "stored_value_actual_money",
            "observed_value": f"{flow_comparison['stored_value_money']:.2f}",
            "expected_value": None,
            "diff_value": None,
            "threshold_value": None,
            "detail_json": json_text({"doc_type": "储值"}),
        },
        {
            "check_name": "retail_validation_tail_gap_days",
            "check_scope": "coverage",
            "status": "warning" if retail_tail_gap > 0 else "pass",
            "severity": "warning" if retail_tail_gap > 0 else "info",
            "metric_name": "tail_gap_days",
            "observed_value": str(retail_tail_gap),
            "expected_value": "0",
            "diff_value": float(retail_tail_gap),
            "threshold_value": 0.0,
            "detail_json": json_text({"latest_master_sale_day": latest_sale_day}),
        },
        {
            "check_name": "movement_has_sku_detail",
            "check_scope": "inventory_context",
            "status": "warning",
            "severity": "warning",
            "metric_name": "has_sku_detail",
            "observed_value": "false",
            "expected_value": "true",
            "diff_value": 1.0,
            "threshold_value": 0.0,
            "detail_json": json_text(
                {
                    "movement_rows": len(movement_rows),
                    "reason": "当前只有单据头，缺少 SKU 行级字段。",
                }
            ),
        },
        {
            "check_name": "latest_master_sale_day",
            "check_scope": "master",
            "status": "info",
            "severity": "info",
            "metric_name": "latest_sale_day",
            "observed_value": latest_sale_day,
            "expected_value": None,
            "diff_value": None,
            "threshold_value": None,
            "detail_json": json_text({"master_row_count": len(master_lines), "flow_row_count": len(flow_rows)}),
        },
    ]
    frame = pd.DataFrame(checks)
    frame["batch_id"] = batch_id
    frame["check_id"] = frame.apply(
        lambda row: build_key(batch_id, row["check_name"], row["metric_name"]),
        axis=1,
    )
    columns = [
        "check_id",
        "batch_id",
        "check_name",
        "check_scope",
        "status",
        "severity",
        "metric_name",
        "observed_value",
        "expected_value",
        "diff_value",
        "threshold_value",
        "detail_json",
    ]
    return frame[columns].copy()


def prepare_order_reconciliation(
    frame: pd.DataFrame,
    *,
    batch_id: str,
    comparison_label: str,
    amount_columns: tuple[str, str],
    qty_columns: tuple[str, str],
    line_count_columns: tuple[str | None, str | None] = (None, None),
    flow_doc_type_column: str | None = None,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    prepared = frame.copy()
    left_amount, right_amount = amount_columns
    left_qty, right_qty = qty_columns
    left_line, right_line = line_count_columns
    prepared["flow_doc_type"] = (
        prepared[flow_doc_type_column].fillna("").astype(str) if flow_doc_type_column and flow_doc_type_column in prepared.columns else ""
    )
    prepared["left_amount"] = prepared[left_amount]
    prepared["right_amount"] = prepared[right_amount]
    prepared["left_qty"] = prepared[left_qty]
    prepared["right_qty"] = prepared[right_qty]
    prepared["left_line_count"] = prepared[left_line] if left_line and left_line in prepared.columns else None
    prepared["right_line_count"] = prepared[right_line] if right_line and right_line in prepared.columns else None
    prepared["line_count_diff"] = (
        prepared["left_line_count"] - prepared["right_line_count"]
        if left_line and right_line and left_line in prepared.columns and right_line in prepared.columns
        else None
    )
    prepared["is_problem"] = (
        (prepared["amount_diff"].abs() > 1) | (prepared["amount_diff_ratio"].fillna(0.0) > 0.001)
    ).astype(int)
    prepared["batch_id"] = batch_id
    prepared["comparison_label"] = comparison_label
    prepared["result_id"] = prepared.apply(
        lambda row: build_key(batch_id, comparison_label, row["order_no"], row["flow_doc_type"]),
        axis=1,
    )
    columns = [
        "result_id",
        "batch_id",
        "comparison_label",
        "flow_doc_type",
        "order_no",
        "left_amount",
        "right_amount",
        "amount_diff",
        "amount_diff_ratio",
        "left_qty",
        "right_qty",
        "qty_diff",
        "left_line_count",
        "right_line_count",
        "line_count_diff",
        "is_problem",
    ]
    return prepared[columns].copy()


def prepare_daily_reconciliation(
    frame: pd.DataFrame,
    *,
    batch_id: str,
    comparison_label: str,
    amount_columns: tuple[str, str],
    qty_columns: tuple[str | None, str | None] = (None, None),
    order_columns: tuple[str | None, str | None] = (None, None),
    flow_doc_type_column: str | None = None,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    prepared = frame.copy()
    left_amount, right_amount = amount_columns
    left_qty, right_qty = qty_columns
    left_orders, right_orders = order_columns
    prepared["sale_day"] = prepared["sale_day"].apply(normalize_date_text)
    prepared["flow_doc_type"] = (
        prepared[flow_doc_type_column].fillna("").astype(str) if flow_doc_type_column and flow_doc_type_column in prepared.columns else ""
    )
    prepared["left_amount"] = prepared[left_amount]
    prepared["right_amount"] = prepared[right_amount]
    prepared["left_qty"] = prepared[left_qty] if left_qty and left_qty in prepared.columns else None
    prepared["right_qty"] = prepared[right_qty] if right_qty and right_qty in prepared.columns else None
    prepared["qty_diff"] = (
        prepared["left_qty"] - prepared["right_qty"]
        if left_qty and right_qty and left_qty in prepared.columns and right_qty in prepared.columns
        else None
    )
    prepared["left_orders"] = prepared[left_orders] if left_orders and left_orders in prepared.columns else None
    prepared["right_orders"] = prepared[right_orders] if right_orders and right_orders in prepared.columns else None
    prepared["order_diff"] = (
        prepared["left_orders"] - prepared["right_orders"]
        if left_orders and right_orders and left_orders in prepared.columns and right_orders in prepared.columns
        else None
    )
    prepared["is_problem"] = prepared["amount_diff"].abs().gt(1).astype(int)
    prepared["batch_id"] = batch_id
    prepared["comparison_label"] = comparison_label
    prepared["result_id"] = prepared.apply(
        lambda row: build_key(batch_id, comparison_label, row["sale_day"], row["flow_doc_type"]),
        axis=1,
    )
    columns = [
        "result_id",
        "batch_id",
        "comparison_label",
        "flow_doc_type",
        "sale_day",
        "left_amount",
        "right_amount",
        "amount_diff",
        "left_qty",
        "right_qty",
        "qty_diff",
        "left_orders",
        "right_orders",
        "order_diff",
        "is_problem",
    ]
    return prepared[columns].copy()


def prepare_sku_reconciliation(
    frame: pd.DataFrame,
    *,
    batch_id: str,
    comparison_label: str,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    prepared = frame.copy()
    prepared["left_amount"] = prepared["net_sales_amount"]
    prepared["right_amount"] = prepared["cumulative_sales_amount"]
    prepared["left_qty"] = prepared["net_sales_qty"]
    prepared["right_qty"] = prepared["cumulative_sales_qty"]
    prepared["right_return_qty"] = prepared["cumulative_return_qty"]
    prepared["is_problem"] = (
        prepared["amount_diff"].abs().gt(0.01) | prepared["qty_diff"].abs().gt(0.01)
    ).astype(int)
    prepared["batch_id"] = batch_id
    prepared["comparison_label"] = comparison_label
    prepared["result_id"] = prepared.apply(
        lambda row: build_key(batch_id, comparison_label, row["sku"], row["color"]),
        axis=1,
    )
    columns = [
        "result_id",
        "batch_id",
        "comparison_label",
        "sku",
        "color",
        "left_amount",
        "right_amount",
        "amount_diff",
        "left_qty",
        "right_qty",
        "qty_diff",
        "right_return_qty",
        "is_problem",
    ]
    return prepared[columns].copy()


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)


def insert_batch_row(
    conn: sqlite3.Connection,
    *,
    batch_id: str,
    created_at: str,
    store_name: str,
    inferred_store_name: str,
    capture_dir: Path,
    notes: str,
) -> None:
    conn.execute(
        """
        INSERT INTO import_batches (
            batch_id, created_at, store_name, primary_input, inferred_store_name,
            capture_dir, input_dir, script_path, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            batch_id,
            created_at,
            store_name,
            PRIMARY_INPUT,
            inferred_store_name,
            str(capture_dir),
            "",
            str(Path(__file__).resolve()),
            notes,
        ),
    )


def run_build(
    *,
    store_name: str,
    capture_dir: Path,
    db_path: Path,
    batch_id: str,
    notes: str,
) -> dict[str, object]:
    master_lines, capture_sales_audit = load_capture_sales_master(capture_dir, store_name)
    retail_lines, capture_retail_audit = load_capture_store_retail_validation(
        capture_dir,
        store_name=store_name,
        input_user=PRIMARY_INPUT,
    )
    product_rows, capture_product_audit = load_capture_product_sales(capture_dir)
    flow_rows, capture_flow_audit = load_capture_daily_flow(capture_dir)
    movement_rows, capture_movement_audit = load_capture_movement(capture_dir)
    inventory_detail_rows, inventory_detail_sizes, capture_inventory_detail_audit = load_capture_inventory_detail(
        capture_dir,
        store_name,
    )
    inventory_sales_rows, inventory_sales_sizes, capture_inventory_sales_audit = load_capture_inventory_sales(
        capture_dir,
        store_name,
    )
    stock_flow_rows, capture_stock_flow_audit = load_capture_stock_flow(capture_dir)
    vip_analysis_rows, capture_vip_analysis_audit = load_capture_vip_analysis(capture_dir, store_name)
    member_rank_rows, capture_member_rank_audit = load_capture_member_rank(capture_dir, store_name)
    guide_report_rows, capture_guide_report_audit = load_capture_guide_report(capture_dir, store_name)
    retail_detail_rows, retail_detail_sizes, capture_retail_detail_audit = load_capture_retail_detail(
        capture_dir,
        store_name,
    )

    retail_comparison = compare_sales_overlap(master_lines, retail_lines, label="master_vs_store_retail")
    product_comparison = compare_master_to_product(master_lines, product_rows)
    flow_comparison = compare_master_to_flow(master_lines, flow_rows)
    daily_sales = build_daily_sales(master_lines, flow_rows)
    monthly_sales = build_monthly_sales(master_lines, flow_rows)
    sku_sales = build_sku_sales(master_lines)

    source_specs = [
        ("capture_sales_detail", "master", capture_sales_audit),
        ("capture_store_retail_validation", "validation", capture_retail_audit),
        ("capture_product_sales", "cumulative_validation", capture_product_audit),
        ("capture_daily_flow", "cash_validation", capture_flow_audit),
        ("capture_movement", "inventory_context", capture_movement_audit),
        ("capture_inventory_detail", "inventory_snapshot", capture_inventory_detail_audit),
        ("capture_inventory_sales", "inventory_sales_snapshot", capture_inventory_sales_audit),
        ("capture_stock_flow", "stock_flow_snapshot", capture_stock_flow_audit),
        ("capture_vip_analysis", "member_snapshot", capture_vip_analysis_audit),
        ("capture_member_rank", "member_rank", capture_member_rank_audit),
        ("capture_guide_report", "guide_snapshot", capture_guide_report_audit),
        ("capture_retail_detail", "retail_snapshot", capture_retail_detail_audit),
    ]
    source_file_rows = prepare_source_files_rows(batch_id, source_specs)

    sales_rows = pd.concat(
        [
            prepare_sales_order_lines(
                master_lines,
                batch_id=batch_id,
                source_name="capture_sales_detail",
                source_role="master",
                primary_store=store_name,
            ),
            prepare_sales_order_lines(
                retail_lines,
                batch_id=batch_id,
                source_name="capture_store_retail_validation",
                source_role="validation",
                primary_store=store_name,
            ),
        ],
        ignore_index=True,
    )

    flow_doc_rows = prepare_daily_flow_rows(flow_rows, batch_id=batch_id, store_name=store_name)
    product_snapshot_rows = prepare_product_sales_snapshot(product_rows, batch_id=batch_id, store_name=store_name)
    movement_doc_rows = prepare_movement_docs(movement_rows.assign(source_name="capture_movement"), batch_id=batch_id, store_name=store_name)
    inventory_detail_snapshot_rows = prepare_inventory_snapshot_rows(
        inventory_detail_rows,
        batch_id=batch_id,
        store_name=store_name,
        value_columns=[
            "sex_label",
            "total_stock_qty",
            "total_stock_amount",
            "total_retail_qty",
            "total_retail_amount",
        ],
    )
    inventory_sales_snapshot_rows = prepare_inventory_snapshot_rows(
        inventory_sales_rows,
        batch_id=batch_id,
        store_name=store_name,
        value_columns=[
            "stock_sale_ratio",
            "total_retail_qty",
            "total_retail_amount",
        ],
    )
    size_breakdown_rows = pd.concat(
        [
            prepare_size_breakdown_rows(
                inventory_detail_sizes,
                batch_id=batch_id,
                store_name=store_name,
            ),
            prepare_size_breakdown_rows(
                inventory_sales_sizes,
                batch_id=batch_id,
                store_name=store_name,
            ),
            prepare_size_breakdown_rows(
                retail_detail_sizes,
                batch_id=batch_id,
                store_name=store_name,
            ),
        ],
        ignore_index=True,
    )
    stock_flow_snapshot_rows = prepare_stock_flow_snapshot_rows(
        stock_flow_rows,
        batch_id=batch_id,
        store_name=store_name,
    )
    vip_analysis_member_rows = prepare_vip_analysis_rows(
        vip_analysis_rows,
        batch_id=batch_id,
        store_name=store_name,
    )
    member_rank_snapshot_rows = prepare_member_rank_rows(
        member_rank_rows,
        batch_id=batch_id,
        store_name=store_name,
    )
    guide_summary_rows = prepare_guide_report_rows(
        guide_report_rows,
        batch_id=batch_id,
        store_name=store_name,
    )
    retail_detail_snapshot_rows = prepare_retail_detail_rows(
        retail_detail_rows,
        batch_id=batch_id,
        store_name=store_name,
    )
    daily_summary_rows = prepare_period_summary(daily_sales, batch_id=batch_id, key_column="sale_date")
    monthly_summary_rows = prepare_period_summary(monthly_sales, batch_id=batch_id, key_column="month")
    sku_summary_rows = sku_sales.copy()
    if not sku_summary_rows.empty:
        sku_summary_rows.insert(0, "batch_id", batch_id)

    quality_check_rows = prepare_quality_checks(
        batch_id=batch_id,
        store_name=store_name,
        master_lines=master_lines,
        retail_comparison=retail_comparison,
        product_comparison=product_comparison,
        flow_comparison=flow_comparison,
        flow_rows=flow_rows,
        movement_rows=movement_rows,
    )

    order_recon_rows = pd.concat(
        [
            prepare_order_reconciliation(
                retail_comparison["order_comparison"],
                batch_id=batch_id,
                comparison_label="master_vs_store_retail",
                amount_columns=("amount_master", "amount_validation"),
                qty_columns=("qty_master", "qty_validation"),
                line_count_columns=("line_count_master", "line_count_validation"),
            ),
            prepare_order_reconciliation(
                flow_comparison["order_comparison"],
                batch_id=batch_id,
                comparison_label="master_vs_daily_flow",
                amount_columns=("master_amount", "flow_actual_money"),
                qty_columns=("master_qty", "flow_qty"),
                flow_doc_type_column="flow_doc_type",
            ),
        ],
        ignore_index=True,
    )

    daily_recon_rows = pd.concat(
        [
            prepare_daily_reconciliation(
                retail_comparison["daily_comparison"],
                batch_id=batch_id,
                comparison_label="master_vs_store_retail",
                amount_columns=("amount_master", "amount_validation"),
                qty_columns=("qty_master", "qty_validation"),
                order_columns=("orders_master", "orders_validation"),
            ),
            prepare_daily_reconciliation(
                flow_comparison["daily_comparison"],
                batch_id=batch_id,
                comparison_label="master_vs_daily_flow",
                amount_columns=("master_amount", "flow_actual_money"),
                flow_doc_type_column="flow_doc_type",
            ),
        ],
        ignore_index=True,
    )

    sku_recon_rows = prepare_sku_reconciliation(
        product_comparison["sku_comparison"],
        batch_id=batch_id,
        comparison_label="master_vs_product_sales",
    )

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        create_schema(conn)
        insert_batch_row(
            conn,
            batch_id=batch_id,
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            store_name=store_name,
            inferred_store_name=store_name,
            capture_dir=capture_dir,
            notes=notes,
        )
        append_frame(conn, "source_files", source_file_rows)
        append_frame(conn, "sales_order_lines", sales_rows)
        append_frame(conn, "daily_flow_docs", flow_doc_rows)
        append_frame(conn, "product_sales_snapshot", product_snapshot_rows)
        append_frame(conn, "movement_docs", movement_doc_rows)
        append_frame(conn, "inventory_detail_snapshots", inventory_detail_snapshot_rows)
        append_frame(conn, "inventory_sales_snapshots", inventory_sales_snapshot_rows)
        append_frame(conn, "stock_flow_snapshots", stock_flow_snapshot_rows)
        append_frame(conn, "size_metric_breakdowns", size_breakdown_rows)
        append_frame(conn, "vip_analysis_members", vip_analysis_member_rows)
        append_frame(conn, "member_sales_rank", member_rank_snapshot_rows)
        append_frame(conn, "guide_report_summary", guide_summary_rows)
        append_frame(conn, "retail_detail_snapshots", retail_detail_snapshot_rows)
        append_frame(conn, "daily_sales_summary", daily_summary_rows)
        append_frame(conn, "monthly_sales_summary", monthly_summary_rows)
        append_frame(conn, "sku_sales_summary", sku_summary_rows)
        append_frame(conn, "quality_checks", quality_check_rows)
        append_frame(conn, "order_reconciliation_results", order_recon_rows)
        append_frame(conn, "daily_reconciliation_results", daily_recon_rows)
        append_frame(conn, "sku_reconciliation_results", sku_recon_rows)
        conn.commit()
    finally:
        conn.close()

    return {
        "batch_id": batch_id,
        "db_path": str(db_path),
        "store_name": store_name,
        "master_row_count": len(master_lines),
        "validation_row_count": len(retail_lines),
        "daily_flow_row_count": len(flow_rows),
        "product_snapshot_row_count": len(product_rows),
        "movement_row_count": len(movement_rows),
        "inventory_detail_row_count": len(inventory_detail_rows),
        "inventory_sales_row_count": len(inventory_sales_rows),
        "stock_flow_row_count": len(stock_flow_rows),
        "size_breakdown_row_count": len(size_breakdown_rows),
        "vip_analysis_row_count": len(vip_analysis_rows),
        "member_rank_row_count": len(member_rank_rows),
        "guide_report_row_count": len(guide_report_rows),
        "retail_detail_row_count": len(retail_detail_rows),
        "daily_summary_row_count": len(daily_sales),
        "monthly_summary_row_count": len(monthly_sales),
        "sku_summary_row_count": len(sku_sales),
        "quality_check_count": len(quality_check_rows),
        "problem_order_count": int(
            len(retail_comparison["problem_orders"])
            + len(flow_comparison["problem_orders"])
        ),
        "problem_sku_count": int(sku_recon_rows["is_problem"].sum()) if not sku_recon_rows.empty else 0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-name", default=DEFAULT_STORE_NAME)
    parser.add_argument("--capture-dir", type=Path, default=DEFAULT_CAPTURE_DIR)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--batch-id", default=None)
    parser.add_argument("--notes", default="sales calibration import")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    batch_id = args.batch_id or make_batch_id()
    summary = run_build(
        store_name=args.store_name,
        capture_dir=args.capture_dir,
        db_path=args.db_path,
        batch_id=batch_id,
        notes=args.notes,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
