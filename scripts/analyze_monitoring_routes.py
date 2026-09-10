#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Monitoring V1A: choose fixed-monitoring road/lane candidates from the
Decision route matrix.

This is route-driven placement, not arbitrary station placement.

Input:
    configs/decision_route_matrix.json

Output:
    configs/monitoring_station_candidates.json

No CARLA connection is required for this script.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path


def _route_kind(route):
    return str(route.get("route_type", "unknown"))


def analyze_routes(matrix):
    routes = [r for r in matrix.get("routes", []) if r.get("reachable", False)]

    stats = defaultdict(lambda: {
        "route_ids": set(),
        "empty_route_ids": set(),
        "haul_route_ids": set(),
        "occurrences": 0,
    })

    for route in routes:
        route_id = str(route.get("route_id", ""))
        kind = _route_kind(route)

        # A road/lane may appear more than once in one raw route sequence.
        # Route coverage should count that route only once.
        seen_in_route = set()

        for item in route.get("road_lane_sequence", []):
            key = (int(item["road_id"]), int(item["lane_id"]))
            stats[key]["occurrences"] += 1

            if key in seen_in_route:
                continue
            seen_in_route.add(key)

            stats[key]["route_ids"].add(route_id)
            if kind == "haul_to_dump":
                stats[key]["haul_route_ids"].add(route_id)
            elif kind == "empty_to_loading":
                stats[key]["empty_route_ids"].add(route_id)

    total_routes = len(routes)
    rows = []

    for (road_id, lane_id), value in stats.items():
        route_count = len(value["route_ids"])
        haul_count = len(value["haul_route_ids"])
        empty_count = len(value["empty_route_ids"])

        rows.append({
            "road_id": road_id,
            "lane_id": lane_id,
            "route_coverage_count": route_count,
            "route_coverage_ratio": (
                round(float(route_count) / float(total_routes), 6)
                if total_routes else 0.0
            ),
            "haul_route_coverage_count": haul_count,
            "empty_route_coverage_count": empty_count,
            "sequence_occurrences": value["occurrences"],
            "route_ids": sorted(value["route_ids"]),
        })

    rows.sort(
        key=lambda x: (
            -x["haul_route_coverage_count"],
            -x["route_coverage_count"],
            -x["empty_route_coverage_count"],
            x["road_id"],
            x["lane_id"],
        )
    )
    return rows, total_routes


def select_candidates(ranked, count):
    """
    Select distinct road IDs first so two stations are not immediately chosen
    on opposite lanes of the same road. If not enough distinct roads exist,
    fall back to remaining road/lane pairs.
    """
    selected = []
    used_road_ids = set()

    for row in ranked:
        if row["road_id"] in used_road_ids:
            continue
        selected.append(row)
        used_road_ids.add(row["road_id"])
        if len(selected) >= count:
            return selected

    for row in ranked:
        key = (row["road_id"], row["lane_id"])
        if any((x["road_id"], x["lane_id"]) == key for x in selected):
            continue
        selected.append(row)
        if len(selected) >= count:
            break

    return selected


def build_output(matrix, ranked, selected):
    stations = []
    for index, row in enumerate(selected, 1):
        stations.append({
            "station_id": "station_road_{:02d}".format(index),
            "station_type": "road_monitor",
            "road_id": row["road_id"],
            "lane_id": row["lane_id"],
            "route_coverage_count": row["route_coverage_count"],
            "route_coverage_ratio": row["route_coverage_ratio"],
            "haul_route_coverage_count": row["haul_route_coverage_count"],
            "empty_route_coverage_count": row["empty_route_coverage_count"],
            "monitor_radius_m": 80.0,
            "camera_enabled": True,
            "placement_status": "ROAD_LANE_SELECTED_NEEDS_CARLA_PREVIEW",
        })

    return {
        "schema_version": "1.0-monitoring-station-candidates",
        "map_id": matrix.get("map_id"),
        "source_route_matrix_schema": matrix.get("schema_version"),
        "selection_rule": (
            "Rank road/lane pairs primarily by haul-route coverage, then total "
            "route coverage; prefer distinct road_ids for fixed-station candidates."
        ),
        "route_count_analyzed": len(
            [r for r in matrix.get("routes", []) if r.get("reachable", False)]
        ),
        "stations": stations,
        "top_ranked_road_lanes": ranked[:20],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--matrix",
        default="configs/decision_route_matrix.json",
    )
    parser.add_argument(
        "--output",
        default="configs/monitoring_station_candidates.json",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=3,
        help="Number of route-driven fixed-station candidates",
    )
    args = parser.parse_args()

    if args.count < 1:
        raise SystemExit("--count must be >= 1")

    matrix_path = Path(args.matrix)
    with matrix_path.open("r", encoding="utf-8") as f:
        matrix = json.load(f)

    ranked, total_routes = analyze_routes(matrix)
    if not ranked:
        raise RuntimeError(
            "No road_lane_sequence data found in reachable routes: {}".format(
                matrix_path
            )
        )

    selected = select_candidates(ranked, args.count)
    output = build_output(matrix, ranked, selected)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("========================================")
    print("MONITORING V1A ROUTE COVERAGE COMPLETE")
    print("map               : {}".format(matrix.get("map_id")))
    print("reachable routes  : {}".format(total_routes))
    print("road/lane pairs   : {}".format(len(ranked)))
    print("selected stations : {}".format(len(selected)))
    print("----------------------------------------")
    for index, row in enumerate(selected, 1):
        print(
            "station_road_{:02d} | road={} lane={} | total={} | haul={} | empty={}".format(
                index,
                row["road_id"],
                row["lane_id"],
                row["route_coverage_count"],
                row["haul_route_coverage_count"],
                row["empty_route_coverage_count"],
            )
        )
    print("output            : {}".format(out))
    print("========================================")


if __name__ == "__main__":
    main()
