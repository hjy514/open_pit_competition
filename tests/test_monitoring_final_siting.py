# -*- coding: utf-8 -*-

from importlib.machinery import SourceFileLoader
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "finalize_monitoring_stations.py"
)

mod = SourceFileLoader(
    "finalize_monitoring_stations",
    str(SCRIPT),
).load_module()


def candidate(
    road_id,
    x,
    y,
    haul_ids,
    total_ids,
    lane_id=1,
    samples=20,
):
    return {
        "road_id": road_id,
        "lane_id": lane_id,
        "x": float(x),
        "y": float(y),
        "z": 0.0,
        "road_yaw_deg": 0.0,
        "matched_waypoint_count": samples,
        "haul_route_ids": list(haul_ids),
        "empty_route_ids": [],
        "route_ids": list(total_ids),
        "haul_route_coverage_count": len(haul_ids),
        "empty_route_coverage_count": 0,
        "route_coverage_count": len(total_ids),
    }


def test_distance_filter_rejects_near_duplicate():
    a = candidate(18, 0, 0, ["h1", "h2", "h3"], ["h1", "h2", "h3"])
    b = candidate(82, 80, 0, ["h1", "h2"], ["h1", "h2"])
    c = candidate(50, 250, 0, ["h4"], ["h4"])

    selected = mod.select_final_stations(
        [a, b, c],
        count=2,
        min_distance_m=150.0,
    )

    assert selected[0]["road_id"] == 18
    assert selected[1]["road_id"] == 50


def test_second_station_prefers_new_haul_coverage():
    a = candidate(
        10, 0, 0,
        ["h1", "h2", "h3", "h4"],
        ["h1", "h2", "h3", "h4"],
    )
    # Large absolute coverage but mostly duplicates A.
    b = candidate(
        20, 300, 0,
        ["h1", "h2", "h3"],
        ["h1", "h2", "h3", "e1", "e2"],
    )
    # Smaller absolute coverage but 2 new haul routes.
    c = candidate(
        30, 0, 300,
        ["h5", "h6"],
        ["h5", "h6"],
    )

    selected = mod.select_final_stations(
        [a, b, c],
        count=2,
        min_distance_m=150.0,
    )

    assert selected[0]["road_id"] == 10
    assert selected[1]["road_id"] == 30
    assert selected[1]["marginal_haul_route_count"] == 2


def test_three_stations_respect_minimum_distance():
    candidates = [
        candidate(1, 0, 0, ["h1", "h2"], ["h1", "h2"]),
        candidate(2, 100, 0, ["h3"], ["h3"]),
        candidate(3, 300, 0, ["h4"], ["h4"]),
        candidate(4, 0, 350, ["h5"], ["h5"]),
    ]

    selected = mod.select_final_stations(
        candidates,
        count=3,
        min_distance_m=150.0,
    )

    assert len(selected) == 3

    for i in range(len(selected)):
        for j in range(i + 1, len(selected)):
            assert (
                mod.horizontal_distance_xy(selected[i], selected[j])
                >= 150.0
            )


def test_first_station_uses_best_haul_coverage():
    a = candidate(1, 0, 0, ["h1"], ["h1", "e1", "e2", "e3"])
    b = candidate(2, 500, 0, ["h1", "h2", "h3"], ["h1", "h2", "h3"])

    selected = mod.select_final_stations(
        [a, b],
        count=1,
        min_distance_m=150.0,
    )

    assert selected[0]["road_id"] == 2
