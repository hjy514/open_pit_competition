# -*- coding: utf-8 -*-
"""Monitoring V1B orchestration.

Design guarantee:
- reads CarlaAdapter state only;
- spawns only sensor.camera.rgb actors;
- never applies vehicle control;
- never changes destinations or VehicleBehavior contexts;
- monitoring failures are intended to be isolated by SimulationRuntime.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Dict, Optional

from open_pit_competition.storage.database import OpenPitDatabase
from open_pit_competition.storage.models import (
    FixedStationRecord,
    RoadStateRecord,
    StationReadingRecord,
    VehicleTelemetryRecord,
)

from .fixed_station import FixedStationObserver
from .mobile_collector import MobileCollector
from .models import CameraConfig, FixedStationConfig, MonitoringSnapshot


class MonitoringManager:
    def __init__(
        self,
        adapter,
        stations_path="configs/monitoring_stations.json",
        camera_layout_path="configs/monitoring_camera_layout.json",
        database_path="runtime_data/database/open_pit.db",
        camera_enabled=True,
        telemetry_interval_s=0.5,
        station_interval_s=1.0,
        camera_output_dir="runtime_data/monitoring/cameras",
    ):
        self.adapter = adapter
        self.stations_path = Path(stations_path)
        self.camera_layout_path = Path(camera_layout_path)
        self.database = OpenPitDatabase(database_path)
        self.camera_enabled = bool(camera_enabled)
        self.telemetry_interval_s = max(0.1, float(telemetry_interval_s))
        self.station_interval_s = max(0.2, float(station_interval_s))
        self.camera_output_dir = Path(camera_output_dir)

        self.station_configs: Dict[str, FixedStationConfig] = {}
        self.camera_configs: Dict[str, CameraConfig] = {}
        self.observers: Dict[str, FixedStationObserver] = {}
        self.camera_actors: Dict[str, object] = {}
        self.latest_frame_paths: Dict[str, str] = {}
        self.camera_frame_counts: Dict[str, int] = {}
        self._frame_locks: Dict[str, threading.Lock] = {}

        self.mobile_collector = MobileCollector()
        self.latest_snapshot = MonitoringSnapshot(timestamp_s=0.0)

        self._next_telemetry_at = 0.0
        self._next_station_at = 0.0
        self._started = False
        self._closed = False

    def _load_configs(self):
        with self.stations_path.open("r", encoding="utf-8") as f:
            stations_data = json.load(f)

        with self.camera_layout_path.open("r", encoding="utf-8") as f:
            camera_data = json.load(f)

        current_map = str(self.adapter.world.get_map().name).split("/")[-1]
        expected_station_map = stations_data.get("map_id")
        expected_camera_map = camera_data.get("map_id")

        for expected in (expected_station_map, expected_camera_map):
            if expected and expected != current_map:
                raise RuntimeError(
                    "Monitoring map mismatch: current={} expected={}".format(
                        current_map,
                        expected,
                    )
                )

        for item in stations_data.get("stations", []):
            cfg = FixedStationConfig(
                station_id=str(item["station_id"]),
                road_id=int(item["road_id"]),
                lane_id=int(item["lane_id"]),
                x=float(item["x"]),
                y=float(item["y"]),
                z=float(item["z"]),
                monitor_radius_m=float(item.get("monitor_radius_m", 80.0)),
                observation_vertical_tolerance_m=float(
                    item.get("observation_vertical_tolerance_m", 20.0)
                ),
                camera_enabled=bool(item.get("camera_enabled", True)),
            )
            self.station_configs[cfg.station_id] = cfg

        for item in camera_data.get("stations", []):
            transform = item["camera_transform"]
            policy = item.get("camera_policy", {})
            cfg = CameraConfig(
                station_id=str(item["station_id"]),
                placement=str(item.get("placement", "unknown")),
                x=float(transform["x"]),
                y=float(transform["y"]),
                z=float(transform["z"]),
                pitch=float(transform["pitch"]),
                yaw=float(transform["yaw"]),
                roll=float(transform.get("roll", 0.0)),
                image_width=int(policy.get("image_width", 640)),
                image_height=int(policy.get("image_height", 360)),
                target_fps=float(policy.get("target_fps", 5.0)),
                fov_deg=float(policy.get("fov_deg", 90.0)),
            )
            self.camera_configs[cfg.station_id] = cfg

        missing = sorted(set(self.station_configs) - set(self.camera_configs))
        if self.camera_enabled and missing:
            raise RuntimeError(
                "Missing camera layout for stations: {}".format(
                    ",".join(missing)
                )
            )

        self.observers = {
            station_id: FixedStationObserver(cfg, station_index=index)
            for index, (station_id, cfg) in enumerate(
                sorted(self.station_configs.items())
            )
        }

    def _register_stations(self):
        self.database.initialize()
        for cfg in self.station_configs.values():
            self.database.upsert_fixed_station(
                FixedStationRecord(
                    station_id=cfg.station_id,
                    station_type="road_monitor",
                    x=cfg.x,
                    y=cfg.y,
                    z=cfg.z,
                    road_id=cfg.road_id,
                    lane_id=cfg.lane_id,
                    monitor_radius_m=cfg.monitor_radius_m,
                    camera_enabled=(
                        self.camera_enabled and cfg.camera_enabled
                    ),
                    active=True,
                )
            )

    def _configure_camera_blueprint(self, camera_cfg):
        bp = self.adapter.world.get_blueprint_library().find("sensor.camera.rgb")
        bp.set_attribute("image_size_x", str(camera_cfg.image_width))
        bp.set_attribute("image_size_y", str(camera_cfg.image_height))
        bp.set_attribute("fov", str(camera_cfg.fov_deg))

        if bp.has_attribute("sensor_tick"):
            fps = max(0.5, float(camera_cfg.target_fps))
            bp.set_attribute("sensor_tick", str(1.0 / fps))

        # The custom mine map preview was very bright. Use compensation only
        # when CARLA 0.9.10 exposes the attribute; do not assume it exists.
        if bp.has_attribute("exposure_compensation"):
            bp.set_attribute("exposure_compensation", "-1.0")

        return bp

    def _camera_transform(self, camera_cfg):
        carla = self.adapter.carla
        return carla.Transform(
            carla.Location(
                x=camera_cfg.x,
                y=camera_cfg.y,
                z=camera_cfg.z,
            ),
            carla.Rotation(
                pitch=camera_cfg.pitch,
                yaw=camera_cfg.yaw,
                roll=camera_cfg.roll,
            ),
        )

    def _camera_callback(self, station_id):
        output_path = self.camera_output_dir / "{}_latest.png".format(station_id)
        lock = self._frame_locks.setdefault(station_id, threading.Lock())

        def callback(image):
            if self._closed:
                return
            if not lock.acquire(False):
                return
            try:
                image.save_to_disk(str(output_path))
                self.latest_frame_paths[station_id] = str(output_path)
                self.camera_frame_counts[station_id] = (
                    self.camera_frame_counts.get(station_id, 0) + 1
                )
            except Exception:
                # Camera I/O must never affect vehicle control.
                pass
            finally:
                lock.release()

        return callback

    def _spawn_cameras(self):
        if not self.camera_enabled:
            return

        self.camera_output_dir.mkdir(parents=True, exist_ok=True)

        for station_id, station_cfg in sorted(self.station_configs.items()):
            if not station_cfg.camera_enabled:
                continue

            camera_cfg = self.camera_configs[station_id]
            bp = self._configure_camera_blueprint(camera_cfg)
            transform = self._camera_transform(camera_cfg)

            actor = None
            try:
                actor = self.adapter.world.spawn_actor(bp, transform)
                actor.listen(self._camera_callback(station_id))
                self.camera_actors[station_id] = actor
                self.camera_frame_counts[station_id] = 0
                print(
                    "[MONITORING] camera {} | placement={} | "
                    "xyz=({:.1f},{:.1f},{:.1f}) | {}x{} @ {:.1f}fps".format(
                        station_id,
                        camera_cfg.placement,
                        camera_cfg.x,
                        camera_cfg.y,
                        camera_cfg.z,
                        camera_cfg.image_width,
                        camera_cfg.image_height,
                        camera_cfg.target_fps,
                    )
                )
            except Exception as exc:
                if actor is not None and station_id not in self.camera_actors:
                    try:
                        actor.destroy()
                    except Exception:
                        pass
                # A camera failure is non-fatal. The station still supplies
                # traffic values from CARLA ground-truth snapshots.
                print(
                    "[MONITORING WARNING] camera {} not started: {}".format(
                        station_id,
                        exc,
                    )
                )

    def start(self):
        if self._started:
            return
        if self.adapter.world is None:
            raise RuntimeError("CarlaAdapter must be connected before MonitoringManager.start()")

        self._load_configs()
        self._register_stations()
        self._spawn_cameras()
        self._started = True
        self._closed = False

        print(
            "[MONITORING] started | stations={} | cameras={}/{} | "
            "telemetry={:.1f}Hz | station={:.1f}Hz".format(
                len(self.station_configs),
                len(self.camera_actors),
                len(self.station_configs) if self.camera_enabled else 0,
                1.0 / self.telemetry_interval_s,
                1.0 / self.station_interval_s,
            )
        )
        print(
            "[MONITORING] road_risk/visibility source=simulated_baseline; "
            "traffic/vehicle state source=CARLA"
        )

    def _persist_mobile(self, telemetry):
        records = [
            VehicleTelemetryRecord(
                timestamp_s=item.timestamp_s,
                vehicle_id=item.vehicle_id,
                x=item.x,
                y=item.y,
                z=item.z,
                speed_kmh=item.speed_kmh,
                road_id=item.road_id,
                lane_id=item.lane_id,
                healthy=item.healthy,
                available=item.available,
                business_state=item.business_state,
                current_task_id=item.current_task_id,
            )
            for item in telemetry
        ]
        self.database.insert_vehicle_telemetry_batch(records)

    def _persist_stations(self, observations):
        station_records = []
        road_records = []

        for item in observations:
            station_records.append(
                StationReadingRecord(
                    timestamp_s=item.timestamp_s,
                    station_id=item.station_id,
                    vehicle_count=item.vehicle_count,
                    avg_speed_kmh=item.avg_speed_kmh,
                    congestion_level=item.congestion_level,
                    road_risk=item.road_risk,
                    visibility=item.visibility,
                )
            )

            cost_multiplier = (
                1.0
                + 0.7 * float(item.road_congestion_level)
                + 1.3 * float(item.road_risk)
            )
            road_records.append(
                RoadStateRecord(
                    timestamp_s=item.timestamp_s,
                    road_id=item.road_id,
                    lane_id=item.lane_id,
                    open=True,
                    traffic_level=item.road_congestion_level,
                    risk_level=item.road_risk,
                    visibility=item.visibility,
                    cost_multiplier=round(cost_multiplier, 4),
                    source_station_id=item.station_id,
                )
            )

        self.database.insert_station_readings_batch(station_records)
        self.database.upsert_road_states_batch(road_records)

    def collect(
        self,
        timestamp_s,
        business_states: Optional[Dict[str, str]] = None,
        current_task_ids: Optional[Dict[str, Optional[str]]] = None,
    ):
        if not self._started or self._closed:
            return self.latest_snapshot

        timestamp_s = float(timestamp_s)
        need_mobile = timestamp_s >= self._next_telemetry_at
        need_station = timestamp_s >= self._next_station_at

        if not need_mobile and not need_station:
            return self.latest_snapshot

        snapshots = list(self.adapter.get_all_snapshots().values())

        vehicles = self.latest_snapshot.vehicles
        stations = self.latest_snapshot.stations

        if need_mobile:
            telemetry = self.mobile_collector.collect(
                timestamp_s,
                snapshots,
                business_states=business_states,
                current_task_ids=current_task_ids,
            )
            self._persist_mobile(telemetry)
            vehicles = {item.vehicle_id: item for item in telemetry}
            self._next_telemetry_at = timestamp_s + self.telemetry_interval_s

        if need_station:
            observations = []
            for station_id, observer in sorted(self.observers.items()):
                observations.append(
                    observer.observe(
                        timestamp_s,
                        snapshots,
                        camera_active=(station_id in self.camera_actors),
                        latest_frame_path=self.latest_frame_paths.get(station_id),
                    )
                )
            self._persist_stations(observations)
            stations = {item.station_id: item for item in observations}
            self._next_station_at = timestamp_s + self.station_interval_s

        self.latest_snapshot = MonitoringSnapshot(
            timestamp_s=timestamp_s,
            stations=stations,
            vehicles=vehicles,
        )
        return self.latest_snapshot

    def status_line(self):
        station_parts = []
        for station_id, item in sorted(self.latest_snapshot.stations.items()):
            station_parts.append(
                "{}:obs{} road{} v{:.1f} c{:.2f}".format(
                    station_id.replace("station_road_", "S"),
                    item.vehicle_count,
                    item.road_vehicle_count,
                    item.avg_speed_kmh,
                    item.congestion_level,
                )
            )
        return " | ".join(station_parts) if station_parts else "waiting"

    def close(self):
        if self._closed:
            return
        self._closed = True

        destroyed = 0
        for station_id, actor in list(self.camera_actors.items()):
            try:
                actor.stop()
            except Exception:
                pass
            try:
                actor.destroy()
                destroyed += 1
            except Exception:
                pass

        self.camera_actors.clear()
        print(
            "[MONITORING] stopped | destroyed camera sensors={}".format(
                destroyed
            )
        )
