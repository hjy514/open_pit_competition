# -*- coding: utf-8 -*-

from importlib.machinery import SourceFileLoader
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "analyze_monitoring_routes.py"
)
mod = SourceFileLoader("analyze_monitoring_routes", str(SCRIPT)).load_module()


def sample_matrix():
    return {
        "schema_version": "1.0-decision-route-matrix",
        "map_id": "0325_5",
        "routes": [
            {
                "route_id": "haul_a",
                "route_type": "haul_to_dump",
                "reachable": True,
                "road_lane_sequence": [
                    {"road_id": 10, "lane_id": -1},
                    {"road_id": 20, "lane_id": -1},
                    {"road_id": 30, "lane_id": -1},
                ],
            },
            {
                "route_id": "haul_b",
                "route_type": "haul_to_dump",
                "reachable": True,
                "road_lane_sequence": [
                    {"road_id": 10, "lane_id": -1},
                    {"road_id": 20, "lane_id": -1},
                ],
            },
            {
                "route_id": "empty_a",
                "route_type": "empty_to_loading",
                "reachable": True,
                "road_lane_sequence": [
                    {"road_id": 10, "lane_id": -1},
                    {"road_id": 40, "lane_id": 1},
                ],
            },
        ],
    }


def test_analysis_counts_unique_route_coverage():
    ranked, total = mod.analyze_routes(sample_matrix())
    assert total == 3

    road10 = next(
        x for x in ranked if x["road_id"] == 10 and x["lane_id"] == -1
    )
    assert road10["route_coverage_count"] == 3
    assert road10["haul_route_coverage_count"] == 2
    assert road10["empty_route_coverage_count"] == 1


def test_ranking_prefers_haul_coverage():
    ranked, _ = mod.analyze_routes(sample_matrix())
    assert ranked[0]["road_id"] == 10
    assert ranked[0]["haul_route_coverage_count"] == 2


def test_selection_prefers_distinct_roads():
    ranked, _ = mod.analyze_routes(sample_matrix())
    selected = mod.select_candidates(ranked, 3)
    assert len(selected) == 3
    assert len({x["road_id"] for x in selected}) == 3
