from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .carla_adapter import CarlaAdapter, CarlaAdapterError
from .events import EventQueue, RuntimeEvent
from .scenario import ScenarioConfig, load_scenario
from .vehicle_behavior import BehaviorContext


def _load_json(path: str) -> Dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def _distance_xy(x1: float, y1: float, x2: float, y2: float) -> float:
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


class SimulationRuntime:
    """Formal Simulation-layer runtime.

    Responsibilities:
    - load one Scenario;
    - create the configured CAT mine-truck fleet;
    - drive CARLA through CarlaAdapter;
    - supply VehicleBehavior contexts;
    - execute scheduled Scenario events;
    - terminate the scenario cleanly.

    S01 intentionally contains no abnormal events. It is the baseline
    used to prove the common runtime before S02/S07 add disturbances.
    """

    def __init__(
        self,
        scenario: ScenarioConfig,
        fleet_config: Dict[str, Any],
        map_config: Dict[str, Any],
        system_config: Dict[str, Any],
        monitoring_enabled: bool = False,
        monitoring_camera_enabled: bool = True,
        monitoring_stations_path: str = "configs/monitoring_stations.json",
        monitoring_camera_layout_path: str = "configs/monitoring_camera_layout.json",
        monitoring_database_path: str = "runtime_data/database/open_pit.db",
    ):
        self.scenario = scenario
        self.fleet_config = fleet_config
        self.map_config = map_config
        self.system_config = system_config

        self.vehicles: List[Dict[str, Any]] = list(
            fleet_config.get("vehicles", [])
        )
        if not self.vehicles:
            raise ValueError("fleet.json must contain a non-empty vehicles list")

        if scenario.initial_spawn_count < 1:
            raise ValueError("initial_spawn_count must be >= 1")

        if scenario.initial_spawn_count > len(self.vehicles):
            raise ValueError(
                "initial_spawn_count cannot exceed fleet size"
            )

        self.control_period_s = float(
            system_config.get("control_period_s", 0.05)
        )

        self.adapter = CarlaAdapter(
            carla_root=str(system_config["carla_root"]),
            host=str(system_config.get("host", "127.0.0.1")),
            port=int(system_config.get("port", 2000)),
            timeout_seconds=float(
                system_config.get("timeout_seconds", 20.0)
            ),
            map_name=str(map_config["map_name"]),
            load_map=bool(map_config.get("load_map", False)),
        )

        self.event_queue = EventQueue(scenario.events)

        self.spawned_ids: List[str] = []
        self.spawn_times: Dict[str, float] = {}
        self.contexts: Dict[str, BehaviorContext] = {}

        self._next_spawn_index = scenario.initial_spawn_count
        self._start_time: Optional[float] = None
        self._next_spawn_retry_at = 0.0
        self._spawn_retry_interval_s = float(
            system_config.get("spawn_retry_interval_s", 1.0)
        )

        # Simulation-layer state for the currently assigned haul route.
        # S07 toggles this state. VehicleBehavior only consumes road_open;
        # it does not own scenario/event logic.
        self.route_open = True

        # Monitoring is observation-only and optional.  It is deliberately
        # fail-open: a sensor/database failure must never stop CAT control.
        self.monitoring_enabled = bool(monitoring_enabled)
        self.monitoring_camera_enabled = bool(monitoring_camera_enabled)
        self.monitoring_stations_path = str(monitoring_stations_path)
        self.monitoring_camera_layout_path = str(monitoring_camera_layout_path)
        self.monitoring_database_path = str(monitoring_database_path)
        self.monitoring = None
        self._monitoring_failure_reported = False

    def _vehicle_id(self, spec: Dict[str, Any]) -> str:
        return str(spec["vehicle_id"])

    def _blueprint_id(self, spec: Dict[str, Any]) -> str:
        return str(
            spec.get(
                "blueprint_id",
                self.fleet_config.get(
                    "blueprint_id",
                    "vehicle.cat.cat",
                ),
            )
        )

    def _spawn_vehicle(
        self,
        spec: Dict[str, Any],
        elapsed_seconds: float,
    ) -> None:
        vehicle_id = self._vehicle_id(spec)
        speed_kmh = float(spec["cruise_speed_kmh"])
        spawn_index = int(spec["spawn_point_index"])

        self.adapter.spawn_vehicle(
            vehicle_id=vehicle_id,
            spawn_point_index=spawn_index,
            blueprint_id=self._blueprint_id(spec),
            role_name=vehicle_id,
        )

        self.adapter.set_destination_spawn_point(
            vehicle_id=vehicle_id,
            spawn_point_index=self.scenario.destination_spawn_index,
            target_speed_kmh=speed_kmh,
        )

        self.contexts[vehicle_id] = BehaviorContext(
            cruise_speed_kmh=speed_kmh,
            road_open=self.route_open,
        )

        self.spawned_ids.append(vehicle_id)
        self.spawn_times[vehicle_id] = elapsed_seconds

        print(
            "[RUNTIME] spawned {} | spawn={} | destination={} | "
            "speed={:.1f} km/h | blueprint={}".format(
                vehicle_id,
                spawn_index,
                self.scenario.destination_spawn_index,
                speed_kmh,
                self._blueprint_id(spec),
            )
        )

    def _spawn_initial_fleet(self) -> None:
        count = self.scenario.initial_spawn_count

        for spec in self.vehicles[:count]:
            self._spawn_vehicle(spec, elapsed_seconds=0.0)
            time.sleep(0.25)

    def _try_spawn_next_vehicle(self, elapsed_seconds: float) -> None:
        if self._next_spawn_index >= len(self.vehicles):
            return

        # A reusable CARLA spawn point can remain temporarily occupied
        # even after the previous truck has moved beyond our release
        # distance.  Do not abort the whole scenario for that transient
        # condition; retry after a short delay.
        if elapsed_seconds < self._next_spawn_retry_at:
            return

        previous_spec = self.vehicles[self._next_spawn_index - 1]
        previous_id = self._vehicle_id(previous_spec)

        if previous_id not in self.spawned_ids:
            return

        reusable_spawn_index = int(
            self.map_config["rear_release_spawn_index"]
        )

        spawn_points = self.adapter.world.get_map().get_spawn_points()
        rear_location = spawn_points[reusable_spawn_index].location

        previous_snapshot = self.adapter.get_vehicle_snapshot(previous_id)

        clearance = _distance_xy(
            rear_location.x,
            rear_location.y,
            previous_snapshot.x,
            previous_snapshot.y,
        )

        if clearance < self.scenario.spawn_clearance_m:
            return

        spec = self.vehicles[self._next_spawn_index]
        vehicle_id = self._vehicle_id(spec)

        print(
            "[RUNTIME] release condition met | {} cleared rear spawn "
            "by {:.1f} m".format(previous_id, clearance)
        )

        try:
            self._spawn_vehicle(spec, elapsed_seconds)
        except CarlaAdapterError as exc:
            # Only a physical spawn-point occupancy failure is treated
            # as retryable. Other adapter errors still surface normally.
            if "Failed to spawn" not in str(exc):
                raise

            self._next_spawn_retry_at = (
                elapsed_seconds + self._spawn_retry_interval_s
            )

            print(
                "[RUNTIME] spawn deferred | {} | retry in {:.1f}s | {}".format(
                    vehicle_id,
                    self._spawn_retry_interval_s,
                    exc,
                )
            )
            return

        self._next_spawn_retry_at = 0.0
        self._next_spawn_index += 1

    def _handle_event(self, event: RuntimeEvent) -> None:
        """Common event entry point.

        S01 has no events. S02/S07 will extend this method using the
        already validated adapter/behavior operations.
        """
        print(
            "[EVENT] type={} at={:.1f}s params={}".format(
                event.event_type,
                event.at_seconds,
                event.params,
            )
        )

        if event.event_type == "vehicle_failure":
            vehicle_id = str(event.params["vehicle_id"])
            self.adapter.set_vehicle_operational(
                vehicle_id,
                healthy=False,
                available=False,
            )
            return

        if event.event_type == "vehicle_recovery":
            vehicle_id = str(event.params["vehicle_id"])
            self.adapter.set_vehicle_operational(
                vehicle_id,
                healthy=True,
                available=True,
            )
            return

        if event.event_type == "road_closure":
            self.route_open = False
            for context in self.contexts.values():
                context.road_open = False
            print(
                "[EVENT] road closure applied | route_open=False | "
                "affected={}".format(len(self.contexts))
            )
            return

        if event.event_type == "road_reopen":
            self.route_open = True
            for context in self.contexts.values():
                context.road_open = True
            print(
                "[EVENT] road reopen applied | route_open=True | "
                "affected={}".format(len(self.contexts))
            )
            return

        raise ValueError(
            "unsupported runtime event type: {}".format(
                event.event_type
            )
        )

    def _step_active_vehicles(self) -> None:
        for vehicle_id in list(self.spawned_ids):
            self.adapter.step_vehicle(
                vehicle_id,
                context=self.contexts[vehicle_id],
            )

    def _start_monitoring(self) -> None:
        if not self.monitoring_enabled:
            return

        manager = None
        try:
            # Lazy import keeps the Simulation layer independent when
            # monitoring is disabled.
            from open_pit_competition.monitoring.manager import MonitoringManager

            manager = MonitoringManager(
                adapter=self.adapter,
                stations_path=self.monitoring_stations_path,
                camera_layout_path=self.monitoring_camera_layout_path,
                database_path=self.monitoring_database_path,
                camera_enabled=self.monitoring_camera_enabled,
                telemetry_interval_s=0.5,
                station_interval_s=1.0,
            )
            manager.start()
            self.monitoring = manager
        except Exception as exc:
            # Observation must never be a hard dependency of vehicle motion.
            print(
                "[MONITORING WARNING] startup failed; vehicle runtime continues: {}".format(
                    exc
                )
            )
            if manager is not None:
                try:
                    manager.close()
                except Exception:
                    pass
            self.monitoring = None

    def _collect_monitoring(self, elapsed_seconds: float) -> None:
        if self.monitoring is None:
            return

        try:
            self.monitoring.collect(elapsed_seconds)
        except Exception as exc:
            if not self._monitoring_failure_reported:
                self._monitoring_failure_reported = True
                print(
                    "[MONITORING WARNING] collection failed; monitoring disabled "
                    "for this run, vehicle control continues: {}".format(exc)
                )
            try:
                self.monitoring.close()
            except Exception:
                pass
            self.monitoring = None

    def run(self) -> None:
        print("=" * 78)
        print(
            "SCENARIO {} | {}".format(
                self.scenario.scenario_id,
                self.scenario.name,
            )
        )
        print("=" * 78)
        print(self.scenario.description)
        print(
            "fleet={} | blueprint={} | map={} | duration={:.1f}s".format(
                len(self.vehicles),
                self.fleet_config.get(
                    "blueprint_id",
                    "vehicle.cat.cat",
                ),
                self.map_config["map_name"],
                self.scenario.duration_s,
            )
        )
        print()

        self.adapter.connect()
        self._spawn_initial_fleet()
        self._start_monitoring()

        self._start_time = time.monotonic()
        last_status_time = -1e9

        try:
            while True:
                now = time.monotonic()
                elapsed = now - self._start_time

                if elapsed >= self.scenario.duration_s:
                    print(
                        "[RUNTIME] scenario duration reached: {:.1f}s".format(
                            elapsed
                        )
                    )
                    break

                self._try_spawn_next_vehicle(elapsed)

                for event in self.event_queue.pop_due(elapsed):
                    self._handle_event(event)

                self._step_active_vehicles()
                self._collect_monitoring(elapsed)

                if elapsed - last_status_time >= 5.0:
                    last_status_time = elapsed
                    print(
                        "[RUNTIME] {:6.1f}s | active={}/{} | route_open={} | "
                        "spawned={}".format(
                            elapsed,
                            len(self.spawned_ids),
                            len(self.vehicles),
                            self.route_open,
                            ",".join(self.spawned_ids),
                        )
                    )
                    if self.monitoring is not None:
                        print(
                            "[MONITORING] {}".format(
                                self.monitoring.status_line()
                            )
                        )

                time.sleep(self.control_period_s)

        finally:
            self._cleanup()

    def _cleanup(self) -> None:
        # Destroy camera sensors before CARLA vehicle cleanup.  Monitoring
        # owns only its sensor actors; CarlaAdapter still owns only vehicles.
        if self.monitoring is not None:
            try:
                self.monitoring.close()
            except Exception as exc:
                print("[CLEANUP WARNING] monitoring.close:", exc)
            self.monitoring = None

        try:
            self.adapter.close()
        except Exception as exc:
            print("[CLEANUP WARNING] adapter.close:", exc)

        try:
            destroyed = self.adapter.destroy_spawned_vehicles()
            print(
                "[CLEANUP] destroyed controlled vehicles: {}".format(
                    destroyed
                )
            )
        except Exception as exc:
            print(
                "[CLEANUP WARNING] destroy_spawned_vehicles:",
                exc,
            )

        print()
        print("=" * 78)
        print("SCENARIO SUMMARY")
        print("=" * 78)
        print("scenario :", self.scenario.scenario_id)
        print(
            "spawned  : {}/{}".format(
                len(self.spawned_ids),
                len(self.vehicles),
            )
        )
        for vehicle_id in self.spawned_ids:
            print(
                "  {:8} at {:.1f}s".format(
                    vehicle_id,
                    self.spawn_times[vehicle_id],
                )
            )
        print("=" * 78)


