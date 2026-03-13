#!/usr/bin/env python3
"""Check whether the repo is ready to publish the dashboard via GitHub Pages."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs"
DASHBOARD_DIR = DOCS_DIR / "dashboard"


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
            file_exists(DOCS_DIR / ".nojekyll", "docs/.nojekyll exists"),
            file_exists(DOCS_DIR / "index.html", "docs/index.html exists"),
            file_exists(DASHBOARD_DIR / "index.html", "docs/dashboard/index.html exists"),
            file_exists(DASHBOARD_DIR / "summary.md", "docs/dashboard/summary.md exists"),
            file_exists(DASHBOARD_DIR / "report.md", "docs/dashboard/report.md exists"),
            file_exists(DASHBOARD_DIR / "补货建议清单.csv", "docs/dashboard/补货建议清单.csv exists"),
            file_exists(DASHBOARD_DIR / "去化建议清单.csv", "docs/dashboard/去化建议清单.csv exists"),
            file_exists(DASHBOARD_DIR / "品类风险概览.csv", "docs/dashboard/品类风险概览.csv exists"),
        ]
    )

    docs_index = DOCS_DIR / "index.html"
    dashboard_index = DASHBOARD_DIR / "index.html"
    readme = ROOT / "README.md"

    results.extend(
        [
            text_contains(docs_index, "./dashboard/", "Pages homepage links to dashboard"),
            text_contains(docs_index, "./dashboard/summary.md", "Pages homepage links to summary"),
            text_contains(docs_index, "./dashboard/report.md", "Pages homepage links to report"),
            text_contains(readme, "docs/index.html", "README links to Pages homepage"),
            text_contains(readme, "docs/dashboard/index.html", "README links to dashboard entry"),
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

    print("GitHub Pages readiness check")
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
    print("Pages is ready. Next step: enable GitHub Pages with main + /docs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
