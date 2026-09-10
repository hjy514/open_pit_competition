# -*- coding: utf-8 -*-
"""Closed Loop V1 coordinator.

MVP flow:
Monitoring/Runtime state -> WorldState -> GreedyScheduler -> Assignment
-> Runtime destination command -> loading/unloading lifecycle -> feedback.

Architecture boundaries:
- Decision never calls CARLA.
- Closed Loop calls only Runtime-facing execution methods.
- SQLite is persistence/history only; it is not the live decision bus.
- VehicleBehavior remains the low-level safety authority.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Dict, Optional

from open_pit_competition.decision.models import (
    OperatingPoint,
    TransportTask,
    VehicleState,
)
from open_pit_competition.decision.replanner import DecisionReplanner
from open_pit_competition.decision.route_planner import MatrixRoutePlanner
from open_pit_competition.decision.scheduler import GreedyScheduler
from open_pit_competition.storage.database import OpenPitDatabase
from open_pit_competition.storage.models import AssignmentRecord, TaskRecord

from .evaluator import ClosedLoopEvaluator
from .metrics import ClosedLoopMetrics
from .models import TaskRuntimeMeta, VehicleExecutionState
from .state_builder import ClosedLoopStateBuilder


class ClosedLoopConfig:
    def __init__(self, data=None):
        data = dict(data or {})
        self.decision_interval_s = float(data.get("decision_interval_s", 5.0))
        self.observation_interval_s = float(data.get("observation_interval_s", 0.5))
        self.arrival_radius_m = float(data.get("arrival_radius_m", 12.0))
        self.service_stop_speed_mps = float(
            data.get("service_stop_speed_mps", 0.5)
        )
        self.loading_duration_s = float(data.get("loading_duration_s", 4.0))
        self.unloading_duration_s = float(data.get("unloading_duration_s", 3.0))
        self.task_count = int(data.get("task_count", 8))
        self.task_seed = int(data.get("task_seed", 20260910))
        self.task_release_interval_s = float(
            data.get("task_release_interval_s", 0.0)
        )
        self.task_templates = list(data.get("task_templates", []))
        self.prefer_initial_loading_origins = bool(
            data.get("prefer_initial_loading_origins", True)
        )
        self.min_haul_distance_m = float(data.get("min_haul_distance_m", 0.0))
        max_distance = data.get("max_haul_distance_m", 450.0)
        self.max_haul_distance_m = (
            None if max_distance is None else float(max_distance)
        )
        self.route_matrix_path = str(
            data.get("route_matrix_path", "configs/decision_route_matrix.json")
        )
        self.operating_areas_path = str(
            data.get("operating_areas_path", "configs/operating_areas.json")
        )
        self.database_path = str(
            data.get("database_path", "runtime_data/database/open_pit.db")
        )
        self.results_path = str(
            data.get(
                "results_path",
                "runtime_data/results/closed_loop_v1_summary.json",
            )
        )
        self.route_distance_tolerance_ratio = float(
            data.get("route_distance_tolerance_ratio", 0.08)
        )
        self.route_start_tolerance_m = float(
            data.get("route_start_tolerance_m", 30.0)
        )
        self.route_skip_ahead_waypoints = int(
            data.get("route_skip_ahead_waypoints", 2)
        )
        self.route_complete_acceptance_radius_m = float(
            data.get("route_complete_acceptance_radius_m", 35.0)
        )
        self.route_endpoint_arrival_radius_m = float(
            data.get("route_endpoint_arrival_radius_m", 12.0)
        )
        self.route_endpoint_remaining_waypoints_max = int(
            data.get("route_endpoint_remaining_waypoints_max", 8)
        )
        self.stall_recovery_enabled = bool(
            data.get("stall_recovery_enabled", True)
        )
        self.stall_speed_threshold_kmh = float(
            data.get("stall_speed_threshold_kmh", 0.8)
        )
        self.stall_timeout_s = float(
            data.get("stall_timeout_s", 8.0)
        )
        self.stall_recovery_cooldown_s = float(
            data.get("stall_recovery_cooldown_s", 8.0)
        )
        self.stall_max_recoveries_per_leg = int(
            data.get("stall_max_recoveries_per_leg", 4)
        )
        self.stall_recovery_forward_m = float(
            data.get("stall_recovery_forward_m", 18.0)
        )
        self.stall_recovery_z_offset_m = float(
            data.get("stall_recovery_z_offset_m", 0.5)
        )
        self.stall_recovery_clearance_m = float(
            data.get("stall_recovery_clearance_m", 12.0)
        )
        self.stall_recovery_max_extra_forward_m = float(
            data.get("stall_recovery_max_extra_forward_m", 30.0)
        )

    @classmethod
    def from_path(cls, path):
        with Path(path).open("r", encoding="utf-8") as f:
            return cls(json.load(f))


def _distance_xyz(a, b):
    return math.sqrt(
        (float(a[0]) - float(b[0])) ** 2
        + (float(a[1]) - float(b[1])) ** 2
        + (float(a[2]) - float(b[2])) ** 2
    )


class ClosedLoopCoordinator:
    def __init__(
        self,
        runtime,
        config: ClosedLoopConfig,
        route_planner=None,
        scheduler=None,
        replanner=None,
        database=None,
        evaluator=None,
    ):
        self.runtime = runtime
        self.config = config

        self.route_planner = route_planner or MatrixRoutePlanner(
            config.route_matrix_path
        )
        self.scheduler = scheduler or GreedyScheduler(self.route_planner)
        self.replanner = replanner or DecisionReplanner()
        self.database = database or OpenPitDatabase(config.database_path)
        self.evaluator = evaluator or ClosedLoopEvaluator()
        self.state_builder = ClosedLoopStateBuilder()

        self.vehicle_states: Dict[str, VehicleState] = {}
        self.executions: Dict[str, VehicleExecutionState] = {}
        self.tasks: Dict[str, TransportTask] = {}
        self.task_meta: Dict[str, TaskRuntimeMeta] = {}
        self.operating_points = []

        self.metrics = ClosedLoopMetrics()
        self._released_tasks = set()
        self._vehicle_event_times: Dict[str, float] = {}
        self._next_decision_at = 0.0
        self._next_observation_at = 0.0
        self._decision_due = True
        self._started = False
        self._last_time_s = 0.0
        self._route_done_gap_warned = set()
        self._route_progress_last_log_s = {}
        self._stall_watch = {}

    # ------------------------------------------------------------------
    # Startup / task generation
    # ------------------------------------------------------------------
    def _load_operating_points(self):
        path = Path(self.config.operating_areas_path)
        if not path.exists():
            return []

        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        points = []
        for area in data.get("areas", []):
            area_type = str(area.get("area_type", ""))
            if area_type not in ("haul_loading", "haul_dump"):
                continue

            point_type = "loading" if area_type == "haul_loading" else "dump"
            for spawn_index in area.get("point_spawn_indices", []):
                idx = int(spawn_index)
                points.append(
                    OperatingPoint(
                        point_id="{}_{}".format(point_type, idx),
                        point_type=point_type,
                        spawn_index=idx,
                    )
                )
        return points

    def _generate_tasks(self):
        if self.config.task_templates:
            self._generate_configured_tasks()
            return

        routes = self.route_planner.reachable_haul_routes(
            min_distance_m=self.config.min_haul_distance_m,
            max_distance_m=self.config.max_haul_distance_m,
        )
        if not routes:
            routes = self.route_planner.reachable_haul_routes()
        if not routes:
            raise RuntimeError("Closed Loop found no reachable haul routes")

        initial_origins = {
            int(item["spawn_point_index"])
            for item in self.runtime.fleet_config.get("vehicles", [])
        }
        local_routes = [
            route for route in routes
            if route.from_spawn_index in initial_origins
        ]
        if self.config.prefer_initial_loading_origins and local_routes:
            routes = local_routes

        rng = random.Random(self.config.task_seed)
        chosen = []
        by_origin = {}
        for route in routes:
            by_origin.setdefault(route.from_spawn_index, []).append(route)

        if self.config.prefer_initial_loading_origins and local_routes:
            for origin in sorted(by_origin):
                if len(chosen) >= self.config.task_count:
                    break
                chosen.append(rng.choice(by_origin[origin]))

        remaining = [route for route in routes if route not in chosen]
        rng.shuffle(remaining)
        chosen.extend(remaining[:max(0, self.config.task_count - len(chosen))])

        while len(chosen) < self.config.task_count:
            chosen.append(routes[rng.randrange(len(routes))])

        for index, route in enumerate(chosen[:self.config.task_count], start=1):
            task_id = "cl_task_{:03d}".format(index)
            release_time = (index - 1) * self.config.task_release_interval_s
            task = TransportTask(
                task_id=task_id,
                origin_spawn_index=route.from_spawn_index,
                destination_spawn_index=route.to_spawn_index,
                release_time_s=release_time,
                priority=rng.randint(1, 3),
                status="pending",
            )
            self.tasks[task_id] = task
            self.task_meta[task_id] = TaskRuntimeMeta(
                task_id=task_id,
                created_at_s=0.0,
            )

        self.metrics.generated_tasks = len(self.tasks)

    def _generate_configured_tasks(self):
        for index, item in enumerate(self.config.task_templates, start=1):
            origin = int(item["origin_spawn_index"])
            destination = int(item["destination_spawn_index"])
            route = self.route_planner.plan_haul(origin, destination)
            if route is None:
                raise RuntimeError(
                    "Configured Closed Loop task {} has no haul route {}->{}".format(
                        item.get("task_id", index), origin, destination
                    )
                )

            task_id = str(item.get("task_id", "cl_task_{:03d}".format(index)))
            task = TransportTask(
                task_id=task_id,
                origin_spawn_index=origin,
                destination_spawn_index=destination,
                release_time_s=float(item.get("release_time_s", 0.0)),
                priority=int(item.get("priority", 1)),
                status="pending",
            )
            self.tasks[task_id] = task
            self.task_meta[task_id] = TaskRuntimeMeta(
                task_id=task_id,
                created_at_s=0.0,
            )

        self.metrics.generated_tasks = len(self.tasks)

    def _execute_route(self, vehicle_id, route_plan):
        """Ask Runtime to execute the exact Decision-selected OD contract."""

        if route_plan.distance_m <= 1e-6:
            self.runtime.set_vehicle_business_hold(
                vehicle_id,
                True,
                "already at selected loading point",
            )
            return "already_there"

        command = getattr(self.runtime, "command_vehicle_route", None)
        if callable(command):
            command(
                vehicle_id=vehicle_id,
                route_id=route_plan.route_id,
                from_spawn_point_index=route_plan.from_spawn_index,
                to_spawn_point_index=route_plan.to_spawn_index,
                expected_distance_m=route_plan.distance_m,
                sampling_resolution_m=self.route_planner.sampling_resolution_m,
                distance_tolerance_ratio=self.config.route_distance_tolerance_ratio,
                route_start_tolerance_m=self.config.route_start_tolerance_m,
                skip_ahead_waypoints=self.config.route_skip_ahead_waypoints,
            )
            return "matrix_route"

        self.runtime.command_vehicle_destination(
            vehicle_id,
            route_plan.to_spawn_index,
        )
        return "destination_fallback"

    def start(self, current_time_s=0.0):
        if self._started:
            return

        self.database.initialize()
        self.operating_points = self._load_operating_points()
        self._generate_tasks()

        for vehicle_id in self.runtime.get_spawned_vehicle_ids():
            self.on_vehicle_spawned(vehicle_id, current_time_s)

        for task in self.tasks.values():
            self._persist_task(task)

        self._started = True
        self._last_time_s = float(current_time_s)

        print(
            "[CLOSED_LOOP] started | tasks={} | decision={:.1f}s | "
            "observe={:.1f}s | load={:.1f}s | unload={:.1f}s".format(
                len(self.tasks),
                self.config.decision_interval_s,
                self.config.observation_interval_s,
                self.config.loading_duration_s,
                self.config.unloading_duration_s,
            )
        )

        self.tick(current_time_s)

    def on_vehicle_spawned(self, vehicle_id, current_time_s):
        vehicle_id = str(vehicle_id)
        if vehicle_id in self.vehicle_states:
            return

        spec = self.runtime.get_vehicle_spec(vehicle_id)
        spawn_index = int(spec["spawn_point_index"])

        self.vehicle_states[vehicle_id] = VehicleState(
            vehicle_id=vehicle_id,
            current_spawn_index=spawn_index,
            available=True,
            healthy=True,
            current_task_id=None,
        )
        self.executions[vehicle_id] = VehicleExecutionState(
            vehicle_id=vehicle_id,
            business_state="IDLE",
            state_since_s=float(current_time_s),
        )

        # A newly spawned spare CAT must not continue along the scenario's
        # fallback destination while Decision is deciding its business task.
        self.runtime.set_vehicle_business_hold(
            vehicle_id,
            True,
            "closed-loop waiting assignment",
        )
        self._decision_due = True
        print(
            "[CLOSED_LOOP] vehicle ready | {} | logical_spawn={}".format(
                vehicle_id,
                spawn_index,
            )
        )

    # ------------------------------------------------------------------
    # Live WorldState / Decision
    # ------------------------------------------------------------------
    def _world_state(self, current_time_s, monitoring_snapshot=None):
        return self.state_builder.build(
            current_time_s=current_time_s,
            vehicle_states=self.vehicle_states,
            tasks=self.tasks,
            operating_points=self.operating_points,
            monitoring_snapshot=monitoring_snapshot,
            min_vehicle_observation_time=self._vehicle_event_times,
        )

    def _run_decision(self, current_time_s, monitoring_snapshot=None):
        world_state = self._world_state(current_time_s, monitoring_snapshot)
        assignments = self.scheduler.schedule(world_state)
        if not assignments:
            return 0

        self.replanner.apply_assignments(world_state, assignments)

        applied = 0
        for assignment in assignments:
            vehicle = self.vehicle_states.get(assignment.vehicle_id)
            task = self.tasks.get(assignment.task_id)
            execution = self.executions.get(assignment.vehicle_id)

            if vehicle is None or task is None or execution is None:
                continue

            meta = self.task_meta[task.task_id]
            if meta.assignment_count > 0 or task.task_id in self._released_tasks:
                self.metrics.reschedules += 1
                self._released_tasks.discard(task.task_id)

            meta.assignment_count += 1
            meta.assigned_vehicle_id = vehicle.vehicle_id
            if meta.started_at_s is None:
                meta.started_at_s = float(current_time_s)

            execution.assignment = assignment
            execution.business_state = "TO_LOADING"
            execution.target_spawn_index = task.origin_spawn_index
            execution.state_since_s = float(current_time_s)
            execution.service_started_at_s = None

            route_mode = self._execute_route(
                vehicle.vehicle_id,
                assignment.empty_route,
            )

            if route_mode == "already_there":
                self._enter_loading(
                    vehicle.vehicle_id,
                    current_time_s,
                )

            self.metrics.assignments += 1
            self.database.insert_assignment(
                AssignmentRecord(
                    timestamp_s=float(current_time_s),
                    vehicle_id=vehicle.vehicle_id,
                    task_id=task.task_id,
                    empty_route_id=assignment.empty_route.route_id,
                    haul_route_id=assignment.haul_route.route_id,
                    score=assignment.score,
                    reason=assignment.reason,
                )
            )
            self._persist_task(task)
            applied += 1

            print(
                "[CLOSED_LOOP] ASSIGN | {} -> {} | loading={} dump={} | "
                "empty={:.1f}m/{:.1f}s | haul={:.1f}m/{:.1f}s | "
                "mode={} | score={:.1f}".format(
                    vehicle.vehicle_id,
                    task.task_id,
                    task.origin_spawn_index,
                    task.destination_spawn_index,
                    assignment.empty_route.distance_m,
                    assignment.empty_route.estimated_time_s,
                    assignment.haul_route.distance_m,
                    assignment.haul_route.estimated_time_s,
                    route_mode,
                    assignment.score,
                )
            )

            scenario = getattr(self.runtime, "scenario", None)
            duration_s = getattr(scenario, "duration_s", None)
            if duration_s is not None:
                remaining = max(0.0, float(duration_s) - float(current_time_s))
                if (
                    route_mode != "already_there"
                    and assignment.empty_route.estimated_time_s > remaining
                ):
                    print(
                        "[CLOSED_LOOP WARNING] {} empty-route ETA {:.1f}s "
                        "exceeds scenario remaining {:.1f}s; no LOADING is "
                        "expected before scenario end.".format(
                            vehicle.vehicle_id,
                            assignment.empty_route.estimated_time_s,
                            remaining,
                        )
                    )

        return applied

    # ------------------------------------------------------------------
    # Business lifecycle
    # ------------------------------------------------------------------
    def _telemetry_for(self, vehicle_id, monitoring_snapshot):
        if monitoring_snapshot is not None:
            telemetry = monitoring_snapshot.vehicles.get(vehicle_id)
            if telemetry is not None:
                minimum = float(self._vehicle_event_times.get(vehicle_id, -1.0))
                if float(telemetry.timestamp_s) + 1e-9 >= minimum:
                    return telemetry

        # Monitoring is optional. Runtime remains the execution boundary.
        return self.runtime.get_live_vehicle_telemetry(vehicle_id, self._last_time_s)

    def _arrived(
        self,
        vehicle_id,
        spawn_index,
        monitoring_snapshot,
        expected_route_id=None,
    ):
        telemetry = self._telemetry_for(vehicle_id, monitoring_snapshot)
        target = self.runtime.get_spawn_point_xyz(spawn_index)
        position = (telemetry.x, telemetry.y, telemetry.z)
        raw_spawn_gap_m = _distance_xyz(position, target)

        if raw_spawn_gap_m <= self.config.arrival_radius_m:
            return True, telemetry

        route_status_fn = getattr(
            self.runtime,
            "get_vehicle_route_status",
            None,
        )
        route_status = (
            route_status_fn(vehicle_id)
            if callable(route_status_fn)
            else None
        )

        if route_status:
            active_route_id = route_status.get("route_id")
            route_matches = (
                expected_route_id is None
                or active_route_id == expected_route_id
            )
            final_gap_m = route_status.get("final_gap_m")
            remaining = route_status.get("remaining_waypoints")
            done = bool(route_status.get("done", False))

            if (
                route_matches
                and final_gap_m is not None
                and remaining is not None
                and float(final_gap_m)
                    <= self.config.route_endpoint_arrival_radius_m
                and int(remaining)
                    <= self.config.route_endpoint_remaining_waypoints_max
            ):
                print(
                    "[CLOSED_LOOP] ARRIVAL | {} | target={} | "
                    "mode=route_endpoint | endpoint_gap={:.1f}m | "
                    "remaining_wp={}".format(
                        vehicle_id,
                        spawn_index,
                        float(final_gap_m),
                        int(remaining),
                    )
                )
                return True, telemetry

            if (
                route_matches
                and done
                and raw_spawn_gap_m
                    <= self.config.route_complete_acceptance_radius_m
            ):
                print(
                    "[CLOSED_LOOP] ARRIVAL | {} | target={} | "
                    "mode=route_done | spawn_gap={:.1f}m".format(
                        vehicle_id,
                        spawn_index,
                        raw_spawn_gap_m,
                    )
                )
                return True, telemetry

            now_s = float(self._last_time_s)
            last_log_s = float(
                self._route_progress_last_log_s.get(vehicle_id, -1e9)
            )
            if now_s - last_log_s >= 15.0:
                self._route_progress_last_log_s[vehicle_id] = now_s
                print(
                    "[CLOSED_LOOP ROUTE] {} | route={} | speed={:.1f}km/h | "
                    "remaining_wp={} | endpoint_gap={}m | spawn_gap={:.1f}m | "
                    "done={} | behavior={} | reason={}".format(
                        vehicle_id,
                        active_route_id,
                        float(telemetry.speed_kmh),
                        remaining if remaining is not None else "-",
                        (
                            "{:.1f}".format(float(final_gap_m))
                            if final_gap_m is not None
                            else "-"
                        ),
                        raw_spawn_gap_m,
                        done,
                        route_status.get("behavior_state") or "-",
                        route_status.get("behavior_reason") or "-",
                    )
                )

        # Preserve the V1.2 compatibility path for Runtime/test doubles that
        # do not expose route-status details yet.
        done_fn = getattr(
            self.runtime,
            "is_vehicle_route_complete",
            None,
        )
        route_done = (
            bool(done_fn(vehicle_id))
            if callable(done_fn)
            else False
        )
        if (
            route_done
            and raw_spawn_gap_m
                <= self.config.route_complete_acceptance_radius_m
        ):
            print(
                "[CLOSED_LOOP] ARRIVAL | {} | target={} | "
                "mode=route_done | spawn_gap={:.1f}m".format(
                    vehicle_id,
                    spawn_index,
                    raw_spawn_gap_m,
                )
            )
            return True, telemetry

        return False, telemetry


    def _reset_stall_watch(self, vehicle_id):
        self._stall_watch.pop(
            vehicle_id,
            None,
        )


    def _maybe_recover_stalled_route(
        self,
        vehicle_id,
        current_time_s,
        expected_route_id,
        telemetry,
    ):
        """Recover only a genuine physical stall while safety says DRIVE."""

        if not self.config.stall_recovery_enabled:
            return False

        status_fn = getattr(
            self.runtime,
            "get_vehicle_route_status",
            None,
        )
        recover_fn = getattr(
            self.runtime,
            "recover_stalled_vehicle_route",
            None,
        )

        if not callable(status_fn) or not callable(recover_fn):
            return False

        status = status_fn(vehicle_id) or {}
        route_id = status.get("route_id")
        remaining = status.get("remaining_waypoints")
        behavior = str(
            status.get("behavior_state") or ""
        ).lower()

        if (
            not route_id
            or route_id != expected_route_id
            or remaining is None
        ):
            self._reset_stall_watch(vehicle_id)
            return False

        remaining = int(remaining)
        now_s = float(current_time_s)

        watch = self._stall_watch.get(vehicle_id)
        if (
            watch is None
            or watch.get("route_id") != route_id
        ):
            self._stall_watch[vehicle_id] = {
                "route_id": route_id,
                "remaining_wp": remaining,
                "last_progress_s": now_s,
                "last_recovery_s": -1e9,
                "recoveries": 0,
            }
            return False

        previous_remaining = int(
            watch.get(
                "remaining_wp",
                remaining,
            )
        )

        # Any waypoint consumption is real route progress.
        if remaining < previous_remaining:
            watch["remaining_wp"] = remaining
            watch["last_progress_s"] = now_s
            return False

        # Route re-attachment can make the exposed queue larger again.
        if remaining > previous_remaining:
            watch["remaining_wp"] = remaining
            watch["last_progress_s"] = now_s
            return False

        # Never teleport while VehicleBehavior is intentionally protecting
        # the CAT. Only CRUISE/RESUME means "the project wants to drive".
        if behavior not in ("cruise", "resume"):
            watch["last_progress_s"] = now_s
            return False

        if float(telemetry.speed_kmh) > self.config.stall_speed_threshold_kmh:
            return False

        # Close to route completion: let normal arrival handling own it.
        if remaining <= self.config.route_endpoint_remaining_waypoints_max:
            return False

        stalled_for_s = now_s - float(
            watch.get(
                "last_progress_s",
                now_s,
            )
        )
        if stalled_for_s < self.config.stall_timeout_s:
            return False

        since_recovery_s = now_s - float(
            watch.get(
                "last_recovery_s",
                -1e9,
            )
        )
        if since_recovery_s < self.config.stall_recovery_cooldown_s:
            return False

        recoveries = int(
            watch.get(
                "recoveries",
                0,
            )
        )
        if recoveries >= self.config.stall_max_recoveries_per_leg:
            if not watch.get("limit_warned"):
                watch["limit_warned"] = True
                print(
                    "[CLOSED_LOOP WARNING] {} stall recovery limit reached "
                    "| route={} | remaining_wp={}".format(
                        vehicle_id,
                        route_id,
                        remaining,
                    )
                )
            return False

        try:
            result = recover_fn(
                vehicle_id=vehicle_id,
                forward_distance_m=self.config.stall_recovery_forward_m,
                z_offset_m=self.config.stall_recovery_z_offset_m,
                clearance_m=self.config.stall_recovery_clearance_m,
                max_extra_forward_m=(
                    self.config.stall_recovery_max_extra_forward_m
                ),
            )
        except Exception as exc:
            # Do not kill the whole six-CAT runtime because one recovery
            # attempt failed. Retry only after the normal cooldown.
            watch["last_recovery_s"] = now_s
            print(
                "[CLOSED_LOOP WARNING] stall recovery failed | {} | "
                "route={} | {}".format(
                    vehicle_id,
                    route_id,
                    exc,
                )
            )
            return False

        watch["recoveries"] = recoveries + 1
        watch["last_recovery_s"] = now_s
        watch["last_progress_s"] = now_s
        watch["remaining_wp"] = remaining

        print(
            "[CLOSED_LOOP RECOVERY] {} | route={} | stalled={:.1f}s | "
            "remaining_wp={} | recovery={}/{} | shift={:.1f}m".format(
                vehicle_id,
                route_id,
                stalled_for_s,
                remaining,
                watch["recoveries"],
                self.config.stall_max_recoveries_per_leg,
                float(result.get("shift_m", 0.0)),
            )
        )
        return True


    def _enter_loading(self, vehicle_id, current_time_s):
        self._reset_stall_watch(vehicle_id)
        execution = self.executions[vehicle_id]
        task = self.tasks[execution.assignment.task_id]

        execution.business_state = "LOADING"
        execution.target_spawn_index = task.origin_spawn_index
        execution.state_since_s = float(current_time_s)
        execution.service_started_at_s = None
        self.vehicle_states[vehicle_id].current_spawn_index = (
            task.origin_spawn_index
        )
        task.status = "loading"

        self.runtime.set_vehicle_business_hold(
            vehicle_id,
            True,
            "closed-loop loading",
        )
        self._persist_task(task)
        print(
            "[CLOSED_LOOP] LOADING | {} | task={} | point={}".format(
                vehicle_id,
                task.task_id,
                task.origin_spawn_index,
            )
        )

    def _start_haul(self, vehicle_id, current_time_s):
        self._reset_stall_watch(vehicle_id)
        execution = self.executions[vehicle_id]
        task = self.tasks[execution.assignment.task_id]

        execution.business_state = "TO_DUMP"
        execution.target_spawn_index = task.destination_spawn_index
        execution.state_since_s = float(current_time_s)
        execution.service_started_at_s = None
        task.status = "to_dump"

        route_mode = self._execute_route(
            vehicle_id,
            execution.assignment.haul_route,
        )
        self._persist_task(task)
        print(
            "[CLOSED_LOOP] HAUL | {} | task={} | dump={} | "
            "route={} | {:.1f}m/{:.1f}s | mode={}".format(
                vehicle_id,
                task.task_id,
                task.destination_spawn_index,
                execution.assignment.haul_route.route_id,
                execution.assignment.haul_route.distance_m,
                execution.assignment.haul_route.estimated_time_s,
                route_mode,
            )
        )

    def _enter_unloading(self, vehicle_id, current_time_s):
        self._reset_stall_watch(vehicle_id)
        execution = self.executions[vehicle_id]
        task = self.tasks[execution.assignment.task_id]

        execution.business_state = "UNLOADING"
        execution.target_spawn_index = task.destination_spawn_index
        execution.state_since_s = float(current_time_s)
        execution.service_started_at_s = None
        self.vehicle_states[vehicle_id].current_spawn_index = (
            task.destination_spawn_index
        )
        task.status = "unloading"

        self.runtime.set_vehicle_business_hold(
            vehicle_id,
            True,
            "closed-loop unloading",
        )
        self._persist_task(task)
        print(
            "[CLOSED_LOOP] UNLOADING | {} | task={} | point={}".format(
                vehicle_id,
                task.task_id,
                task.destination_spawn_index,
            )
        )

    def _complete_task(self, vehicle_id, current_time_s):
        self._reset_stall_watch(vehicle_id)
        execution = self.executions[vehicle_id]
        assignment = execution.assignment
        task = self.tasks[assignment.task_id]
        vehicle = self.vehicle_states[vehicle_id]
        meta = self.task_meta[task.task_id]

        task.status = "completed"
        meta.completed_at_s = float(current_time_s)
        meta.assigned_vehicle_id = vehicle_id

        vehicle.current_task_id = None
        vehicle.available = True

        execution.business_state = "IDLE"
        execution.assignment = None
        execution.target_spawn_index = None
        execution.state_since_s = float(current_time_s)
        execution.service_started_at_s = None

        self.runtime.set_vehicle_business_hold(
            vehicle_id,
            True,
            "closed-loop task complete; waiting assignment",
        )

        self.metrics.completed_tasks += 1
        self._persist_task(task)
        self._decision_due = True

        print(
            "[CLOSED_LOOP] COMPLETED | {} | task={} | completed={}/{}".format(
                vehicle_id,
                task.task_id,
                self.metrics.completed_tasks,
                self.metrics.generated_tasks,
            )
        )

    def _advance_vehicle(self, vehicle_id, current_time_s, monitoring_snapshot):
        vehicle = self.vehicle_states[vehicle_id]
        execution = self.executions[vehicle_id]

        if not vehicle.healthy or not vehicle.available:
            return

        state = execution.business_state

        if state == "TO_LOADING":
            arrived, _telemetry = self._arrived(
                vehicle_id,
                execution.target_spawn_index,
                monitoring_snapshot,
                expected_route_id=(
                    execution.assignment.empty_route.route_id
                    if execution.assignment is not None
                    else None
                ),
            )
            if arrived:
                self._enter_loading(vehicle_id, current_time_s)
            else:
                self._maybe_recover_stalled_route(
                    vehicle_id,
                    current_time_s,
                    (
                        execution.assignment.empty_route.route_id
                        if execution.assignment is not None
                        else None
                    ),
                    _telemetry,
                )
            return

        if state == "TO_DUMP":
            arrived, _telemetry = self._arrived(
                vehicle_id,
                execution.target_spawn_index,
                monitoring_snapshot,
                expected_route_id=(
                    execution.assignment.haul_route.route_id
                    if execution.assignment is not None
                    else None
                ),
            )
            if arrived:
                self._enter_unloading(vehicle_id, current_time_s)
            else:
                self._maybe_recover_stalled_route(
                    vehicle_id,
                    current_time_s,
                    (
                        execution.assignment.haul_route.route_id
                        if execution.assignment is not None
                        else None
                    ),
                    _telemetry,
                )
            return

        if state not in ("LOADING", "UNLOADING"):
            return

        telemetry = self._telemetry_for(vehicle_id, monitoring_snapshot)

        # Service time starts only after the large CAT has actually stopped.
        if execution.service_started_at_s is None:
            if (
                float(telemetry.speed_kmh) / 3.6
                <= self.config.service_stop_speed_mps
            ):
                execution.service_started_at_s = float(current_time_s)
            return

        elapsed_service = (
            float(current_time_s) - execution.service_started_at_s
        )

        if state == "LOADING" and elapsed_service >= self.config.loading_duration_s:
            self._start_haul(vehicle_id, current_time_s)
        elif (
            state == "UNLOADING"
            and elapsed_service >= self.config.unloading_duration_s
        ):
            self._complete_task(vehicle_id, current_time_s)

    # ------------------------------------------------------------------
    # Runtime events / dynamic replanning
    # ------------------------------------------------------------------
    def handle_runtime_event(self, event, current_time_s):
        event_type = str(event.event_type)
        current_time_s = float(current_time_s)

        if event_type == "vehicle_failure":
            vehicle_id = str(event.params["vehicle_id"])
            if vehicle_id not in self.vehicle_states:
                return

            world_state = self._world_state(current_time_s)
            released_task_id = self.replanner.fail_vehicle(
                world_state,
                vehicle_id,
            )

            execution = self.executions[vehicle_id]
            execution.business_state = "FAULT"
            execution.assignment = None
            execution.target_spawn_index = None
            execution.state_since_s = current_time_s
            execution.service_started_at_s = None
            self._reset_stall_watch(vehicle_id)
            self.runtime.set_vehicle_business_hold(
                vehicle_id,
                True,
                "closed-loop vehicle fault",
            )

            self.metrics.vehicle_failures += 1
            self._vehicle_event_times[vehicle_id] = current_time_s

            if released_task_id is not None:
                self._released_tasks.add(released_task_id)
                meta = self.task_meta[released_task_id]
                meta.assigned_vehicle_id = None
                self._persist_task(self.tasks[released_task_id])
                print(
                    "[CLOSED_LOOP] RELEASE | task={} from failed {}".format(
                        released_task_id,
                        vehicle_id,
                    )
                )

            self._decision_due = True
            return

        if event_type == "vehicle_recovery":
            vehicle_id = str(event.params["vehicle_id"])
            if vehicle_id not in self.vehicle_states:
                return

            world_state = self._world_state(current_time_s)
            self.replanner.recover_vehicle(world_state, vehicle_id)

            execution = self.executions[vehicle_id]
            execution.business_state = "IDLE"
            execution.assignment = None
            execution.target_spawn_index = None
            execution.state_since_s = current_time_s
            execution.service_started_at_s = None
            self._reset_stall_watch(vehicle_id)
            self.runtime.set_vehicle_business_hold(
                vehicle_id,
                True,
                "closed-loop recovered; waiting assignment",
            )
            self._vehicle_event_times[vehicle_id] = current_time_s
            self._decision_due = True

            print("[CLOSED_LOOP] RECOVERED | {}".format(vehicle_id))
            return

        if event_type in ("road_closure", "road_reopen"):
            # Runtime / VehicleBehavior owns the physical hold/resume.
            # V1's route matrix has one route per endpoint pair, therefore
            # Closed Loop V1 records the event but does not invent an
            # alternate route that the Decision layer does not actually have.
            self._decision_due = True

    # ------------------------------------------------------------------
    # Tick / persistence / status
    # ------------------------------------------------------------------
    def tick(self, current_time_s, monitoring_snapshot=None):
        if not self._started:
            return

        current_time_s = float(current_time_s)
        self._last_time_s = current_time_s

        for vehicle_id in self.runtime.get_spawned_vehicle_ids():
            if vehicle_id not in self.vehicle_states:
                self.on_vehicle_spawned(vehicle_id, current_time_s)

        observe_due = current_time_s + 1e-9 >= self._next_observation_at
        if observe_due:
            self._world_state(current_time_s, monitoring_snapshot)
            for vehicle_id in list(self.executions):
                self._advance_vehicle(
                    vehicle_id,
                    current_time_s,
                    monitoring_snapshot,
                )
            self._next_observation_at = (
                current_time_s + self.config.observation_interval_s
            )

        if self._decision_due or current_time_s + 1e-9 >= self._next_decision_at:
            self._run_decision(current_time_s, monitoring_snapshot)
            self._decision_due = False
            self._next_decision_at = (
                current_time_s + self.config.decision_interval_s
            )

    def business_states(self):
        return {
            vehicle_id: item.business_state
            for vehicle_id, item in self.executions.items()
        }

    def current_task_ids(self):
        return {
            vehicle_id: self.vehicle_states[vehicle_id].current_task_id
            for vehicle_id in self.executions
        }

    def status_line(self):
        counts = {}
        for item in self.executions.values():
            counts[item.business_state] = counts.get(item.business_state, 0) + 1

        state_text = ",".join(
            "{}={}".format(key, counts[key])
            for key in sorted(counts)
        ) or "waiting"

        pending = sum(1 for task in self.tasks.values() if task.status == "pending")
        active = sum(
            1
            for task in self.tasks.values()
            if task.status not in ("pending", "completed")
        )
        completed = sum(
            1 for task in self.tasks.values() if task.status == "completed"
        )
        return "{} | tasks P/A/C={}/{}/{}".format(
            state_text,
            pending,
            active,
            completed,
        )

    def _persist_task(self, task):
        meta = self.task_meta[task.task_id]
        status = str(task.status).upper()
        self.database.upsert_task(
            TaskRecord(
                task_id=task.task_id,
                origin_spawn_index=task.origin_spawn_index,
                destination_spawn_index=task.destination_spawn_index,
                priority=task.priority,
                release_time_s=task.release_time_s,
                status=status,
                assigned_vehicle_id=meta.assigned_vehicle_id,
                created_at_s=meta.created_at_s,
                started_at_s=meta.started_at_s,
                completed_at_s=meta.completed_at_s,
            )
        )

    def close(self, current_time_s=None):
        if not self._started:
            return None

        if current_time_s is None:
            current_time_s = self._last_time_s

        summary = self.evaluator.write(
            self,
            current_time_s=float(current_time_s),
            output_path=self.config.results_path,
        )
        self._started = False

        print(
            "[CLOSED_LOOP] summary | generated={} completed={} "
            "pending={} completion_rate={:.1%} assignments={} reschedules={}".format(
                summary["generated_tasks"],
                summary["completed_tasks"],
                summary["pending_tasks"],
                summary["completion_rate"],
                summary["assignments"],
                summary["reschedules"],
            )
        )
        print("[CLOSED_LOOP] results -> {}".format(self.config.results_path))
        return summary
