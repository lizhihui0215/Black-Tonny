#!/usr/bin/env python3
"""Local service for refreshing Yeusoft report scans and rebuilding the dashboard."""

from __future__ import annotations

import json
import os
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
BEIJING_TZ = ZoneInfo("Asia/Shanghai")
HOST = "127.0.0.1"
PORT = 8765
CONFIG_FILE = ROOT / "data" / "local" / "yeusoft_local_config.json"
COST_FILE = ROOT / "data" / "local" / "store_cost_snapshot.json"
COST_HISTORY_FILE = ROOT / "data" / "local" / "store_cost_history.json"
SCAN_OUTPUT = ROOT / "reports" / "capture-cache"
DEFAULT_SYNC_MODE = "full"
DEFAULT_SYNC_START_DATE = "2025-03-01"


def now_text() -> str:
    return datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")


def load_local_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        return {}
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def load_cost_snapshot() -> dict[str, Any]:
    if not COST_FILE.exists():
        return {}
    return json.loads(COST_FILE.read_text(encoding="utf-8"))


def save_cost_snapshot(snapshot: dict[str, Any]) -> None:
    COST_FILE.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")


def load_cost_history() -> list[dict[str, Any]]:
    if not COST_HISTORY_FILE.exists():
        return []
    payload = json.loads(COST_HISTORY_FILE.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        snapshots = payload.get("snapshots")
        if isinstance(snapshots, list):
            return [item for item in snapshots if isinstance(item, dict)]
    return []


def save_cost_history(history: list[dict[str, Any]]) -> None:
    COST_HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def snapshot_period_key(snapshot: dict[str, Any]) -> str:
    snapshot_datetime = str(snapshot.get("snapshot_datetime") or "").strip()
    if len(snapshot_datetime) >= 7:
        return snapshot_datetime[:7]
    return str(snapshot.get("snapshot_name") or "未标记月份").strip()


def upsert_cost_history(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    history = load_cost_history()
    period_key = snapshot_period_key(snapshot)
    updated = False

    for index, item in enumerate(history):
        if snapshot_period_key(item) == period_key:
            history[index] = snapshot
            updated = True
            break

    if not updated:
        history.append(snapshot)

    history.sort(key=lambda item: str(item.get("snapshot_datetime") or ""), reverse=True)
    save_cost_history(history)
    return history


@dataclass
class JobState:
    running: bool = False
    started_at: str | None = None
    finished_at: str | None = None
    status: str = "idle"
    message: str = "本地抓取服务已启动，等待执行。"
    steps: list[dict[str, str]] = field(default_factory=list)
    last_scan_index: str | None = None
    last_dashboard: str | None = None
    last_source: str | None = None
    last_success_at: str | None = None
    last_error_at: str | None = None
    last_error: str | None = None
    run_count: int = 0
    sync_mode: str = DEFAULT_SYNC_MODE
    sync_start_date: str = DEFAULT_SYNC_START_DATE
    sync_end_date: str = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")
    total_reports: int = 0
    ok_reports: int = 0
    partial_reports: int = 0
    warning_reports: int = 0
    opened_only_reports: int = 0
    error_reports: int = 0


STATE = JobState()
STATE_LOCK = threading.Lock()


def update_state(**kwargs: Any) -> None:
    with STATE_LOCK:
        for key, value in kwargs.items():
            setattr(STATE, key, value)


def snapshot_state() -> dict[str, Any]:
    with STATE_LOCK:
        return {
            "running": STATE.running,
            "started_at": STATE.started_at,
            "finished_at": STATE.finished_at,
            "status": STATE.status,
            "message": STATE.message,
            "steps": list(STATE.steps),
            "last_scan_index": STATE.last_scan_index,
            "last_dashboard": STATE.last_dashboard,
            "last_source": STATE.last_source,
            "last_success_at": STATE.last_success_at,
            "last_error_at": STATE.last_error_at,
            "last_error": STATE.last_error,
            "run_count": STATE.run_count,
            "sync_mode": STATE.sync_mode,
            "sync_start_date": STATE.sync_start_date,
            "sync_end_date": STATE.sync_end_date,
            "total_reports": STATE.total_reports,
            "ok_reports": STATE.ok_reports,
            "partial_reports": STATE.partial_reports,
            "warning_reports": STATE.warning_reports,
            "opened_only_reports": STATE.opened_only_reports,
            "error_reports": STATE.error_reports,
        }


def append_step(title: str, status: str, detail: str) -> None:
    with STATE_LOCK:
        STATE.steps.append({"title": title, "status": status, "detail": detail})


def run_command(cmd: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def load_scan_index() -> dict[str, Any]:
    index_path = SCAN_OUTPUT / "index.json"
    if not index_path.exists():
        return {}
    return json.loads(index_path.read_text(encoding="utf-8"))


def refresh_job(source: str = "unknown", mode: str = DEFAULT_SYNC_MODE, start_date: str | None = None, end_date: str | None = None) -> None:
    config = load_local_config()
    sync_start_date = str(start_date or config.get("start_date") or DEFAULT_SYNC_START_DATE)
    sync_end_date = str(end_date or config.get("end_date") or datetime.now(BEIJING_TZ).strftime("%Y-%m-%d"))
    env = {
        **os.environ,
        "YEU_SITE_URL": str(config.get("site_url") or "https://jypos.yeusoft.net/"),
        "YEU_USERNAME": str(config.get("username") or ""),
        "YEU_PASSWORD": str(config.get("password") or ""),
        "YEU_START_DATE": sync_start_date,
        "YEU_END_DATE": sync_end_date,
        "YEU_SYNC_MODE": mode,
    }

    update_state(
        running=True,
        started_at=now_text(),
        finished_at=None,
        status="running",
        message="正在执行 Yeusoft 全量同步并重建仪表盘。",
        steps=[],
        last_source=source,
        sync_mode=mode,
        sync_start_date=sync_start_date,
        sync_end_date=sync_end_date,
        total_reports=0,
        ok_reports=0,
        partial_reports=0,
        warning_reports=0,
        opened_only_reports=0,
        error_reports=0,
    )

    try:
        append_step("读取本地配置", "ok", "已读取本地 Yeusoft 登录配置和成本快照。")

        if not env["YEU_USERNAME"] or not env["YEU_PASSWORD"]:
            raise RuntimeError("缺少 Yeusoft 用户名或密码，请先填写 data/local/yeusoft_local_config.json。")

        scan = run_command(["node", "scripts/yeusoft/scan.mjs"], env=env)
        if scan.returncode != 0:
            raise RuntimeError(f"关键报表扫描失败：{scan.stderr.strip() or scan.stdout.strip()}")
        scan_index = load_scan_index()
        counts = scan_index.get("counts", {}) if isinstance(scan_index, dict) else {}
        update_state(
            total_reports=int(scan_index.get("totalReports") or 0) if isinstance(scan_index, dict) else 0,
            ok_reports=int(counts.get("ok") or 0),
            partial_reports=int(counts.get("partial") or 0),
            warning_reports=int(counts.get("warning") or 0),
            opened_only_reports=int(counts.get("opened-only") or 0),
            error_reports=int(counts.get("error") or 0),
        )
        warning_count = int(counts.get("warning") or 0)
        error_count = int(counts.get("error") or 0)
        append_step(
            "执行全量同步",
            "warning" if warning_count or error_count else "ok",
            (
                f"已按 {sync_start_date} 到 {sync_end_date} 运行全量同步。"
                f" 成功 {counts.get('ok', 0)} 张，部分成功 {counts.get('partial', 0)} 张，"
                f"沿用上次成功数据 {warning_count} 张，仅打开未取数 {counts.get('opened-only', 0)} 张，"
                f"失败 {error_count} 张。"
            ),
        )

        build_cmd = [
            "python3",
            "-m",
            "scripts.dashboard.main",
            "--cost-file",
            str(COST_FILE),
            "--cost-history-file",
            str(COST_HISTORY_FILE),
        ]
        build = run_command(build_cmd, env=env)
        if build.returncode != 0:
            raise RuntimeError(f"看板重建失败：{build.stderr.strip() or build.stdout.strip()}")
        append_step("重建经营仪表盘", "ok", "已使用最新本地数据和成本快照重建仪表盘。")

        manuals = run_command(["python3", "-m", "scripts.docs_site.build"], env=env)
        if manuals.returncode != 0:
            raise RuntimeError(f"文档中心重建失败：{manuals.stderr.strip() or manuals.stdout.strip()}")
        append_step("重建文档中心", "ok", "已同步更新摘要、报告和网页版手册。")

        last_scan_index = str((SCAN_OUTPUT / "index.json").resolve()) if (SCAN_OUTPUT / "index.json").exists() else None
        last_dashboard = str((ROOT / "site" / "dashboard" / "index.html").resolve())
        update_state(
            running=False,
            finished_at=now_text(),
            status="warning" if warning_count or error_count else "success",
            message=(
                "全量同步和重建已完成，部分报表沿用了上次成功数据。"
                if warning_count and not error_count
                else "全量同步和重建已完成，但仍有少量报表未成功。"
                if error_count
                else "全量同步和重建已完成，可以刷新首页和仪表盘查看最新结果。"
            ),
            last_scan_index=last_scan_index,
            last_dashboard=last_dashboard,
            last_success_at=now_text(),
            last_error=None,
            run_count=STATE.run_count + 1,
        )
    except Exception as error:  # noqa: BLE001
        append_step("执行失败", "error", str(error))
        update_state(
            running=False,
            finished_at=now_text(),
            status="error",
            message=str(error),
            last_error=str(error),
            last_error_at=now_text(),
            run_count=STATE.run_count + 1,
        )


class Handler(BaseHTTPRequestHandler):
    server_version = "BlackTonyLocalService/1.0"

    def _read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0") or 0)
        if content_length <= 0:
            return {}
        raw = self.rfile.read(content_length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(200, {"ok": True})

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            self._send(200, {"ok": True, **snapshot_state()})
            return
        if parsed.path == "/api/cost-snapshot":
            history = load_cost_history()
            self._send(
                200,
                {
                    "ok": True,
                    "path": str(COST_FILE),
                    "history_path": str(COST_HISTORY_FILE),
                    "snapshot": load_cost_snapshot(),
                    "history": history,
                },
            )
            return
        if parsed.path == "/api/cost-history":
            self._send(
                200,
                {
                    "ok": True,
                    "path": str(COST_HISTORY_FILE),
                    "history": load_cost_history(),
                },
            )
            return
        self._send(404, {"ok": False, "message": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/cost-snapshot":
            try:
                payload = self._read_json_body()
                snapshot = payload.get("snapshot")
                if not isinstance(snapshot, dict):
                    self._send(400, {"ok": False, "message": "请求里缺少 snapshot 对象。"})
                    return
                save_cost_snapshot(snapshot)
                history = upsert_cost_history(snapshot)
                self._send(
                    200,
                    {
                        "ok": True,
                "message": "成本快照已保存到本地文件。",
                        "path": str(COST_FILE),
                        "history_path": str(COST_HISTORY_FILE),
                        "snapshot": snapshot,
                        "history": history,
                    },
                )
            except Exception as error:  # noqa: BLE001
                self._send(500, {"ok": False, "message": f"保存成本快照失败：{error}"})
            return

        if parsed.path != "/api/refresh":
            self._send(404, {"ok": False, "message": "Not found"})
            return

        payload = self._read_json_body()
        source = str(payload.get("source") or "unknown")
        mode = str(payload.get("mode") or DEFAULT_SYNC_MODE)
        start_date = str(payload.get("start_date") or "").strip() or None
        end_date = str(payload.get("end_date") or "").strip() or None
        current = snapshot_state()
        if current["running"]:
            self._send(409, {"ok": False, "message": "已有抓取任务正在执行。", **current})
            return

        thread = threading.Thread(target=refresh_job, args=(source, mode, start_date, end_date), daemon=True)
        thread.start()
        self._send(
            202,
            {
                "ok": True,
                "message": "已开始执行全量同步并重建仪表盘。",
                **snapshot_state(),
            },
        )


def main() -> int:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Local dashboard service running at http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
