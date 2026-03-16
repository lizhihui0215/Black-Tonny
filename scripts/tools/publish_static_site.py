#!/usr/bin/env python3
"""Run the local JSON -> SQLite -> analysis -> static Pages publish pipeline."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.tools.local_dashboard_service import (  # noqa: E402
    COST_FILE,
    COST_HISTORY_FILE,
    DEFAULT_SYNC_MODE,
    DEFAULT_SYNC_START_DATE,
    SCAN_OUTPUT,
    load_local_config,
)


BEIJING_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_ANALYSIS_DB_FILE = ROOT / "reports" / "calibration" / "black_tony_analysis.sqlite"
DEFAULT_OUTPUT_DIR = ROOT / "reports" / "dashboard-history"
DEFAULT_PAGES_DIR = ROOT / "site" / "dashboard"
REPORT_DIR = ROOT / "reports" / "dashboard-history"


@dataclass
class StepResult:
    name: str
    status: str
    detail: str
    command: list[str] | None = None


def now_dt() -> datetime:
    return datetime.now(BEIJING_TZ)


def run_command(cmd: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def load_scan_index() -> dict:
    index_path = SCAN_OUTPUT / "index.json"
    if not index_path.exists():
        return {}
    return json.loads(index_path.read_text(encoding="utf-8"))


def build_env(
    *,
    sync_mode: str,
    start_date: str | None,
    end_date: str | None,
) -> dict[str, str]:
    config = load_local_config()
    sync_start = str(start_date or config.get("start_date") or DEFAULT_SYNC_START_DATE)
    sync_end = str(end_date or config.get("end_date") or now_dt().strftime("%Y-%m-%d"))
    return {
        **os.environ,
        "YEU_SITE_URL": str(config.get("site_url") or "https://jypos.yeusoft.net/"),
        "YEU_USERNAME": str(config.get("username") or ""),
        "YEU_PASSWORD": str(config.get("password") or ""),
        "YEU_START_DATE": sync_start,
        "YEU_END_DATE": sync_end,
        "YEU_SYNC_MODE": sync_mode,
    }


def require_local_credentials(env: dict[str, str]) -> None:
    if not env.get("YEU_USERNAME") or not env.get("YEU_PASSWORD"):
        raise RuntimeError(
            "缺少 Yeusoft 登录配置。请先填写 "
            "data/local/yeusoft_local_config.json，再执行静态发布。"
        )


def write_publish_report(summary: dict[str, object], *, stamp: str) -> tuple[Path, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_json_path = REPORT_DIR / f"静态发布报告_{stamp}.json"
    report_md_path = REPORT_DIR / f"静态发布报告_{stamp}.md"
    latest_json_path = REPORT_DIR / "静态发布报告_latest.json"
    latest_md_path = REPORT_DIR / "静态发布报告_latest.md"

    report_json = json.dumps(summary, ensure_ascii=False, indent=2)
    report_json_path.write_text(report_json, encoding="utf-8")
    latest_json_path.write_text(report_json, encoding="utf-8")

    lines = [
        "# 静态发布报告",
        "",
        f"- 生成时间：{summary['generated_at']}",
        f"- 发布模式：{summary['mode_label']}",
        f"- 同步窗口：{summary['sync_window']}",
        f"- SQLite：{summary['analysis_db_file']}",
        f"- 静态站点目录：{summary['pages_dir']}",
        f"- 历史输出目录：{summary['output_dir']}",
        f"- 结果：{summary['overall_status']}",
        "",
        "## 步骤结果",
        "",
    ]
    for step in summary["steps"]:
        lines.append(f"- {step['name']}：{step['status']}，{step['detail']}")

    if summary.get("scan_counts"):
        lines.extend(["", "## 抓取摘要", ""])
        for key, value in summary["scan_counts"].items():
            lines.append(f"- {key}：{value}")

    if summary.get("analysis_summary"):
        lines.extend(["", "## SQLite 同步摘要", ""])
        for key, value in summary["analysis_summary"].items():
            lines.append(f"- {key}：{value}")

    if summary.get("field_audit_summary"):
        lines.extend(["", "## 字段核对摘要", ""])
        field_audit_summary = summary["field_audit_summary"]
        for key, value in field_audit_summary.items():
            lines.append(f"- {key}：{value}")

    lines.extend(
        [
            "",
            "## 发布产物",
            "",
            f"- Pages 首页：[index.html]({summary['pages_dashboard_html']})",
            f"- Pages JSON 清单：[manifest.json]({summary['pages_manifest_json']})",
            f"- Pages 数据包目录：[data]({summary['pages_data_dir']})",
            f"- 字段核对 Markdown：[api_field_audit.md]({summary['field_audit_markdown']})",
            f"- 字段核对 JSON：[api_field_audit.json]({summary['field_audit_json']})",
            f"- 自检脚本：[check_pages_ready.py]({summary['check_script']})",
        ]
    )
    report_md = "\n".join(lines) + "\n"
    report_md_path.write_text(report_md, encoding="utf-8")
    latest_md_path.write_text(report_md, encoding="utf-8")
    return latest_md_path, latest_json_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-sync", action="store_true", help="Skip Yeusoft capture refresh and reuse current capture-cache.")
    parser.add_argument("--skip-docs", action="store_true", help="Skip rebuilding the manuals site.")
    parser.add_argument("--skip-check", action="store_true", help="Skip final Pages readiness check.")
    parser.add_argument("--sync-mode", default=DEFAULT_SYNC_MODE, help="Yeusoft sync mode passed to the capture script.")
    parser.add_argument("--start-date", default=None, help="Optional capture start date in YYYY-MM-DD.")
    parser.add_argument("--end-date", default=None, help="Optional capture end date in YYYY-MM-DD.")
    parser.add_argument("--analysis-db-file", type=Path, default=DEFAULT_ANALYSIS_DB_FILE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--pages-dir", type=Path, default=DEFAULT_PAGES_DIR)
    parser.add_argument("--notes", default="static publish pipeline")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    env = build_env(sync_mode=args.sync_mode, start_date=args.start_date, end_date=args.end_date)
    stamp = now_dt().strftime("%Y%m%d_%H%M%S")
    steps: list[StepResult] = []
    scan_counts: dict[str, object] = {}
    analysis_summary: dict[str, object] = {}
    field_audit_summary: dict[str, object] = {}

    try:
        if args.skip_sync:
            steps.append(
                StepResult(
                    name="抓取 JSON",
                    status="skipped",
                    detail="已跳过抓取，沿用当前 reports/capture-cache。",
                )
            )
        else:
            require_local_credentials(env)
            scan_cmd = ["node", "scripts/yeusoft/scan.mjs"]
            scan = run_command(scan_cmd, env=env)
            if scan.returncode != 0:
                raise RuntimeError(scan.stderr.strip() or scan.stdout.strip() or "Yeusoft 抓取失败。")
            scan_index = load_scan_index()
            counts = scan_index.get("counts", {}) if isinstance(scan_index, dict) else {}
            scan_counts = {
                "total_reports": int(scan_index.get("totalReports") or 0) if isinstance(scan_index, dict) else 0,
                "ok": int(counts.get("ok") or 0),
                "partial": int(counts.get("partial") or 0),
                "warning": int(counts.get("warning") or 0),
                "opened_only": int(counts.get("opened-only") or 0),
                "error": int(counts.get("error") or 0),
            }
            steps.append(
                StepResult(
                    name="抓取 JSON",
                    status="ok" if scan_counts.get("error", 0) == 0 else "warning",
                    detail=(
                        f"成功 {scan_counts.get('ok', 0)} 张，部分成功 {scan_counts.get('partial', 0)} 张，"
                        f"warning {scan_counts.get('warning', 0)} 张，失败 {scan_counts.get('error', 0)} 张。"
                    ),
                    command=scan_cmd,
                )
            )

        field_audit_cmd = ["python3", "-m", "scripts.yeusoft.build_field_audit"]
        field_audit = run_command(field_audit_cmd, env=env)
        if field_audit.returncode != 0:
            raise RuntimeError(field_audit.stderr.strip() or field_audit.stdout.strip() or "字段核对产物生成失败。")
        field_audit_summary = json.loads(field_audit.stdout)
        field_audit_status = "warning" if field_audit_summary.get("high_suspicion_count", 0) else "ok"
        steps.append(
            StepResult(
                name="截图字段核对",
                status=field_audit_status,
                detail=(
                    f"已经 {field_audit_summary.get('confirmed_count', 0)} 张，"
                    f"高度怀疑 {field_audit_summary.get('high_suspicion_count', 0)} 张。"
                ),
                command=field_audit_cmd,
            )
        )

        build_db_cmd = [
            "python3",
            "-m",
            "scripts.tools.build_analysis_db",
            "--db-path",
            str(args.analysis_db_file),
            "--notes",
            args.notes,
        ]
        build_db = run_command(build_db_cmd, env=env)
        if build_db.returncode != 0:
            raise RuntimeError(build_db.stderr.strip() or build_db.stdout.strip() or "SQLite 同步失败。")
        analysis_summary = json.loads(build_db.stdout)
        steps.append(
            StepResult(
                name="数据同步 -> SQLite",
                status="ok",
                detail=(
                    f"批次 {analysis_summary.get('batch_id')}，销售 {analysis_summary.get('master_row_count')} 行，"
                    f"库存 {analysis_summary.get('inventory_detail_row_count')} 行。"
                ),
                command=build_db_cmd,
            )
        )

        dashboard_cmd = [
            "python3",
            "-m",
            "scripts.dashboard.main",
            "--cost-file",
            str(COST_FILE),
            "--cost-history-file",
            str(COST_HISTORY_FILE),
            "--analysis-db-file",
            str(args.analysis_db_file),
            "--output-dir",
            str(args.output_dir),
            "--pages-dir",
            str(args.pages_dir),
        ]
        dashboard = run_command(dashboard_cmd, env=env)
        if dashboard.returncode != 0:
            raise RuntimeError(dashboard.stderr.strip() or dashboard.stdout.strip() or "静态看板导出失败。")
        steps.append(
            StepResult(
                name="SQLite -> 本地分析 -> 导出 Pages",
                status="ok",
                detail="已生成 HTML / Markdown / CSV / JSON 到 reports/ 和 site/。",
                command=dashboard_cmd,
            )
        )

        if args.skip_docs:
            steps.append(
                StepResult(
                    name="文档中心构建",
                    status="skipped",
                    detail="已跳过 manuals 站点重建。",
                )
            )
        else:
            docs_cmd = ["python3", "-m", "scripts.docs_site.build"]
            docs = run_command(docs_cmd, env=env)
            if docs.returncode != 0:
                raise RuntimeError(docs.stderr.strip() or docs.stdout.strip() or "文档中心构建失败。")
            steps.append(
                StepResult(
                    name="文档中心构建",
                    status="ok",
                    detail="已刷新 site/manuals。",
                    command=docs_cmd,
                )
            )

        if args.skip_check:
            steps.append(
                StepResult(
                    name="Pages 自检",
                    status="skipped",
                    detail="已跳过最终自检。",
                )
            )
            check_status = "skipped"
        else:
            check_cmd = ["python3", "-m", "scripts.tools.check_pages_ready"]
            check = run_command(check_cmd, env=env)
            if check.returncode != 0:
                raise RuntimeError(check.stdout.strip() or check.stderr.strip() or "Pages 自检失败。")
            steps.append(
                StepResult(
                    name="Pages 自检",
                    status="ok",
                    detail="site/ 静态发布目录检查通过。",
                    command=check_cmd,
                )
            )
            check_status = "ok"

        overall_status = "ok"
        summary = {
            "generated_at": now_dt().isoformat(),
            "overall_status": overall_status,
            "mode_label": "复用本地抓取缓存" if args.skip_sync else "全量静态发布",
            "sync_window": f"{env['YEU_START_DATE']} -> {env['YEU_END_DATE']}",
            "analysis_db_file": str(args.analysis_db_file.resolve()),
            "output_dir": str(args.output_dir.resolve()),
            "pages_dir": str(args.pages_dir.resolve()),
            "pages_data_dir": str((args.pages_dir / 'data').resolve()),
            "pages_dashboard_html": str((args.pages_dir / "index.html").resolve()),
            "pages_manifest_json": str((args.pages_dir / "data" / "manifest.json").resolve()),
            "check_script": str((ROOT / "scripts" / "tools" / "check_pages_ready.py").resolve()),
            "scan_counts": scan_counts,
            "field_audit_summary": field_audit_summary,
            "field_audit_markdown": field_audit_summary.get(
                "audit_markdown",
                str((ROOT / "reports" / "calibration" / "api_field_audit.md").resolve()),
            ),
            "field_audit_json": field_audit_summary.get(
                "audit_json",
                str((ROOT / "reports" / "calibration" / "api_field_audit.json").resolve()),
            ),
            "analysis_summary": analysis_summary,
            "check_status": check_status,
            "steps": [
                {
                    "name": step.name,
                    "status": step.status,
                    "detail": step.detail,
                    "command": step.command,
                }
                for step in steps
            ],
        }
        report_md_path, report_json_path = write_publish_report(summary, stamp=stamp)
        print(json.dumps({**summary, "report_markdown": str(report_md_path), "report_json": str(report_json_path)}, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:  # noqa: BLE001
        steps.append(StepResult(name="执行失败", status="error", detail=str(error)))
        summary = {
            "generated_at": now_dt().isoformat(),
            "overall_status": "error",
            "mode_label": "复用本地抓取缓存" if args.skip_sync else "全量静态发布",
            "sync_window": f"{env['YEU_START_DATE']} -> {env['YEU_END_DATE']}",
            "analysis_db_file": str(args.analysis_db_file.resolve()),
            "output_dir": str(args.output_dir.resolve()),
            "pages_dir": str(args.pages_dir.resolve()),
            "pages_data_dir": str((args.pages_dir / 'data').resolve()),
            "pages_dashboard_html": str((args.pages_dir / "index.html").resolve()),
            "pages_manifest_json": str((args.pages_dir / "data" / "manifest.json").resolve()),
            "check_script": str((ROOT / "scripts" / "tools" / "check_pages_ready.py").resolve()),
            "scan_counts": scan_counts,
            "field_audit_summary": field_audit_summary,
            "field_audit_markdown": field_audit_summary.get(
                "audit_markdown",
                str((ROOT / "reports" / "calibration" / "api_field_audit.md").resolve()),
            ),
            "field_audit_json": field_audit_summary.get(
                "audit_json",
                str((ROOT / "reports" / "calibration" / "api_field_audit.json").resolve()),
            ),
            "analysis_summary": analysis_summary,
            "check_status": "error",
            "steps": [
                {
                    "name": step.name,
                    "status": step.status,
                    "detail": step.detail,
                    "command": step.command,
                }
                for step in steps
            ],
        }
        report_md_path, report_json_path = write_publish_report(summary, stamp=stamp)
        print(
            json.dumps(
                {**summary, "report_markdown": str(report_md_path), "report_json": str(report_json_path)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
