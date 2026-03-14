#!/usr/bin/env python3
"""Build a working catalog for Yeusoft reports and known API families."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAPTURE_DIR = ROOT / "reports" / "yeusoft_report_capture"
OUTPUT_JSON = ROOT / "reports" / "yeusoft_report_capture" / "catalog.json"
OUTPUT_MD = ROOT / "reports" / "yeusoft_report_capture" / "catalog.md"


QUICK_REPORTS = [
    ("零售报表", "销售明细统计", "report01"),
    ("零售报表", "零售缴款单", "report02"),
    ("零售报表", "导购员统计", "report03"),
    ("零售报表", "门店销售日报", "report09"),
    ("库存报表", "库存明细统计", "report04"),
    ("库存报表", "库存零售统计", "report05"),
    ("库存报表", "库存综合分析", "report10"),
    ("进出报表", "进销存统计", "report06"),
    ("进出报表", "出入库单据", "report07"),
    ("会员报表", "会员综合分析", "report08"),
]

KNOWN_MENU_META = {
    "零售明细统计": {"func_lid": "E004001001", "func_url": "SaleList"},
    "店铺零售清单": {"func_lid": "E004001007", "func_url": "customReport_49"},
    "销售清单": {"func_lid": "E004001008", "func_url": "UnhiddenSaleList"},
    "库存明细统计": {"func_lid": "E004002001", "func_url": "StockList"},
    "库存零售统计": {"func_lid": "E004002002", "func_url": "StockSale"},
    "库存综合分析": {"func_lid": "E004002003", "func_url": "StockAnalysis"},
    "进销存统计": {"func_lid": "E004003001", "func_url": "InSaleReport"},
    "出入库单据": {"func_lid": "E004003002", "func_url": "InOutDoc"},
    "会员综合分析": {"func_lid": "E004004001", "func_url": "VipAnalysis"},
    "商品销售情况": {"func_lid": "E004005001", "func_url": "wareSalesStatus"},
    "商品品类分析": {"func_lid": "E004005002", "func_url": "wareCategoryReport"},
    "门店销售月报": {"func_lid": "E004005003", "func_url": "salesMonthlyReport"},
    "每日流水单": {"func_lid": "E004006001", "func_url": "dailyFlow"},
}


VALUE_LEVEL = {
    "店铺零售清单": "A",
    "销售清单": "A",
    "库存综合分析": "A",
    "出入库单据": "A",
    "商品销售情况": "A",
    "每日流水单": "A",
    "会员综合分析": "A",
    "会员消费排行": "A",
    "销售明细统计": "B",
    "库存明细统计": "B",
    "库存零售统计": "B",
    "进销存统计": "B",
    "商品品类分析": "B",
    "门店销售月报": "B",
    "导购员统计": "B",
    "零售缴款单": "C",
    "门店销售日报": "B",
}


def infer_api_family(capture: dict) -> str:
    requests = capture.get("requests", [])
    urls = [item.get("url", "") for item in requests]
    if any("GetDIYReportData" in url for url in urls):
        return "DIYReport"
    if any("SelectRetailDocPaymentSlip" in url for url in urls):
        return "Grid + JyApi"
    if any("SelStockAnalysisList" in url or "SelOutInStockReport" in url for url in urls):
        return "ReportAPI"
    if any("GetViewGridList" in url for url in urls):
        return "Grid"
    return "Unknown"


def extract_request_payload(capture: dict, keyword: str) -> dict | None:
    for item in capture.get("requests", []):
        if keyword in item.get("url", ""):
            data = item.get("postData")
            return data if isinstance(data, dict) else None
    return None


def extract_direct_api(capture: dict) -> str:
    if not capture:
        return ""
    ignored = {
        "GetMenuList",
        "GetViewGridList",
        "GetDIYReportData",
        "GetConfiguration",
        "GetControlData",
        "GetFilterContentData",
    }
    urls: list[str] = []
    for item in capture.get("requests", []):
        url = item.get("url", "")
        if not url:
            continue
        if any(keyword in url for keyword in ignored):
            continue
        urls.append(url)
    urls = list(dict.fromkeys(urls))
    return " | ".join(urls)


def load_capture_index() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in CAPTURE_DIR.glob("*.json"):
        if path.name in {"index.json", "catalog.json"}:
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        name = payload.get("reportName")
        if name:
            out[name] = payload
    return out


def build_catalog() -> list[dict]:
    captures = load_capture_index()
    catalog: list[dict] = []

    for group, title, internal_name in QUICK_REPORTS:
        capture = captures.get(title)
        grid = extract_request_payload(capture, "GetViewGridList") if capture else None
        diy = extract_request_payload(capture, "GetDIYReportData") if capture else None
        item = {
            "group": group,
            "report_name": title,
            "internal_name": internal_name,
            "api_family": infer_api_family(capture) if capture else "Pending",
            "menuid": (diy or grid or {}).get("menuid", "") or KNOWN_MENU_META.get(title, {}).get("func_lid", ""),
            "gridid": (diy or grid or {}).get("gridid", ""),
            "func_lid": KNOWN_MENU_META.get(title, {}).get("func_lid", ""),
            "func_url": KNOWN_MENU_META.get(title, {}).get("func_url", "") or (capture.get("tabState", {}).get("titleTabsValue", "") if capture else ""),
            "direct_api": extract_direct_api(capture),
            "value_level": VALUE_LEVEL.get(title, "Pending"),
            "capture_status": "captured" if capture else "pending",
        }
        catalog.append(item)

    extra_reports = [
        ("零售报表", "店铺零售清单", ""),
        ("零售报表", "销售清单", ""),
        ("综合分析", "商品销售情况", ""),
        ("会员报表", "会员消费排行", ""),
        ("对账报表", "每日流水单", ""),
        ("综合分析", "商品品类分析", ""),
        ("综合分析", "门店销售月报", ""),
    ]
    known_names = {item["report_name"] for item in catalog}
    for group, title, internal_name in extra_reports:
        if title in known_names:
            continue
        capture = captures.get(title)
        grid = extract_request_payload(capture, "GetViewGridList") if capture else None
        diy = extract_request_payload(capture, "GetDIYReportData") if capture else None
        item = {
            "group": group,
            "report_name": title,
            "internal_name": internal_name,
            "api_family": infer_api_family(capture) if capture else "Pending",
            "menuid": (diy or grid or {}).get("menuid", "") or KNOWN_MENU_META.get(title, {}).get("func_lid", ""),
            "gridid": (diy or grid or {}).get("gridid", ""),
            "func_lid": KNOWN_MENU_META.get(title, {}).get("func_lid", ""),
            "func_url": KNOWN_MENU_META.get(title, {}).get("func_url", "") or (capture.get("tabState", {}).get("titleTabsValue", "") if capture else ""),
            "direct_api": extract_direct_api(capture),
            "value_level": VALUE_LEVEL.get(title, "Pending"),
            "capture_status": "captured" if capture else "pending",
        }
        catalog.append(item)

    return catalog


def write_markdown(catalog: list[dict]) -> str:
    lines = [
        "# Yeusoft 报表目录与 API 家族",
        "",
        "这份目录汇总当前已经识别到的报表分组、内部名、接口族和经营价值。",
        "",
        "| 分组 | 报表 | 内部名 | API 家族 | menuid | gridid | FuncLID | FuncUrl | 直连数据 API | 价值级别 | 状态 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in catalog:
        lines.append(
            f"| {item['group']} | {item['report_name']} | {item['internal_name'] or '-'} | {item['api_family']} | "
            f"{item['menuid'] or '-'} | {item['gridid'] or '-'} | {item['func_lid'] or '-'} | {item['func_url'] or '-'} | "
            f"{item['direct_api'] or '-'} | {item['value_level']} | {item['capture_status']} |"
        )
    lines.extend(
        [
            "",
            "## 当前结论",
            "",
            "- `GetMenuList` 已能稳定拿到报表的 `FuncLID / FuncUrl / FuncName`，后续不必再依赖左侧浮层菜单点击。",
            "- `库存综合分析` 已确认可以直接走 `SelStockAnalysisList`。",
            "- `出入库单据` 已确认可以直接走 `SelOutInStockReport`。",
            "- `每日流水单` 已确认可以直接走 `SelectRetailDocPaymentSlip`。",
            "- `店铺零售清单` 已确认属于 `DIYReport` 家族，`销售清单` 已确认属于 `Grid` 家族。",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    catalog = build_catalog()
    OUTPUT_JSON.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    OUTPUT_MD.write_text(write_markdown(catalog), encoding="utf-8")
    print(f"Wrote catalog json: {OUTPUT_JSON}")
    print(f"Wrote catalog md: {OUTPUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
