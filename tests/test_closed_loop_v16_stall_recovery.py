# -*- coding: utf-8 -*-

from types import SimpleNamespace

from open_pit_competition.closed_loop.coordinator import (
    ClosedLoopConfig,
    ClosedLoopCoordinator,
)
from open_pit_competition.simulation.carla_adapter import CarlaAdapter


class FakeRuntime:
    def __init__(self):
        self.remaining = 30
        self.behavior = "cruise"
        self.recoveries = []

    def get_vehicle_route_status(self, vehicle_id):
        return {
            "route_id": "haul_to_dump_53_to_23",
            "remaining_waypoints": self.remaining,
            "behavior_state": self.behavior,
        }

    def recover_stalled_vehicle_route(self, **kwargs):
        self.recoveries.append(kwargs)
        return {"shift_m": 18.0}


def make_coordinator(runtime):
    coordinator = object.__new__(ClosedLoopCoordinator)
    coordinator.runtime = runtime
    coordinator.config = ClosedLoopConfig({
        "stall_recovery_enabled": True,
        "stall_speed_threshold_kmh": 0.8,
        "stall_timeout_s": 8.0,
        "stall_recovery_cooldown_s": 8.0,
        "stall_max_recoveries_per_leg": 4,
        "stall_recovery_forward_m": 18.0,
        "stall_recovery_z_offset_m": 0.5,
        "stall_recovery_clearance_m": 12.0,
        "stall_recovery_max_extra_forward_m": 30.0,
        "route_endpoint_remaining_waypoints_max": 8,
    })
    coordinator._stall_watch = {}
    return coordinator


def telemetry(speed_kmh):
    return SimpleNamespace(speed_kmh=float(speed_kmh))


def test_route_forward_index_uses_distance_not_fixed_waypoint_count():
    class Location:
        def __init__(self, x):
            self.x = x
            self.y = 0.0
            self.z = 0.0

    class Waypoint:
        def __init__(self, x):
            self.transform = SimpleNamespace(location=Location(x))

    route = [(Waypoint(x), None) for x in (0.0, 2.0, 5.0, 9.0, 14.0, 20.0)]

    assert CarlaAdapter._route_forward_index(
        route,
        start_index=1,
        forward_distance_m=10.0,
    ) == 4


def test_stall_watch_recovers_after_timeout_when_behavior_is_cruise():
    runtime = FakeRuntime()
    coordinator = make_coordinator(runtime)

    assert coordinator._maybe_recover_stalled_route(
        "truck_1",
        0.0,
        "haul_to_dump_53_to_23",
        telemetry(0.0),
    ) is False

    assert coordinator._maybe_recover_stalled_route(
        "truck_1",
        9.0,
        "haul_to_dump_53_to_23",
        telemetry(0.1),
    ) is True

    assert len(runtime.recoveries) == 1
    assert runtime.recoveries[0]["forward_distance_m"] == 18.0


def test_real_waypoint_progress_resets_stall_timer():
    runtime = FakeRuntime()
    coordinator = make_coordinator(runtime)

    coordinator._maybe_recover_stalled_route(
        "truck_1",
        0.0,
        "haul_to_dump_53_to_23",
        telemetry(0.0),
    )

    runtime.remaining = 25
    assert coordinator._maybe_recover_stalled_route(
        "truck_1",
        7.0,
        "haul_to_dump_53_to_23",
        telemetry(0.1),
    ) is False

    assert coordinator._maybe_recover_stalled_route(
        "truck_1",
        12.0,
        "haul_to_dump_53_to_23",
        telemetry(0.1),
    ) is False

    assert runtime.recoveries == []


def test_safety_stop_never_triggers_teleport_recovery():
    runtime = FakeRuntime()
    runtime.behavior = "wait_front"
    coordinator = make_coordinator(runtime)

    coordinator._maybe_recover_stalled_route(
        "truck_1",
        0.0,
        "haul_to_dump_53_to_23",
        telemetry(0.0),
    )

    assert coordinator._maybe_recover_stalled_route(
        "truck_1",
        30.0,
        "haul_to_dump_53_to_23",
        telemetry(0.0),
    ) is False

    assert runtime.recoveries == []
