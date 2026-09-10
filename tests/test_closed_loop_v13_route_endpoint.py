# -*- coding: utf-8 -*-

from open_pit_competition.closed_loop.coordinator import (
    ClosedLoopConfig,
    ClosedLoopCoordinator,
)
from open_pit_competition.monitoring.models import MobileTelemetry


class FakeRuntime:
    def __init__(
        self,
        final_gap_m,
        remaining_waypoints,
        route_id="haul_to_dump_53_to_23",
        done=False,
        spawn_gap_m=100.0,
    ):
        self.final_gap_m = float(final_gap_m)
        self.remaining_waypoints = int(remaining_waypoints)
        self.route_id = route_id
        self.done = bool(done)
        self.spawn_gap_m = float(spawn_gap_m)

    def get_spawn_point_xyz(self, spawn_index):
        return (0.0, 0.0, 0.0)

    def get_live_vehicle_telemetry(self, vehicle_id, timestamp_s):
        return MobileTelemetry(
            timestamp_s=timestamp_s,
            vehicle_id=vehicle_id,
            x=self.spawn_gap_m,
            y=0.0,
            z=0.0,
            speed_kmh=1.0,
            road_id=None,
            lane_id=None,
            healthy=True,
            available=True,
        )

    def get_vehicle_route_status(self, vehicle_id):
        return {
            "active": True,
            "route_id": self.route_id,
            "done": self.done,
            "remaining_waypoints": self.remaining_waypoints,
            "total_waypoints": 45,
            "final_gap_m": self.final_gap_m,
        }

    def is_vehicle_route_complete(self, vehicle_id):
        return self.done


def make_coordinator(runtime):
    config = ClosedLoopConfig({
        "arrival_radius_m": 10.0,
        "route_endpoint_arrival_radius_m": 12.0,
        "route_endpoint_remaining_waypoints_max": 8,
        "route_complete_acceptance_radius_m": 35.0,
    })
    coordinator = object.__new__(ClosedLoopCoordinator)
    coordinator.runtime = runtime
    coordinator.config = config
    coordinator._last_time_s = 30.0
    coordinator._vehicle_event_times = {}
    coordinator._route_done_gap_warned = set()
    coordinator._route_progress_last_log_s = {}
    return coordinator


def test_near_selected_route_endpoint_is_arrival_even_if_basic_agent_not_done():
    coordinator = make_coordinator(
        FakeRuntime(final_gap_m=9.0, remaining_waypoints=4, done=False)
    )
    arrived, _ = coordinator._arrived(
        "truck_1", 23, None,
        expected_route_id="haul_to_dump_53_to_23",
    )
    assert arrived is True


def test_near_endpoint_is_not_arrival_when_many_waypoints_remain():
    coordinator = make_coordinator(
        FakeRuntime(final_gap_m=9.0, remaining_waypoints=30, done=False)
    )
    arrived, _ = coordinator._arrived(
        "truck_1", 23, None,
        expected_route_id="haul_to_dump_53_to_23",
    )
    assert arrived is False


def test_wrong_active_route_cannot_complete_task():
    coordinator = make_coordinator(
        FakeRuntime(
            final_gap_m=5.0,
            remaining_waypoints=1,
            route_id="different_route",
            done=False,
        )
    )
    arrived, _ = coordinator._arrived(
        "truck_1", 23, None,
        expected_route_id="haul_to_dump_53_to_23",
    )
    assert arrived is False
