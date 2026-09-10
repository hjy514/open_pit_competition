# -*- coding: utf-8 -*-
"""Read-only live projection for the competition dashboard.

This module reads the existing SQLite runtime database and, when CARLA is
available, reads map geometry without modifying the CARLA world.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


class DashboardDataError(RuntimeError):
    pass


class DashboardService:
    def __init__(
        self,
        project_root: Optional[Path] = None,
        database_path: Optional[Path] = None,
    ) -> None:
        if project_root is None:
            project_root = Path(__file__).resolve().parents[3]
        self.project_root = Path(project_root).resolve()
        self.database_path = Path(
            database_path
            or self.project_root / "runtime_data/database/open_pit.db"
        ).resolve()
        self._map_cache: Optional[Dict[str, Any]] = None
        self._map_cache_at = 0.0

    # ------------------------------------------------------------------
    # Public read API
    # ------------------------------------------------------------------
    def health(self, control_status: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        db_ok = self.database_path.exists()
        message = "ready" if db_ok else "database not found"
        return {
            "ok": db_ok,
            "api_version": "dashboard-map-v14",
            "database": str(self.database_path),
            "database_status": "CONNECTED" if db_ok else "MISSING",
            "message": message,
            "control": control_status or {},
        }

    def snapshot(
        self,
        control_status: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        control_status = dict(control_status or {})
        if not self.database_path.exists():
            return self._empty_snapshot(control_status)

        try:
            with self._connect() as conn:
                vehicle_boundary = self._current_run_boundary(
                    conn, "vehicle_telemetry", "id", "timestamp_s"
                )
                station_boundary = self._current_run_boundary(
                    conn, "station_readings", "id", "timestamp_s"
                )
                assignment_boundary = self._current_run_boundary(
                    conn, "assignments", "id", "timestamp_s"
                )
                event_boundary = self._current_run_boundary(
                    conn, "events", "rowid", "timestamp_s"
                )

                vehicles = self._latest_vehicles(conn, vehicle_boundary)
                trails = self._vehicle_trails(conn, vehicle_boundary)
                stations = self._stations(conn, station_boundary)
                road_state = self._road_state(conn)
                tasks = self._tasks(conn, control_status)
                events = self._events(conn, event_boundary)
                assignments = self._assignments(conn, assignment_boundary)

                latest_elapsed = max(
                    [float(v.get("timestamp_s") or 0.0) for v in vehicles] + [0.0]
                )

                metrics = self._metrics(
                    vehicles=vehicles,
                    tasks=tasks,
                    road_state=road_state,
                    events=events,
                    assignments=assignments,
                    conn=conn,
                    vehicle_boundary=vehicle_boundary,
                    station_boundary=station_boundary,
                    event_boundary=event_boundary,
                    assignment_boundary=assignment_boundary,
                )

                return {
                    "system": {
                        "map_name": self._config_map_name(),
                        "carla": "RUNNING" if control_status.get("running") else "READY",
                        "closed_loop": (
                            "RUNNING" if control_status.get("running") else "IDLE"
                        ),
                        "decision": (
                            "ACTIVE" if control_status.get("running") else "READY"
                        ),
                        "monitoring": (
                            "ACTIVE" if control_status.get("running") else "READY"
                        ),
                        "storage": "WRITING" if control_status.get("running") else "READY",
                        "database": "CONNECTED",
                    },
                    "run": {
                        "running": bool(control_status.get("running")),
                        "state": control_status.get("state", "idle"),
                        "scenario_id": control_status.get("scenario_id"),
                        "seed": control_status.get("seed"),
                        "mode": control_status.get("mode"),
                        "elapsed_s": round(
                            float(
                                control_status.get("elapsed_s")
                                if control_status.get("elapsed_s") is not None
                                else latest_elapsed
                            ),
                            1,
                        ),
                    },
                    "vehicles": vehicles,
                    "vehicle_trails": trails,
                    "stations": stations,
                    "road_state": road_state,
                    "tasks": tasks,
                    "events": events,
                    "assignments": assignments,
                    "metrics": metrics,
                    "alerts": self._alerts(vehicles, road_state, events),
                }
        except sqlite3.Error as exc:
            raise DashboardDataError("SQLite read failed: {}".format(exc))

    def map_data(self) -> Dict[str, Any]:
        # A successful CARLA map result is effectively static for the current map.
        if self._map_cache and self._map_cache.get("source") == "carla_live":
            return self._map_cache

        # Retry a fallback cache after a short period so opening the dashboard
        # before CARLA does not permanently freeze the map in fallback mode.
        if self._map_cache and time.time() - self._map_cache_at < 3.0:
            return self._map_cache

        try:
            result = self._map_from_carla()
        except Exception as exc:
            result = self._map_fallback(str(exc))

        self._map_cache = result
        self._map_cache_at = time.time()
        return result

    # ------------------------------------------------------------------
    # SQLite helpers
    # ------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        uri = "file:{}?mode=ro".format(self.database_path.as_posix())
        conn = sqlite3.connect(uri, uri=True, timeout=0.25)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _current_run_boundary(
        conn: sqlite3.Connection,
        table: str,
        id_column: str,
        timestamp_column: str,
        scan_limit: int = 6000,
    ) -> int:
        # IDs are append-only in the data tables. Runtime elapsed timestamps
        # reset near zero at the beginning of a new run. Detect the latest reset
        # without requiring a schema migration or run_id column.
        sql = (
            "SELECT {id_col} AS rid, {ts_col} AS ts "
            "FROM {table} ORDER BY {id_col} DESC LIMIT ?"
        ).format(
            id_col=id_column,
            ts_col=timestamp_column,
            table=table,
        )
        rows = list(conn.execute(sql, (int(scan_limit),)))
        if not rows:
            return 0
        rows.reverse()

        boundary = int(rows[0]["rid"])
        previous_ts = float(rows[0]["ts"] or 0.0)
        for row in rows[1:]:
            current_ts = float(row["ts"] or 0.0)
            # A real scenario reset is large compared with normal interleaving.
            if current_ts + 5.0 < previous_ts:
                boundary = int(row["rid"])
            previous_ts = current_ts
        return boundary

    @staticmethod
    def _rows_to_dicts(rows: Iterable[sqlite3.Row]) -> List[Dict[str, Any]]:
        return [dict(row) for row in rows]

    def _latest_vehicles(
        self,
        conn: sqlite3.Connection,
        boundary: int,
    ) -> List[Dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT v.*
            FROM vehicle_telemetry v
            JOIN (
                SELECT vehicle_id, MAX(id) AS max_id
                FROM vehicle_telemetry
                WHERE id >= ?
                GROUP BY vehicle_id
            ) latest
            ON latest.max_id = v.id
            ORDER BY v.vehicle_id
            """,
            (boundary,),
        ).fetchall()
        result = self._rows_to_dicts(rows)
        for item in result:
            item["healthy"] = bool(item.get("healthy"))
            item["available"] = bool(item.get("available"))
        return result

    def _vehicle_trails(
        self,
        conn: sqlite3.Connection,
        boundary: int,
        points_per_vehicle: int = 100,
    ) -> Dict[str, List[Dict[str, float]]]:
        vehicle_ids = [
            str(row[0])
            for row in conn.execute(
                """
                SELECT DISTINCT vehicle_id
                FROM vehicle_telemetry
                WHERE id >= ?
                ORDER BY vehicle_id
                """,
                (boundary,),
            )
        ]
        trails: Dict[str, List[Dict[str, float]]] = {}
        for vehicle_id in vehicle_ids:
            rows = conn.execute(
                """
                SELECT id, timestamp_s, x, y, z
                FROM vehicle_telemetry
                WHERE id >= ? AND vehicle_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (boundary, vehicle_id, int(points_per_vehicle)),
            ).fetchall()
            values = [
                {
                    "timestamp_s": float(row["timestamp_s"]),
                    "x": float(row["x"]),
                    "y": float(row["y"]),
                    "z": float(row["z"]),
                }
                for row in reversed(rows)
            ]
            trails[vehicle_id] = values
        return trails

    def _stations(
        self,
        conn: sqlite3.Connection,
        reading_boundary: int,
    ) -> List[Dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT
                s.*,
                r.timestamp_s,
                r.vehicle_count,
                r.avg_speed_kmh,
                r.congestion_level,
                r.road_risk,
                r.visibility
            FROM fixed_stations s
            LEFT JOIN station_readings r
              ON r.id = (
                SELECT MAX(r2.id)
                FROM station_readings r2
                WHERE r2.station_id = s.station_id
                  AND r2.id >= ?
              )
            ORDER BY s.station_id
            """,
            (reading_boundary,),
        ).fetchall()
        result = self._rows_to_dicts(rows)
        for item in result:
            item["camera_enabled"] = bool(item.get("camera_enabled"))
            item["active"] = bool(item.get("active"))
        return result

    def _road_state(self, conn: sqlite3.Connection) -> List[Dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT *
            FROM road_state
            ORDER BY road_id, lane_id
            """
        ).fetchall()
        result = self._rows_to_dicts(rows)
        for item in result:
            item["open"] = bool(item.get("open"))
        return result

    def _tasks(
        self,
        conn: sqlite3.Connection,
        control_status: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        configured = self._configured_tasks(control_status)
        db_rows = {
            str(row["task_id"]): dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM tasks
                ORDER BY release_time_s, priority DESC, task_id
                """
            )
        }

        if configured:
            result = []
            for template in configured:
                task_id = str(template.get("task_id"))
                merged = dict(template)
                merged.update(db_rows.get(task_id, {}))
                result.append(merged)
            return result

        return list(db_rows.values())

    def _configured_tasks(
        self,
        control_status: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        raw_path = control_status.get("closed_loop_config")
        if not raw_path:
            return []
        path = Path(str(raw_path))
        if not path.is_absolute():
            path = self.project_root / path
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [
            dict(item)
            for item in data.get("task_templates", [])
            if isinstance(item, dict)
        ]

    def _events(
        self,
        conn: sqlite3.Connection,
        boundary: int,
        limit: int = 80,
    ) -> List[Dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT
                rowid AS row_id,
                event_id,
                timestamp_s,
                event_type,
                target_type,
                target_id,
                payload_json,
                handled
            FROM events
            WHERE rowid >= ?
            ORDER BY rowid DESC
            LIMIT ?
            """,
            (boundary, int(limit)),
        ).fetchall()
        result = []
        for row in reversed(rows):
            item = dict(row)
            try:
                item["payload"] = json.loads(item.pop("payload_json") or "{}")
            except ValueError:
                item["payload"] = {}
            item["handled"] = bool(item.get("handled"))
            result.append(item)
        return result

    def _assignments(
        self,
        conn: sqlite3.Connection,
        boundary: int,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT *
            FROM assignments
            WHERE id >= ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (boundary, int(limit)),
        ).fetchall()
        return list(reversed(self._rows_to_dicts(rows)))

    def _metrics(
        self,
        vehicles: Sequence[Dict[str, Any]],
        tasks: Sequence[Dict[str, Any]],
        road_state: Sequence[Dict[str, Any]],
        events: Sequence[Dict[str, Any]],
        assignments: Sequence[Dict[str, Any]],
        conn: sqlite3.Connection,
        vehicle_boundary: int,
        station_boundary: int,
        event_boundary: int,
        assignment_boundary: int,
    ) -> Dict[str, Any]:
        statuses = [str(item.get("status") or "PENDING").upper() for item in tasks]
        completed = sum(1 for status in statuses if status == "COMPLETED")
        active_tasks = sum(
            1
            for status in statuses
            if status not in {"PENDING", "COMPLETED", "CANCELLED"}
        )

        task_assignment_counts: Dict[str, int] = {}
        for assignment in assignments:
            task_id = str(assignment.get("task_id") or "")
            task_assignment_counts[task_id] = task_assignment_counts.get(task_id, 0) + 1
        reschedules = sum(max(0, count - 1) for count in task_assignment_counts.values())

        return {
            "online_cat": len(vehicles),
            "healthy_cat": sum(1 for item in vehicles if item.get("healthy")),
            "task_count": len(tasks),
            "completed_tasks": completed,
            "active_tasks": active_tasks,
            "pending_tasks": sum(1 for status in statuses if status == "PENDING"),
            "completion_rate": (
                round(completed / float(len(tasks)), 4) if tasks else 0.0
            ),
            "reschedules": reschedules,
            "road_open": all(item.get("open", True) for item in road_state),
            "unhandled_events": sum(1 for item in events if not item.get("handled")),
            "data_collection": {
                "vehicle_telemetry": self._count_since(
                    conn, "vehicle_telemetry", "id", vehicle_boundary
                ),
                "station_readings": self._count_since(
                    conn, "station_readings", "id", station_boundary
                ),
                "events": self._count_since(conn, "events", "rowid", event_boundary),
                "assignments": self._count_since(
                    conn, "assignments", "id", assignment_boundary
                ),
            },
        }

    @staticmethod
    def _count_since(
        conn: sqlite3.Connection,
        table: str,
        id_column: str,
        boundary: int,
    ) -> int:
        row = conn.execute(
            "SELECT COUNT(*) FROM {} WHERE {} >= ?".format(table, id_column),
            (boundary,),
        ).fetchone()
        return int(row[0]) if row else 0

    @staticmethod
    def _alerts(
        vehicles: Sequence[Dict[str, Any]],
        road_state: Sequence[Dict[str, Any]],
        events: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        alerts: List[Dict[str, Any]] = []
        for vehicle in vehicles:
            if not vehicle.get("healthy", True):
                alerts.append(
                    {
                        "level": "danger",
                        "type": "vehicle_fault",
                        "title": "{} 车辆故障".format(vehicle.get("vehicle_id")),
                        "detail": "当前任务 {}".format(
                            vehicle.get("current_task_id") or "—"
                        ),
                        "target": "dispatch",
                    }
                )

        closed = [item for item in road_state if not item.get("open", True)]
        if closed:
            alerts.append(
                {
                    "level": "warning",
                    "type": "road_closed",
                    "title": "运输道路存在封闭状态",
                    "detail": "封闭 road/lane 数量 {}".format(len(closed)),
                    "target": "dispatch",
                }
            )

        important_tokens = (
            "failure",
            "fault",
            "closure",
            "closed",
            "recovery",
            "reopen",
            "emergency",
        )
        for event in reversed(events[-20:]):
            event_type = str(event.get("event_type") or "").lower()
            if any(token in event_type for token in important_tokens):
                alerts.append(
                    {
                        "level": (
                            "danger"
                            if any(token in event_type for token in ("failure", "fault", "closure", "emergency"))
                            else "info"
                        ),
                        "type": event_type,
                        "title": str(event.get("event_type") or "运行事件"),
                        "detail": "{} · {:.1f}s".format(
                            event.get("target_id") or "system",
                            float(event.get("timestamp_s") or 0.0),
                        ),
                        "target": "dispatch",
                    }
                )
                if len(alerts) >= 6:
                    break
        return alerts

    # ------------------------------------------------------------------
    # Map projection
    # ------------------------------------------------------------------
    @staticmethod
    def _road_polylines_from_waypoints(
        waypoints: Sequence[Any],
        max_gap_m: float = 8.0,
    ) -> List[Dict[str, Any]]:
        """Convert CARLA-generated waypoints into drawable lane polylines.

        Every point is copied directly from waypoint.transform.location.
        No XODR transform, no Y inversion, no coordinate fitting is applied.
        Routes, telemetry and roads therefore share the same CARLA world frame.
        """
        groups: Dict[Tuple[int, int, int], List[Any]] = {}
        for waypoint in waypoints:
            key = (
                int(getattr(waypoint, "road_id", 0)),
                int(getattr(waypoint, "section_id", 0)),
                int(getattr(waypoint, "lane_id", 0)),
            )
            groups.setdefault(key, []).append(waypoint)

        result: List[Dict[str, Any]] = []
        for key in sorted(groups):
            ordered = sorted(
                groups[key],
                key=lambda item: float(getattr(item, "s", 0.0)),
            )

            chunks: List[List[Dict[str, float]]] = []
            chunk: List[Dict[str, float]] = []
            previous: Optional[Dict[str, float]] = None
            is_junction = False

            for waypoint in ordered:
                location = waypoint.transform.location
                point = {
                    "x": float(location.x),
                    "y": float(location.y),
                    "z": float(location.z),
                }
                is_junction = is_junction or bool(
                    getattr(waypoint, "is_junction", False)
                )

                if previous is not None:
                    dx = point["x"] - previous["x"]
                    dy = point["y"] - previous["y"]
                    dz = point["z"] - previous["z"]
                    gap = (dx * dx + dy * dy + dz * dz) ** 0.5

                    # Duplicate samples are common at section boundaries.
                    if gap < 0.02:
                        continue

                    # Do not connect two unrelated pieces that happen to share
                    # the same road/section/lane identifier.
                    if gap > float(max_gap_m):
                        if len(chunk) >= 2:
                            chunks.append(chunk)
                        chunk = []

                chunk.append(point)
                previous = point

            if len(chunk) >= 2:
                chunks.append(chunk)

            for part_index, points in enumerate(chunks):
                result.append(
                    {
                        "road_id": key[0],
                        "section_id": key[1],
                        "lane_id": key[2],
                        "part_index": part_index,
                        "is_junction": is_junction,
                        "points": points,
                    }
                )
        return result

    @staticmethod
    def _road_polylines_from_topology(
        topology: Sequence[Any],
    ) -> List[Dict[str, Any]]:
        """Coarse fallback for unusual CARLA maps where generate_waypoints fails."""
        result: List[Dict[str, Any]] = []
        for index, pair in enumerate(topology):
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                continue
            start_wp, end_wp = pair
            start_loc = start_wp.transform.location
            end_loc = end_wp.transform.location
            result.append(
                {
                    "road_id": int(getattr(start_wp, "road_id", 0)),
                    "section_id": int(getattr(start_wp, "section_id", 0)),
                    "lane_id": int(getattr(start_wp, "lane_id", 0)),
                    "part_index": index,
                    "is_junction": bool(
                        getattr(start_wp, "is_junction", False)
                        or getattr(end_wp, "is_junction", False)
                    ),
                    "points": [
                        {
                            "x": float(start_loc.x),
                            "y": float(start_loc.y),
                            "z": float(start_loc.z),
                        },
                        {
                            "x": float(end_loc.x),
                            "y": float(end_loc.y),
                            "z": float(end_loc.z),
                        },
                    ],
                }
            )
        return result

    def _map_from_carla(self) -> Dict[str, Any]:
        system = self._read_json(self.project_root / "configs/system.json")
        host = str(system.get("host", "127.0.0.1"))
        port = int(system.get("port", 2000))
        timeout = min(float(system.get("timeout_seconds", 20.0)), 3.0)
        carla_root = Path(
            str(system.get("carla_root", "/home/xiaoa/carla"))
        ).expanduser()

        self._add_carla_paths(carla_root)

        import carla  # type: ignore
        from agents.navigation.global_route_planner import GlobalRoutePlanner  # type: ignore
        from agents.navigation.global_route_planner_dao import GlobalRoutePlannerDAO  # type: ignore

        client = carla.Client(host, port)
        client.set_timeout(timeout)
        world = client.get_world()
        carla_map = world.get_map()
        spawn_points = carla_map.get_spawn_points()

        # ------------------------------------------------------------------
        # Authoritative visual road network.
        #
        # This deliberately follows the old desktop architecture:
        # roads + routes + vehicles all come from CARLA world coordinates.
        # No direct XODR parsing is used by the desktop map.
        # ------------------------------------------------------------------
        sample_distance_m = 2.0
        generated_waypoints = list(
            carla_map.generate_waypoints(sample_distance_m)
        )
        roads = self._road_polylines_from_waypoints(
            generated_waypoints,
            max_gap_m=sample_distance_m * 4.0,
        )

        road_source = "generate_waypoints"
        if not roads:
            topology = list(carla_map.get_topology())
            roads = self._road_polylines_from_topology(topology)
            road_source = "topology_fallback"

        planner = GlobalRoutePlanner(
            GlobalRoutePlannerDAO(carla_map, 2.0)
        )
        planner.setup()

        routes = []
        for route_index, (from_index, to_index, name) in enumerate(
            (
                (12, 48, "装载点 12 → 卸载点 48"),
                (78, 48, "装载点 78 → 卸载点 48"),
            )
        ):
            if from_index >= len(spawn_points) or to_index >= len(spawn_points):
                continue
            traced = planner.trace_route(
                spawn_points[from_index].location,
                spawn_points[to_index].location,
            )
            points = [
                {
                    "x": float(waypoint.transform.location.x),
                    "y": float(waypoint.transform.location.y),
                    "z": float(waypoint.transform.location.z),
                    "road_id": int(waypoint.road_id),
                    "lane_id": int(waypoint.lane_id),
                }
                for waypoint, _road_option in traced
            ]
            routes.append(
                {
                    "route_id": "haul_to_dump_{}_to_{}".format(
                        from_index, to_index
                    ),
                    "name": name,
                    "from_spawn_index": from_index,
                    "to_spawn_index": to_index,
                    "color_index": route_index,
                    "points": points,
                }
            )

        areas = []
        for spawn_index, kind, name in (
            (12, "loading", "L12"),
            (78, "loading", "L78"),
            (48, "dump", "D48"),
        ):
            if spawn_index >= len(spawn_points):
                continue
            loc = spawn_points[spawn_index].location
            areas.append(
                {
                    "spawn_index": spawn_index,
                    "kind": kind,
                    "name": name,
                    "x": float(loc.x),
                    "y": float(loc.y),
                    "z": float(loc.z),
                }
            )

        all_points: List[Dict[str, Any]] = []
        all_points.extend(
            point
            for road in roads
            for point in road.get("points", [])
        )
        all_points.extend(
            point
            for route in routes
            for point in route.get("points", [])
        )
        all_points.extend(
            {
                "x": area["x"],
                "y": area["y"],
                "z": area["z"],
            }
            for area in areas
        )

        total_road_points = sum(
            len(road.get("points", []))
            for road in roads
        )
        total_road_segments = sum(
            max(0, len(road.get("points", [])) - 1)
            for road in roads
        )

        return {
            "schema_version": "carla-runtime-map-v14",
            "source": "carla_world",
            "road_source": road_source,
            "map_name": str(carla_map.name).split("/")[-1],
            "roads": roads,
            "routes": routes,
            "task_areas": areas,
            "bounds": self._bounds(all_points),
            "road_line_count": len(roads),
            "road_point_count": total_road_points,
            "road_segment_count": total_road_segments,
            "generated_waypoint_count": len(generated_waypoints),
            "note": (
                "CARLA世界坐标同源路网/路线；Dashboard只读，"
                "不spawn车辆、不load_world、不修改控制。"
            ),
        }

    def _map_fallback(self, error: str) -> Dict[str, Any]:
        points: List[Dict[str, float]] = []
        stations: List[Dict[str, Any]] = []
        trails: Dict[str, List[Dict[str, float]]] = {}
        try:
            if self.database_path.exists():
                with self._connect() as conn:
                    boundary = self._current_run_boundary(
                        conn, "vehicle_telemetry", "id", "timestamp_s"
                    )
                    trails = self._vehicle_trails(conn, boundary)
                    points.extend(
                        point
                        for values in trails.values()
                        for point in values
                    )
                    station_boundary = self._current_run_boundary(
                        conn, "station_readings", "id", "timestamp_s"
                    )
                    stations = self._stations(conn, station_boundary)
                    points.extend(
                        {
                            "x": float(item["x"]),
                            "y": float(item["y"]),
                            "z": float(item["z"]),
                        }
                        for item in stations
                    )
        except Exception:
            pass

        return {
            "schema_version": "carla-runtime-map-v14",
            "source": "database_fallback",
            "map_name": self._config_map_name(),
            "roads": [],
            "road_line_count": 0,
            "road_point_count": 0,
            "road_segment_count": 0,
            "routes": [],
            "task_areas": [],
            "bounds": self._bounds(points),
            "note": "CARLA地图暂不可读，当前使用遥测/固定站点自动范围。",
            "error": error,
        }

    @staticmethod
    def _bounds(points: Sequence[Dict[str, Any]]) -> Optional[Dict[str, float]]:
        if not points:
            return None
        xs = [float(item["x"]) for item in points]
        ys = [float(item["y"]) for item in points]
        pad_x = max(10.0, (max(xs) - min(xs)) * 0.08)
        pad_y = max(10.0, (max(ys) - min(ys)) * 0.08)
        return {
            "min_x": min(xs) - pad_x,
            "max_x": max(xs) + pad_x,
            "min_y": min(ys) - pad_y,
            "max_y": max(ys) + pad_y,
        }

    @staticmethod
    def _add_carla_paths(carla_root: Path) -> None:
        candidates = [
            carla_root / "PythonAPI/carla",
            carla_root / "Dist/CARLA_Shipping_0.9.10-dirty/LinuxNoEditor/PythonAPI/carla",
        ]
        for candidate in candidates:
            if candidate.exists() and str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))

        dist_candidates = [
            carla_root / "PythonAPI/carla/dist",
            carla_root / "Dist/CARLA_Shipping_0.9.10-dirty/LinuxNoEditor/PythonAPI/carla/dist",
        ]
        for dist in dist_candidates:
            if not dist.exists():
                continue
            eggs = sorted(dist.glob("carla-0.9.10-py3.7-linux-x86_64.egg"))
            for egg in eggs:
                if str(egg) not in sys.path:
                    sys.path.insert(0, str(egg))

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------
    def _config_map_name(self) -> str:
        data = self._read_json(self.project_root / "configs/map.json")
        return str(data.get("map_name", "0325_5"))

    @staticmethod
    def _read_json(path: Path) -> Dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _empty_snapshot(self, control_status: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "system": {
                "map_name": self._config_map_name(),
                "carla": "READY",
                "closed_loop": "IDLE",
                "decision": "READY",
                "monitoring": "READY",
                "storage": "MISSING",
                "database": "MISSING",
            },
            "run": {
                "running": bool(control_status.get("running")),
                "state": control_status.get("state", "idle"),
                "scenario_id": control_status.get("scenario_id"),
                "seed": control_status.get("seed"),
                "mode": control_status.get("mode"),
                "elapsed_s": 0.0,
            },
            "vehicles": [],
            "vehicle_trails": {},
            "stations": [],
            "road_state": [],
            "tasks": [],
            "events": [],
            "assignments": [],
            "alerts": [],
            "metrics": {
                "online_cat": 0,
                "healthy_cat": 0,
                "task_count": 0,
                "completed_tasks": 0,
                "active_tasks": 0,
                "pending_tasks": 0,
                "completion_rate": 0.0,
                "reschedules": 0,
                "road_open": True,
                "unhandled_events": 0,
                "data_collection": {
                    "vehicle_telemetry": 0,
                    "station_readings": 0,
                    "events": 0,
                    "assignments": 0,
                },
            },
        }
