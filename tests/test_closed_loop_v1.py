# -*- coding: utf-8 -*-

from dataclasses import dataclass

from open_pit_competition.closed_loop.coordinator import (
    ClosedLoopConfig,
    ClosedLoopCoordinator,
)
from open_pit_competition.closed_loop.state_builder import ClosedLoopStateBuilder
from open_pit_competition.decision.models import (
    RoutePlan,
    TransportTask,
    VehicleState,
)
from open_pit_competition.monitoring.models import (
    MobileTelemetry,
    MonitoringSnapshot,
)


class FakePlanner:
    def __init__(self):
        self.haul = RoutePlan(
            route_id="haul_10_to_20",
            route_type="haul_to_dump",
            from_spawn_index=10,
            to_spawn_index=20,
            distance_m=100.0,
            estimated_time_s=20.0,
        )

    def reachable_haul_routes(self, min_distance_m=0.0, max_distance_m=None):
        return [self.haul]

    def plan_empty(self, from_spawn_index, loading_spawn_index):
        return RoutePlan(
            route_id="empty_{}_to_{}".format(from_spawn_index, loading_spawn_index),
            route_type="empty_to_loading",
            from_spawn_index=from_spawn_index,
            to_spawn_index=loading_spawn_index,
            distance_m=50.0,
            estimated_time_s=10.0,
        )

    def plan_haul(self, loading_spawn_index, dump_spawn_index):
        if (loading_spawn_index, dump_spawn_index) == (10, 20):
            return self.haul
        return None


class FakeDatabase:
    def __init__(self):
        self.tasks = {}
        self.assignments = []

    def initialize(self):
        pass

    def upsert_task(self, record):
        self.tasks[record.task_id] = record

    def insert_assignment(self, record):
        self.assignments.append(record)


class FakeRuntime:
    def __init__(self, vehicle_ids=("truck_1",)):
        self.fleet_config = {
            "vehicles": [
                {
                    "vehicle_id": vehicle_id,
                    "spawn_point_index": 1 + index,
                    "cruise_speed_kmh": 14.0,
                }
                for index, vehicle_id in enumerate(vehicle_ids)
            ]
        }
        self.spawned_ids = list(vehicle_ids)
        self.positions = {
            vehicle_id: [0.0, 0.0, 0.0]
            for vehicle_id in vehicle_ids
        }
        self.healthy = {vehicle_id: True for vehicle_id in vehicle_ids}
        self.available = {vehicle_id: True for vehicle_id in vehicle_ids}
        self.speed_kmh = {vehicle_id: 0.0 for vehicle_id in vehicle_ids}
        self.destinations = {}
        self.holds = {}
        self.spawn_xyz = {
            1: (0.0, 0.0, 0.0),
            2: (0.0, 0.0, 0.0),
            10: (10.0, 0.0, 0.0),
            20: (20.0, 0.0, 0.0),
        }

    def get_spawned_vehicle_ids(self):
        return list(self.spawned_ids)

    def get_vehicle_spec(self, vehicle_id):
        for item in self.fleet_config["vehicles"]:
            if item["vehicle_id"] == vehicle_id:
                return dict(item)
        raise KeyError(vehicle_id)

    def set_vehicle_business_hold(self, vehicle_id, hold, reason=""):
        self.holds[vehicle_id] = (bool(hold), reason)

    def command_vehicle_destination(self, vehicle_id, spawn_point_index):
        self.destinations[vehicle_id] = int(spawn_point_index)
        self.holds[vehicle_id] = (False, "")

    def get_spawn_point_xyz(self, spawn_point_index):
        return self.spawn_xyz[int(spawn_point_index)]

    def get_live_vehicle_telemetry(self, vehicle_id, timestamp_s):
        p = self.positions[vehicle_id]
        return MobileTelemetry(
            timestamp_s=timestamp_s,
            vehicle_id=vehicle_id,
            x=p[0],
            y=p[1],
            z=p[2],
            speed_kmh=self.speed_kmh[vehicle_id],
            road_id=None,
            lane_id=None,
            healthy=self.healthy[vehicle_id],
            available=self.available[vehicle_id],
        )


def snap(t, runtime):
    return MonitoringSnapshot(
        timestamp_s=t,
        vehicles={
            vehicle_id: runtime.get_live_vehicle_telemetry(vehicle_id, t)
            for vehicle_id in runtime.spawned_ids
        },
    )


