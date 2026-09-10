# -*- coding: utf-8 -*-

from open_pit_competition.closed_loop.coordinator import (
    ClosedLoopConfig,
    ClosedLoopCoordinator,
)
from open_pit_competition.monitoring.models import MobileTelemetry


class FakeDatabase:
    pass


class FakeRuntime:
    def __init__(self, gap_m, done):
        self.gap_m = float(gap_m)
        self.done = bool(done)

    def get_spawn_point_xyz(self, spawn_index):
        return (0.0, 0.0, 0.0)

    def get_live_vehicle_telemetry(self, vehicle_id, timestamp_s):
        return MobileTelemetry(
            timestamp_s=timestamp_s,
            vehicle_id=vehicle_id,
            x=self.gap_m,
            y=0.0,
            z=0.0,
            speed_kmh=0.0,
            road_id=None,
            lane_id=None,
            healthy=True,
            available=True,
        )

    def is_vehicle_route_complete(self, vehicle_id):
        return self.done


def make_coordinator(runtime):
    config = ClosedLoopConfig({
        "arrival_radius_m": 10.0,
        "route_complete_acceptance_radius_m": 35.0,
    })
    coordinator = object.__new__(ClosedLoopCoordinator)
    coordinator.runtime = runtime
    coordinator.config = config
    coordinator._last_time_s = 0.0
    coordinator._vehicle_event_times = {}
    coordinator._route_done_gap_warned = set()
    return coordinator


def test_geometric_arrival_still_works():
    coordinator = make_coordinator(FakeRuntime(gap_m=8.0, done=False))
    arrived, _ = coordinator._arrived("truck_1", 23, None)
    assert arrived is True


def test_route_done_accepts_near_projected_endpoint():
    coordinator = make_coordinator(FakeRuntime(gap_m=22.0, done=True))
    arrived, _ = coordinator._arrived("truck_1", 23, None)
    assert arrived is True


def test_route_done_does_not_accept_far_endpoint():
    coordinator = make_coordinator(FakeRuntime(gap_m=80.0, done=True))
    arrived, _ = coordinator._arrived("truck_1", 23, None)
    assert arrived is False
