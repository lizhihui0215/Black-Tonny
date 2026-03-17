#!/usr/bin/env python3
"""Check whether the repo is ready to publish the dashboard via the site directory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
SITE_DIR = ROOT / "site"
DASHBOARD_DIR = SITE_DIR / "dashboard"
MANUALS_DIR = SITE_DIR / "manuals"


@dataclass
class CheckResult:
    label: str
    ok: bool
    detail: str


def file_exists(path: Path, label: str) -> CheckResult:
    return CheckResult(label, path.exists(), str(path))


def text_contains(path: Path, needle: str, label: str) -> CheckResult:
    if not path.exists():
        return CheckResult(label, False, f"missing file: {path}")
    text = path.read_text(encoding="utf-8")
    return CheckResult(label, needle in text, needle)


def main() -> int:
    results: list[CheckResult] = []

    results.extend(
        [
            file_exists(SITE_DIR / ".nojekyll", "site/.nojekyll exists"),
            file_exists(SITE_DIR / "index.html", "site/index.html exists"),
            file_exists(SITE_DIR / "costs" / "index.html", "site/costs/index.html exists"),
            file_exists(MANUALS_DIR / "index.html", "site/manuals/index.html exists"),
            file_exists(MANUALS_DIR / "28-月度成本快照维护说明.html", "site/manuals/28-月度成本快照维护说明.html exists"),
            file_exists(DASHBOARD_DIR / "index.html", "site/dashboard/index.html exists"),
            file_exists(DASHBOARD_DIR / "details.html", "site/dashboard/details.html exists"),
            file_exists(DASHBOARD_DIR / "monthly.html", "site/dashboard/monthly.html exists"),
            file_exists(DASHBOARD_DIR / "quarterly.html", "site/dashboard/quarterly.html exists"),
            file_exists(DASHBOARD_DIR / "relationship.html", "site/dashboard/relationship.html exists"),
            file_exists(DASHBOARD_DIR / "summary.md", "site/dashboard/summary.md exists"),
            file_exists(DASHBOARD_DIR / "report.md", "site/dashboard/report.md exists"),
            file_exists(DASHBOARD_DIR / "补货建议清单.csv", "site/dashboard/补货建议清单.csv exists"),
            file_exists(DASHBOARD_DIR / "去化建议清单.csv", "site/dashboard/去化建议清单.csv exists"),
            file_exists(DASHBOARD_DIR / "品类风险概览.csv", "site/dashboard/品类风险概览.csv exists"),
            file_exists(DASHBOARD_DIR / "data" / "dashboard.json", "site/dashboard/data/dashboard.json exists"),
            file_exists(DASHBOARD_DIR / "data" / "details.json", "site/dashboard/data/details.json exists"),
            file_exists(DASHBOARD_DIR / "data" / "monthly.json", "site/dashboard/data/monthly.json exists"),
            file_exists(DASHBOARD_DIR / "data" / "quarterly.json", "site/dashboard/data/quarterly.json exists"),
            file_exists(DASHBOARD_DIR / "data" / "relationship.json", "site/dashboard/data/relationship.json exists"),
            file_exists(DASHBOARD_DIR / "data" / "manifest.json", "site/dashboard/data/manifest.json exists"),
        ]
    )

    docs_index = SITE_DIR / "index.html"
    dashboard_index = DASHBOARD_DIR / "index.html"
    readme = ROOT / "README.md"

    results.extend(
        [
            text_contains(docs_index, "./dashboard/index.html", "Pages homepage links to dashboard"),
            text_contains(docs_index, "./dashboard/monthly.html", "Pages homepage links to monthly page"),
            text_contains(docs_index, "./dashboard/quarterly.html", "Pages homepage links to quarterly page"),
            text_contains(docs_index, "./manuals/index.html", "Pages homepage links to manuals center"),
            text_contains(docs_index, "./costs/index.html", "Pages homepage links to cost maintenance"),
            text_contains(docs_index, "./manuals/dashboard/summary.html", "Pages homepage links to summary html"),
            text_contains(docs_index, "./manuals/dashboard/report.html", "Pages homepage links to report html"),
            text_contains(readme, "site/index.html", "README links to Pages homepage"),
            text_contains(readme, "manuals", "README mentions manuals html docs"),
            text_contains(readme, "site/costs/index.html", "README links to cost maintenance"),
            text_contains(readme, "28-月度成本快照维护说明.md", "README links to monthly cost guide"),
            text_contains(readme, "site/dashboard/index.html", "README links to dashboard entry"),
            text_contains(dashboard_index, "./details.html", "dashboard links to detail page"),
            text_contains(dashboard_index, "./monthly.html", "dashboard links to monthly page"),
            text_contains(dashboard_index, "./quarterly.html", "dashboard links to quarterly page"),
            text_contains(dashboard_index, "./relationship.html", "dashboard links to relationship page"),
            text_contains(DASHBOARD_DIR / "relationship.html", "./details.html", "relationship page links to detail page"),
            text_contains(DASHBOARD_DIR / "relationship.html", "./monthly.html", "relationship page links to monthly page"),
            text_contains(DASHBOARD_DIR / "relationship.html", "./quarterly.html", "relationship page links to quarterly page"),
            text_contains(readme, "GitHub Pages开启清单", "README links to Pages checklist"),
        ]
    )

    dashboard_tokens = [
        "1. 今日经营重点",
        "2. 核心经营指标",
        "3. 赚钱机会",
        "4. 库存风险",
        "5. 补货机会",
        "6. 会员经营",
        "今日执行任务",
        "当前阶段：",
        "日销趋势：",
        "tooltip-badge",
    ]
    results.extend(
        text_contains(dashboard_index, token, f"dashboard contains {token}") for token in dashboard_tokens
    )

    passed = sum(1 for item in results if item.ok)
    total = len(results)

    print("Site readiness check")
    print(f"Passed {passed}/{total}")
    print("")
    for item in results:
        status = "PASS" if item.ok else "FAIL"
        print(f"[{status}] {item.label} :: {item.detail}")

    failed = [item for item in results if not item.ok]
    if failed:
        print("")
        print("Pages is not ready yet.")
        return 1

    print("")
    print("Site is ready. Next step: publish from the site directory.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
