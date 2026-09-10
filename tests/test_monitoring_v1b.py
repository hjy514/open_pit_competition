# -*- coding: utf-8 -*-

from dataclasses import dataclass

from open_pit_competition.monitoring.fixed_station import (
    FixedStationObserver,
    _congestion_level,
    simulated_environment_state,
)
from open_pit_competition.monitoring.mobile_collector import MobileCollector
from open_pit_competition.monitoring.models import FixedStationConfig


@dataclass
class Snapshot:
    vehicle_id: str
    x: float
    y: float
    z: float
    speed_mps: float
    road_id: int
    lane_id: int
    healthy: bool = True
    available: bool = True


def _station():
    return FixedStationConfig(
        station_id="station_road_01",
        road_id=18,
        lane_id=2,
        x=0.0,
        y=0.0,
        z=0.0,
        monitor_radius_m=80.0,
        observation_vertical_tolerance_m=20.0,
        camera_enabled=True,
    )


def test_station_observation_counts_nearby_area_but_keeps_exact_road_subset():
    observer = FixedStationObserver(_station())
    snapshots = [
        # exact monitored road
        Snapshot("truck_1", 10.0, 0.0, 0.0, 2.0, 18, 2),
        # adjacent lane, still physically observable
        Snapshot("truck_2", 20.0, 0.0, 0.0, 3.0, 18, 1),
        # outside radius
        Snapshot("truck_3", 100.0, 0.0, 0.0, 3.0, 18, 2),
        # nearby different road, still observable by station
        Snapshot("truck_4", 10.0, 0.0, 0.0, 3.0, 50, 1),
    ]

    reading = observer.observe(1.0, snapshots)

    assert reading.vehicle_count == 3
    assert reading.avg_speed_kmh == 9.6
    assert reading.road_vehicle_count == 1
    assert reading.road_avg_speed_kmh == 7.2


def test_vertical_tolerance_avoids_counting_other_mine_bench():
    observer = FixedStationObserver(_station())
    snapshots = [
        Snapshot("same_bench", 10.0, 0.0, 5.0, 2.0, 50, 1),
        Snapshot("other_bench", 10.0, 0.0, 30.0, 2.0, 50, 1),
    ]

    reading = observer.observe(1.0, snapshots)

    assert reading.vehicle_count == 1
    assert reading.road_vehicle_count == 0


def test_empty_station_has_zero_congestion():
    assert _congestion_level(0, 0.0) == 0.0


def test_slow_dense_traffic_has_more_congestion_than_one_fast_truck():
    fast = _congestion_level(1, 14.0)
    slow_dense = _congestion_level(3, 2.0)
    assert slow_dense > fast
    assert 0.0 <= fast <= 1.0
    assert 0.0 <= slow_dense <= 1.0


def test_simulated_environment_fields_are_bounded_and_deterministic():
    a = simulated_environment_state(12.5, station_index=2)
    b = simulated_environment_state(12.5, station_index=2)
    assert a == b
    assert 0.0 <= a[0] <= 1.0
    assert 0.0 <= a[1] <= 1.0


def test_mobile_collector_converts_speed_and_fault_state():
    snapshots = [
        Snapshot(
            "truck_4",
            1.0,
            2.0,
            3.0,
            5.0,
            18,
            2,
            healthy=False,
            available=False,
        )
    ]

    result = MobileCollector().collect(3.0, snapshots)

    assert len(result) == 1
    item = result[0]
    assert item.vehicle_id == "truck_4"
    assert item.speed_kmh == 18.0
    assert item.business_state == "FAULT"
    assert item.healthy is False
    assert item.available is False
