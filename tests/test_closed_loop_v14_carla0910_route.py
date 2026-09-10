# -*- coding: utf-8 -*-

from collections import deque

from open_pit_competition.simulation.carla_adapter import CarlaAdapter
from open_pit_competition.simulation.vehicle_behavior import VehicleSnapshot


def snap(vehicle_id, road_id, lane_id):
    return VehicleSnapshot(
        vehicle_id=vehicle_id,
        x=0.0,
        y=0.0,
        z=0.0,
        yaw_deg=0.0,
        speed_mps=0.0,
        road_id=road_id,
        lane_id=lane_id,
    )


def test_same_current_road_lane_true():
    assert CarlaAdapter._same_current_road_lane(
        snap("a", 18, 2),
        snap("b", 18, 2),
    )


def test_same_current_road_lane_false_for_different_road():
    assert not CarlaAdapter._same_current_road_lane(
        snap("a", 18, 2),
        snap("b", 82, 1),
    )


def test_same_current_road_lane_false_when_map_ids_missing():
    assert not CarlaAdapter._same_current_road_lane(
        snap("a", None, None),
        snap("b", 18, 2),
    )