def build_runtime(
    scenario_path: str,
    fleet_path: str,
    map_path: str,
    system_path: str,
    monitoring_enabled: bool = False,
    monitoring_camera_enabled: bool = True,
    monitoring_stations_path: str = "configs/monitoring_stations.json",
    monitoring_camera_layout_path: str = "configs/monitoring_camera_layout.json",
    monitoring_database_path: str = "runtime_data/database/open_pit.db",
) -> SimulationRuntime:
    return SimulationRuntime(
        scenario=load_scenario(scenario_path),
        fleet_config=_load_json(fleet_path),
        map_config=_load_json(map_path),
        system_config=_load_json(system_path),
        monitoring_enabled=monitoring_enabled,
        monitoring_camera_enabled=monitoring_camera_enabled,
        monitoring_stations_path=monitoring_stations_path,
        monitoring_camera_layout_path=monitoring_camera_layout_path,
        monitoring_database_path=monitoring_database_path,
    )


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--scenario",
        default="configs/scenarios/s01_normal.json",
    )
    parser.add_argument(
        "--fleet",
        default="configs/fleet.json",
    )
    parser.add_argument(
        "--map-config",
        default="configs/map.json",
    )
    parser.add_argument(
        "--system",
        default="configs/system.json",
    )
    parser.add_argument(
        "--monitoring",
        action="store_true",
        help="Enable observation-only fixed-station and CAT telemetry monitoring",
    )
    parser.add_argument(
        "--monitoring-no-cameras",
        action="store_true",
        help="Collect monitoring data without spawning RGB sensor actors",
    )
    parser.add_argument(
        "--monitoring-stations",
        default="configs/monitoring_stations.json",
    )
    parser.add_argument(
        "--monitoring-cameras",
        default="configs/monitoring_camera_layout.json",
    )
    parser.add_argument(
        "--monitoring-db",
        default="runtime_data/database/open_pit.db",
    )

    args = parser.parse_args()

    runtime = build_runtime(
        scenario_path=args.scenario,
        fleet_path=args.fleet,
        map_path=args.map_config,
        system_path=args.system,
        monitoring_enabled=args.monitoring,
        monitoring_camera_enabled=(not args.monitoring_no_cameras),
        monitoring_stations_path=args.monitoring_stations,
        monitoring_camera_layout_path=args.monitoring_cameras,
        monitoring_database_path=args.monitoring_db,
    )

    runtime.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
