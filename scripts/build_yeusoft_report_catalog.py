#!/usr/bin/env python3
"""Build a Yeusoft report catalog from captured menu metadata and report samples."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAPTURE_DIR = ROOT / "reports" / "yeusoft_report_capture"
OUTPUT_JSON = CAPTURE_DIR / "catalog.json"
OUTPUT_MD = CAPTURE_DIR / "catalog.md"
REPORT_ROOT_LID = "E004"

VALUE_LEVEL = {
    "店铺零售清单": "A",
    "销售清单": "A",
    "库存综合分析": "A",
    "出入库单据": "A",
    "商品销售情况": "A",
    "每日流水单": "A",
    "会员综合分析": "A",
    "会员消费排行": "A",
    "零售明细统计": "B",
    "导购员报表": "B",
    "库存明细统计": "B",
    "库存零售统计": "B",
    "库存多维分析": "B",
    "进销存统计": "B",
    "日进销存": "B",
    "退货明细": "B",
    "商品品类分析": "B",
    "门店销售月报": "B",
    "储值按店汇总": "C",
    "储值卡汇总": "C",
    "储值卡明细": "C",
}


def extract_menu_tree() -> list[dict]:
    for path in sorted(CAPTURE_DIR.glob("*.json")):
        if path.name in {"index.json", "catalog.json"}:
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for response in payload.get("responses", []):
            if "GetMenuList" in str(response.get("url", "")):
                body = response.get("body", {})
                retdata = body.get("retdata")
                if isinstance(retdata, list):
                    return retdata
    return []


def flatten_reports(menu_tree: list[dict], parents: list[str] | None = None) -> list[dict]:
    parents = parents or []
    rows: list[dict] = []
    for item in menu_tree or []:
        current_parents = [*parents, item.get("FuncName", "")]
        sublist = item.get("SubList") or []
        if sublist:
            rows.extend(flatten_reports(sublist, current_parents))
            continue
        func_lid = str(item.get("FuncLID") or "")
        func_url = str(item.get("FuncUrl") or "")
        if not (func_lid.startswith(REPORT_ROOT_LID) and func_url):
            continue
        rows.append(
            {
                "group": parents[-1] if parents else "",
                "report_name": item.get("FuncName", ""),
                "func_lid": func_lid,
                "func_url": func_url,
                "func_type": item.get("FuncType", ""),
            }
        )
    return rows


def infer_api_family(capture: dict | None) -> str:
    requests = capture.get("requests", []) if capture else []
    urls = [str(item.get("url", "")) for item in requests]
    if any("GetDIYReportData" in url for url in urls):
        return "DIYReport"
    if any("SelectRetailDocPaymentSlip" in url for url in urls):
        return "JyApi"
    if any("SelStockAnalysisList" in url for url in urls):
        return "ReportAPI: SelStockAnalysisList"
    if any("SelOutInStockReport" in url for url in urls):
        return "ReportAPI: SelOutInStockReport"
    if any("GetViewGridList" in url for url in urls):
        return "Grid"
    return "Pending"


def extract_direct_api(capture: dict | None) -> str:
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
        url = str(item.get("url", ""))
        if not url or any(keyword in url for keyword in ignored):
            continue
        urls.append(url)
    return " | ".join(dict.fromkeys(urls))


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
    menu_reports = flatten_reports(extract_menu_tree())
    catalog: list[dict] = []

    for item in menu_reports:
        capture = captures.get(item["report_name"])
        capture_summary = capture.get("captureSummary", {}) if capture else {}
        catalog.append(
            {
                "group": item["group"],
                "report_name": item["report_name"],
                "func_lid": item["func_lid"],
                "func_url": item["func_url"],
                "func_type": item["func_type"],
                "api_family": infer_api_family(capture),
                "direct_api": extract_direct_api(capture),
                "value_level": VALUE_LEVEL.get(item["report_name"], "Pending"),
                "capture_status": capture_summary.get("captureQuality", "pending"),
                "record_count": capture_summary.get("recordCount", 0),
                "report_mode": capture_summary.get("reportMode", ""),
            }
        )

    return catalog


def write_markdown(catalog: list[dict]) -> str:
    lines = [
        "# Yeusoft 报表目录与 API 家族",
        "",
        "这份目录直接根据抓取样本里的 `GetMenuList` 结果生成，避免遗漏实际菜单里的报表。",
        "",
        "| 分组 | 报表 | FuncLID | FuncUrl | FuncType | API 家族 | 直连数据 API | 价值级别 | 抓取状态 | 记录数 | 模式 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in catalog:
        lines.append(
            f"| {item['group']} | {item['report_name']} | {item['func_lid'] or '-'} | {item['func_url'] or '-'} | "
            f"{item['func_type'] or '-'} | {item['api_family']} | {item['direct_api'] or '-'} | {item['value_level']} | "
            f"{item['capture_status']} | {item['record_count']} | {item['report_mode'] or '-'} |"
        )
    lines.extend(
        [
            "",
            "## 当前结论",
            "",
            "- 目录已经和真实 POS 菜单对齐，后续可以据此判断“哪些表值得继续接入老板看板”。",
            "- `capture_status` 现在直接使用抓取质量，而不是简单的 `captured/pending`。",
            "- `record_count` 和 `report_mode` 能帮助判断这张表是“全量区间”还是“快照类”。",
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
