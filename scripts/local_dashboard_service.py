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


ROOT = Path(__file__).resolve().parents[1]
BEIJING_TZ = ZoneInfo("Asia/Shanghai")
HOST = "127.0.0.1"
PORT = 8765
CONFIG_FILE = ROOT / "data" / "yeusoft_local_config.json"
COST_FILE = ROOT / "data" / "store_cost_snapshot.json"
SCAN_OUTPUT = ROOT / "reports" / "yeusoft_report_capture"


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


def refresh_job() -> None:
    config = load_local_config()
    env = {
        **os.environ,
        "YEU_SITE_URL": str(config.get("site_url") or "https://jypos.yeusoft.net/"),
        "YEU_USERNAME": str(config.get("username") or ""),
        "YEU_PASSWORD": str(config.get("password") or ""),
    }

    update_state(
        running=True,
        started_at=now_text(),
        finished_at=None,
        status="running",
        message="正在抓取 Yeusoft 报表并重建仪表盘。",
        steps=[],
    )

    try:
        append_step("读取本地配置", "ok", "已读取本地 Yeusoft 登录配置和成本快照。")

        if not env["YEU_USERNAME"] or not env["YEU_PASSWORD"]:
            raise RuntimeError("缺少 Yeusoft 用户名或密码，请先填写 data/yeusoft_local_config.json。")

        scan = run_command(["node", "scripts/scan_yeusoft_useful_reports.mjs"], env=env)
        if scan.returncode != 0:
            raise RuntimeError(f"关键报表扫描失败：{scan.stderr.strip() or scan.stdout.strip()}")
        append_step("扫描关键报表", "ok", "已抓取关键报表结构与查询返回，用于后续优化看板。")

        build_cmd = [
            "python3",
            "scripts/build_inventory_dashboard.py",
            "--cost-file",
            str(COST_FILE),
        ]
        build = run_command(build_cmd, env=env)
        if build.returncode != 0:
            raise RuntimeError(f"看板重建失败：{build.stderr.strip() or build.stdout.strip()}")
        append_step("重建经营仪表盘", "ok", "已使用最新本地数据和成本快照重建仪表盘。")

        last_scan_index = str((SCAN_OUTPUT / "index.json").resolve()) if (SCAN_OUTPUT / "index.json").exists() else None
        last_dashboard = str((ROOT / "docs" / "dashboard" / "index.html").resolve())
        update_state(
            running=False,
            finished_at=now_text(),
            status="success",
            message="抓取和重建已完成，可以刷新首页和仪表盘查看最新结果。",
            last_scan_index=last_scan_index,
            last_dashboard=last_dashboard,
        )
    except Exception as error:  # noqa: BLE001
        append_step("执行失败", "error", str(error))
        update_state(
            running=False,
            finished_at=now_text(),
            status="error",
            message=str(error),
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
            self._send(
                200,
                {
                    "ok": True,
                    "path": str(COST_FILE),
                    "snapshot": load_cost_snapshot(),
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
                self._send(
                    200,
                    {
                        "ok": True,
                        "message": "成本快照已保存到本地文件。",
                        "path": str(COST_FILE),
                        "snapshot": snapshot,
                    },
                )
            except Exception as error:  # noqa: BLE001
                self._send(500, {"ok": False, "message": f"保存成本快照失败：{error}"})
            return

        if parsed.path != "/api/refresh":
            self._send(404, {"ok": False, "message": "Not found"})
            return

        current = snapshot_state()
        if current["running"]:
            self._send(409, {"ok": False, "message": "已有抓取任务正在执行。", **current})
            return

        thread = threading.Thread(target=refresh_job, daemon=True)
        thread.start()
        self._send(
            202,
            {
                "ok": True,
                "message": "已开始抓取关键报表并重建仪表盘。",
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
