# -*- coding: utf-8 -*-

from open_pit_competition.closed_loop.coordinator import ClosedLoopConfig, ClosedLoopCoordinator
from open_pit_competition.decision.models import RoutePlan
from open_pit_competition.decision.route_planner import MatrixRoutePlanner


class FakeDatabase:
    def initialize(self):
        pass
    def upsert_task(self, record):
        pass
    def insert_assignment(self, record):
        pass


class FakePlanner:
    sampling_resolution_m = 2.0
    def reachable_haul_routes(self, min_distance_m=0.0, max_distance_m=None):
        return []
    def plan_empty(self, from_spawn_index, loading_spawn_index):
        if int(from_spawn_index) == int(loading_spawn_index):
            return RoutePlan(
                route_id="zero",
                route_type="empty_to_loading",
                from_spawn_index=int(from_spawn_index),
                to_spawn_index=int(loading_spawn_index),
                distance_m=0.0,
                estimated_time_s=0.0,
            )
        return None
    def plan_haul(self, loading_spawn_index, dump_spawn_index):
        if (int(loading_spawn_index), int(dump_spawn_index)) == (53, 23):
            return RoutePlan(
                route_id="haul_to_dump_53_to_23",
                route_type="haul_to_dump",
                from_spawn_index=53,
                to_spawn_index=23,
                distance_m=98.821,
                estimated_time_s=25.411,
            )
        return None


class FakeScenario:
    duration_s = 180.0


class FakeRuntime:
    def __init__(self):
        self.scenario = FakeScenario()
        self.fleet_config = {
            "vehicles": [{
                "vehicle_id": "truck_1",
                "spawn_point_index": 53,
                "cruise_speed_kmh": 12.0,
            }]
        }
        self.holds = []
        self.route_commands = []
    def get_spawned_vehicle_ids(self):
        return ["truck_1"]
    def get_vehicle_spec(self, vehicle_id):
        return dict(self.fleet_config["vehicles"][0])
    def set_vehicle_business_hold(self, vehicle_id, hold, reason=""):
        self.holds.append((vehicle_id, bool(hold), reason))
    def command_vehicle_route(self, **kwargs):
        self.route_commands.append(dict(kwargs))
    def command_vehicle_destination(self, vehicle_id, spawn_point_index):
        raise AssertionError("V1.1 should not fall back to destination mode")


def test_matrix_planner_same_loading_point_is_zero_route(tmp_path):
    path = tmp_path / "matrix.json"
    path.write_text(
        """{
          "map_id": "0325_5",
          "sampling_resolution_m": 2.0,
          "reference_speed_kmh": 14.0,
          "loading_spawn_indices": [53],
          "dump_spawn_indices": [23],
          "routes": []
        }""",
        encoding="utf-8",
    )
    planner = MatrixRoutePlanner(str(path))
    route = planner.plan_empty(53, 53)
    assert route is not None
    assert route.distance_m == 0.0
    assert route.estimated_time_s == 0.0
    assert planner.sampling_resolution_m == 2.0


def test_execute_selected_haul_route_uses_runtime_route_boundary():
    runtime = FakeRuntime()
    config = ClosedLoopConfig({})
    coordinator = ClosedLoopCoordinator(
        runtime=runtime,
        config=config,
        route_planner=FakePlanner(),
        database=FakeDatabase(),
    )
    route = FakePlanner().plan_haul(53, 23)
    mode = coordinator._execute_route("truck_1", route)
    assert mode == "matrix_route"
    assert len(runtime.route_commands) == 1
    command = runtime.route_commands[0]
    assert command["route_id"] == "haul_to_dump_53_to_23"
    assert command["from_spawn_point_index"] == 53
    assert command["to_spawn_point_index"] == 23
    assert command["expected_distance_m"] == 98.821
    assert command["sampling_resolution_m"] == 2.0


def test_zero_empty_leg_is_held_in_place():
    runtime = FakeRuntime()
    config = ClosedLoopConfig({})
    coordinator = ClosedLoopCoordinator(
        runtime=runtime,
        config=config,
        route_planner=FakePlanner(),
        database=FakeDatabase(),
    )
    route = FakePlanner().plan_empty(53, 53)
    mode = coordinator._execute_route("truck_1", route)
    assert mode == "already_there"
    assert runtime.holds[-1][0] == "truck_1"
    assert runtime.holds[-1][1] is True
    assert runtime.route_commands == []
