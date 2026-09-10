# -*- coding: utf-8 -*-

from open_pit_competition.simulation.carla_adapter import CarlaAdapter
from open_pit_competition.simulation.vehicle_behavior import (
    BehaviorContext,
    DrivingDecision,
    DrivingState,
    VehicleSnapshot,
)


class FakeControl:
    def __init__(self):
        self.throttle = 0.4
        self.brake = 0.0
        self.hand_brake = False


class FakeActor:
    def __init__(self):
        self.control = None

    def apply_control(self, control):
        self.control = control


class FakePlanner:
    def __init__(self):
        self.speed = None
        self.run_count = 0

    def set_speed(self, speed):
        self.speed = float(speed)

    def run_step(self):
        self.run_count += 1
        return FakeControl()


class FakeAgent:
    def __init__(self, planner):
        self._local_planner = planner
        self.run_count = 0

    def run_step(self):
        self.run_count += 1
        raise AssertionError(
            "BasicAgent.run_step must not own safety in Closed Loop execution"
        )


class FakeBehavior:
    def __init__(self, decision):
        self.decision = decision

    def decide(self, ego, nearby_vehicles, context):
        return self.decision


def snapshot():
    return VehicleSnapshot(
        vehicle_id="truck_1",
        x=0.0,
        y=0.0,
        z=0.0,
        yaw_deg=0.0,
        speed_mps=2.0,
        road_id=18,
        lane_id=2,
    )


def make_adapter(decision):
    adapter = object.__new__(CarlaAdapter)
    actor = FakeActor()
    planner = FakePlanner()
    agent = FakeAgent(planner)

    adapter.world = object()
    adapter._actors = {"truck_1": actor}
    adapter._agents = {"truck_1": agent}
    adapter._cruise_speeds_kmh = {"truck_1": 14.0}
    adapter._active_route_ids = {"truck_1": "haul_to_dump_53_to_23"}
    adapter._active_route_end_xyz = {}
    adapter._active_route_total_waypoints = {}
    adapter._last_driving_decisions = {}
    adapter.behavior = FakeBehavior(decision)

    adapter._require_connected = lambda: None
    adapter._actor = lambda vehicle_id: actor
    adapter.get_vehicle_snapshot = lambda vehicle_id: snapshot()
    adapter._local_planner_for = lambda value: planner

    return adapter, actor, planner, agent


def test_step_vehicle_uses_local_planner_not_basic_agent():
    decision = DrivingDecision(
        state=DrivingState.CRUISE,
        target_speed_kmh=14.0,
        reason="no active safety constraint",
    )
    adapter, actor, planner, agent = make_adapter(decision)

    result = adapter.step_vehicle(
        "truck_1",
        BehaviorContext(cruise_speed_kmh=14.0),
    )

    assert result.state == DrivingState.CRUISE
    assert planner.run_count == 1
    assert planner.speed == 14.0
    assert agent.run_count == 0
    assert actor.control is not None


def test_vehicle_behavior_brake_still_overrides_local_planner():
    decision = DrivingDecision(
        state=DrivingState.YIELD,
        target_speed_kmh=0.0,
        reason="business hold",
        brake_override=0.7,
    )
    adapter, actor, planner, agent = make_adapter(decision)

    adapter.step_vehicle(
        "truck_1",
        BehaviorContext(
            cruise_speed_kmh=14.0,
            yield_required=True,
            yield_reason="business hold",
        ),
    )

    assert planner.run_count == 1
    assert agent.run_count == 0
    assert planner.speed == 0.0
    assert actor.control.throttle == 0.0
    assert actor.control.brake >= 0.7


def test_last_vehicle_behavior_decision_is_recorded():
    decision = DrivingDecision(
        state=DrivingState.CRUISE,
        target_speed_kmh=14.0,
        reason="no active safety constraint",
    )
    adapter, _, _, _ = make_adapter(decision)

    adapter.step_vehicle(
        "truck_1",
        BehaviorContext(cruise_speed_kmh=14.0),
    )

    stored = adapter._last_driving_decisions["truck_1"]
    assert stored.state == DrivingState.CRUISE
    assert stored.reason == "no active safety constraint"