def make_coordinator(runtime, task_count=1):
    config = ClosedLoopConfig({
        "decision_interval_s": 5.0,
        "observation_interval_s": 0.5,
        "arrival_radius_m": 1.5,
        "loading_duration_s": 4.0,
        "unloading_duration_s": 3.0,
        "task_count": task_count,
        "task_seed": 1,
        "task_release_interval_s": 0.0,
        "operating_areas_path": "/tmp/does-not-exist.json",
        "results_path": "/tmp/closed_loop_v1_test_summary.json",
    })
    return ClosedLoopCoordinator(
        runtime=runtime,
        config=config,
        route_planner=FakePlanner(),
        database=FakeDatabase(),
    )


def test_state_builder_ignores_stale_health_after_runtime_event():
    builder = ClosedLoopStateBuilder()
    states = {
        "truck_1": VehicleState("truck_1", 1, healthy=False, available=False)
    }
    tasks = {
        "t1": TransportTask("t1", 10, 20)
    }
    stale = MonitoringSnapshot(
        timestamp_s=4.0,
        vehicles={
            "truck_1": MobileTelemetry(
                timestamp_s=4.0,
                vehicle_id="truck_1",
                x=0,
                y=0,
                z=0,
                speed_kmh=0,
                road_id=None,
                lane_id=None,
                healthy=True,
                available=True,
            )
        },
    )

    world = builder.build(
        5.0,
        states,
        tasks,
        [],
        monitoring_snapshot=stale,
        min_vehicle_observation_time={"truck_1": 5.0},
    )

    assert world.vehicles[0].healthy is False
    assert world.vehicles[0].available is False


def test_closed_loop_full_business_lifecycle():
    runtime = FakeRuntime(("truck_1",))
    coordinator = make_coordinator(runtime)
    coordinator.start(0.0)

    assert runtime.destinations["truck_1"] == 10
    assert coordinator.executions["truck_1"].business_state == "TO_LOADING"

    runtime.positions["truck_1"] = [10.0, 0.0, 0.0]
    coordinator.tick(1.0, snap(1.0, runtime))
    assert coordinator.executions["truck_1"].business_state == "LOADING"

    # First stopped observation starts the loading clock.
    coordinator.tick(1.5, snap(1.5, runtime))
    coordinator.tick(5.6, snap(5.6, runtime))
    assert coordinator.executions["truck_1"].business_state == "TO_DUMP"
    assert runtime.destinations["truck_1"] == 20

    runtime.positions["truck_1"] = [20.0, 0.0, 0.0]
    coordinator.tick(6.2, snap(6.2, runtime))
    assert coordinator.executions["truck_1"].business_state == "UNLOADING"

    coordinator.tick(6.8, snap(6.8, runtime))
    coordinator.tick(9.9, snap(9.9, runtime))

    task = next(iter(coordinator.tasks.values()))
    assert task.status == "completed"
    assert coordinator.executions["truck_1"].business_state == "IDLE"
    assert coordinator.vehicle_states["truck_1"].current_task_id is None
    assert coordinator.metrics.completed_tasks == 1


@dataclass
class FakeEvent:
    event_type: str
    params: dict


def test_vehicle_failure_releases_and_reassigns_task():
    runtime = FakeRuntime(("truck_1", "truck_2"))
    coordinator = make_coordinator(runtime)
    coordinator.start(0.0)

    task = next(iter(coordinator.tasks.values()))
    assert coordinator.vehicle_states["truck_1"].current_task_id == task.task_id

    runtime.healthy["truck_1"] = False
    runtime.available["truck_1"] = False
    coordinator.handle_runtime_event(
        FakeEvent("vehicle_failure", {"vehicle_id": "truck_1"}),
        1.0,
    )
    coordinator.tick(1.0, snap(1.0, runtime))

    assert coordinator.vehicle_states["truck_1"].healthy is False
    assert coordinator.vehicle_states["truck_1"].current_task_id is None
    assert coordinator.vehicle_states["truck_2"].current_task_id == task.task_id
    assert coordinator.executions["truck_2"].business_state == "TO_LOADING"
    assert coordinator.metrics.vehicle_failures == 1
    assert coordinator.metrics.reschedules == 1
