# -*- coding: utf-8 -*-
"""Zero-dependency HTTP/API server for Dashboard V1."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from open_pit_competition.dashboard.service import (
    DashboardDataError,
    DashboardService,
)
from open_pit_competition.simulation.scenario_generator import (
    ScenarioGenerator,
    write_generated_scenario,
)
from open_pit_competition.simulation.task_generator import (
    RandomTaskConfigGenerator,
    load_json,
    write_generated_task_config,
)


class DashboardController:
    FIXED = {
        "S01": {
            "display_name": "S01 正常生产基线",
            "scenario": "configs/scenarios/s01_normal.json",
            "closed_loop": "configs/closed_loop_formal_s01.json",
        },
        "S02": {
            "display_name": "S02 车辆故障",
            "scenario": "configs/scenarios/s02_vehicle_failure.json",
            "closed_loop": "configs/closed_loop_formal_s02.json",
        },
        "S07": {
            "display_name": "S07 道路封闭",
            "scenario": "configs/scenarios/s07_road_closure.json",
            "closed_loop": "configs/closed_loop_formal_s07.json",
        },
    }

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root).resolve()
        self._lock = threading.Lock()
        self._process: Optional[subprocess.Popen] = None
        self._log_handle = None
        self._started_monotonic: Optional[float] = None
        self._state: Dict[str, Any] = {
            "state": "idle",
            "running": False,
            "pid": None,
            "exit_code": None,
            "scenario_id": None,
            "seed": None,
            "mode": None,
            "scenario_path": None,
            "closed_loop_config": None,
            "log_path": None,
        }

    def scenarios(self) -> Dict[str, Any]:
        fixed = [
            {
                "scenario_id": key,
                "display_name": value["display_name"],
                "type": "fixed",
            }
            for key, value in self.FIXED.items()
        ]
        fixed.append(
            {
                "scenario_id": "RANDOM",
                "display_name": "随机 Seed 场景",
                "type": "random",
                "modes": ["mixed", "failure", "closure", "compound"],
            }
        )
        return {"scenarios": fixed}

    def status(self) -> Dict[str, Any]:
        with self._lock:
            self._refresh_locked()
            result = dict(self._state)
            result["elapsed_s"] = self._elapsed_locked()
            result["log_tail"] = self._tail_log(
                result.get("log_path"), 36
            )
            return result

    def generate_random(self, seed: int, mode: str) -> Dict[str, Any]:
        seed = int(seed)
        mode = str(mode or "mixed")
        scenario = ScenarioGenerator(
            seed=seed,
            failure_vehicle_ids=("truck_2", "truck_3"),
        ).generate(mode=mode)

        scenario_rel = Path(
            "runtime_data/generated_scenarios/random_seed_{}.json".format(seed)
        )
        write_generated_scenario(
            scenario,
            str(self.project_root / scenario_rel),
        )

        base_path = self.project_root / "configs/closed_loop_formal_s01.json"
        task_config = RandomTaskConfigGenerator(
            seed=seed,
            base_config=load_json(str(base_path)),
        ).generate()

        closed_loop_rel = Path(
            "runtime_data/generated_closed_loop/random_seed_{}.json".format(seed)
        )
        write_generated_task_config(
            task_config,
            str(self.project_root / closed_loop_rel),
        )

        return {
            "seed": seed,
            "mode": scenario.mode,
            "scenario_id": scenario.config.scenario_id,
            "scenario_path": str(scenario_rel),
            "closed_loop_config": str(closed_loop_rel),
            "events": [
                {
                    "event_type": event.event_type,
                    "at_seconds": event.at_seconds,
                    "params": event.params,
                }
                for event in scenario.config.events
            ],
            "tasks": task_config.tasks,
        }

    def start(
        self,
        scenario_id: str,
        seed: Optional[int] = None,
        mode: str = "mixed",
    ) -> Dict[str, Any]:
        with self._lock:
            self._refresh_locked()
            if self._state.get("running"):
                raise RuntimeError("已有场景正在运行")

            scenario_id = str(scenario_id or "S01").upper()
            if scenario_id == "RANDOM":
                if seed is None:
                    raise ValueError("随机场景需要 seed")
                generated = self.generate_random(int(seed), mode)
                scenario_path = generated["scenario_path"]
                closed_loop_path = generated["closed_loop_config"]
                resolved_id = generated["scenario_id"]
                resolved_mode = generated["mode"]
                resolved_seed = int(seed)
            else:
                spec = self.FIXED.get(scenario_id)
                if not spec:
                    raise ValueError("不支持的场景 {}".format(scenario_id))
                scenario_path = spec["scenario"]
                closed_loop_path = spec["closed_loop"]
                resolved_id = scenario_id
                resolved_mode = "fixed"
                resolved_seed = None

            for rel in (scenario_path, closed_loop_path, "configs/fleet.json"):
                if not (self.project_root / rel).exists():
                    raise RuntimeError("缺少运行文件: {}".format(rel))

            logs_dir = self.project_root / "runtime_data/logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            log_rel = Path(
                "runtime_data/logs/dashboard_{}_{}.log".format(
                    str(resolved_id).lower(),
                    stamp,
                )
            )
            log_path = self.project_root / log_rel
            self._log_handle = log_path.open("w", encoding="utf-8", buffering=1)

            command = [
                sys.executable,
                "-m",
                "open_pit_competition.simulation.runtime",
                "--scenario",
                scenario_path,
                "--fleet",
                "configs/fleet.json",
                "--monitoring",
                "--closed-loop",
                "--closed-loop-config",
                closed_loop_path,
            ]
            env = dict(os.environ)
            src = str(self.project_root / "src")
            env["PYTHONPATH"] = (
                src
                if not env.get("PYTHONPATH")
                else src + os.pathsep + env["PYTHONPATH"]
            )

            self._process = subprocess.Popen(
                command,
                cwd=str(self.project_root),
                env=env,
                stdout=self._log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            self._started_monotonic = time.monotonic()
            self._state.update(
                {
                    "state": "running",
                    "running": True,
                    "pid": self._process.pid,
                    "exit_code": None,
                    "scenario_id": resolved_id,
                    "seed": resolved_seed,
                    "mode": resolved_mode,
                    "scenario_path": scenario_path,
                    "closed_loop_config": closed_loop_path,
                    "log_path": str(log_rel),
                    "command": command,
                }
            )
            return dict(self._state)

    def stop(self) -> Dict[str, Any]:
        with self._lock:
            self._refresh_locked()
            process = self._process
            if process is None or process.poll() is not None:
                self._state["state"] = "idle"
                self._state["running"] = False
                return dict(self._state)

            self._state["state"] = "stopping"
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGINT)
            except (OSError, ProcessLookupError):
                process.send_signal(signal.SIGINT)
            return dict(self._state)

    def _refresh_locked(self) -> None:
        if self._process is None:
            return
        exit_code = self._process.poll()
        if exit_code is None:
            self._state["running"] = True
            return

        final_elapsed = self._elapsed_locked()
        self._state["running"] = False
        self._state["elapsed_s"] = final_elapsed
        self._state["exit_code"] = int(exit_code)
        self._state["state"] = "finished" if exit_code == 0 else "error"
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            except OSError:
                pass
            self._log_handle = None

    def _elapsed_locked(self) -> float:
        if self._started_monotonic is None:
            return 0.0
        if self._state.get("running"):
            return round(time.monotonic() - self._started_monotonic, 1)
        return round(float(self._state.get("elapsed_s") or 0.0), 1)

    def _tail_log(self, raw_path: Optional[str], line_count: int) -> list:
        if not raw_path:
            return []
        path = Path(raw_path)
        if not path.is_absolute():
            path = self.project_root / path
        try:
            lines = path.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()
        except OSError:
            return []
        return lines[-int(line_count):]


class DashboardApplication:
    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root).resolve()
        self.frontend_root = self.project_root / "frontend"
        self.controller = DashboardController(self.project_root)
        self.service = DashboardService(self.project_root)

    def api_get(self, path: str) -> Any:
        control = self.controller.status()

        if path == "/api/health":
            return self.service.health(control)
        if path == "/api/state":
            return self.service.snapshot(control)
        if path == "/api/map":
            return self.service.map_data()
        if path == "/api/scenarios":
            return self.controller.scenarios()
        if path == "/api/control/status":
            return control

        snapshot = self.service.snapshot(control)
        if path == "/api/tasks":
            return {"tasks": snapshot["tasks"]}
        if path == "/api/events":
            return {"events": snapshot["events"], "alerts": snapshot["alerts"]}
        if path == "/api/monitoring":
            return {
                "stations": snapshot["stations"],
                "system": snapshot["system"],
                "data_collection": snapshot["metrics"]["data_collection"],
            }
        raise KeyError(path)

    def api_post(self, path: str, payload: Dict[str, Any]) -> Any:
        if path == "/api/control/generate":
            return self.controller.generate_random(
                int(payload.get("seed")),
                str(payload.get("mode", "mixed")),
            )
        if path == "/api/control/start":
            return self.controller.start(
                str(payload.get("scenario_id", "S01")),
                (
                    int(payload["seed"])
                    if payload.get("seed") not in (None, "")
                    else None
                ),
                str(payload.get("mode", "mixed")),
            )
        if path == "/api/control/stop":
            return self.controller.stop()
        raise KeyError(path)


def make_handler(app: DashboardApplication):
    class Handler(BaseHTTPRequestHandler):
        server_version = "OpenPitDashboardV1/1.0"

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path.startswith("/api/"):
                self._serve_api_get(path)
                return

            static_map = {
                "/": "index.html",
                "/index.html": "index.html",
                "/dashboard.css": "dashboard.css",
                "/dashboard.js": "dashboard.js",
            }
            name = static_map.get(path)
            if not name:
                self.send_error(404)
                return
            self._serve_static(name)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if not path.startswith("/api/"):
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length > 0 else b"{}"
                payload = json.loads(raw.decode("utf-8") or "{}")
                result = app.api_post(path, payload)
                self._json(result, 200)
            except KeyError:
                self._json({"error": "unknown endpoint"}, 404)
            except Exception as exc:
                self._json({"error": str(exc)}, 400)

        def _serve_api_get(self, path: str) -> None:
            try:
                self._json(app.api_get(path), 200)
            except KeyError:
                self._json({"error": "unknown endpoint"}, 404)
            except DashboardDataError as exc:
                self._json({"error": str(exc)}, 503)
            except Exception as exc:
                self._json({"error": str(exc)}, 500)

        def _serve_static(self, name: str) -> None:
            path = app.frontend_root / name
            try:
                data = path.read_bytes()
            except OSError:
                self.send_error(404)
                return

            content_type = {
                ".html": "text/html; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
            }.get(path.suffix, "application/octet-stream")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _json(self, payload: Any, status: int) -> None:
            data = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt: str, *args: Any) -> None:
            print("[DASHBOARD] " + fmt % args)

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--project-root",
        default=str(Path(__file__).resolve().parents[3]),
    )
    args = parser.parse_args()

    app = DashboardApplication(Path(args.project_root))
    server = ThreadingHTTPServer(
        (args.host, args.port),
        make_handler(app),
    )
    print("=" * 72)
    print("OPEN-PIT DASHBOARD V1")
    print("http://{}:{}".format(args.host, args.port))
    print("database: {}".format(app.service.database_path))
    print("=" * 72)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
