#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Monitoring V1A.2 - final fixed-station siting.

Goal:
    Decision route matrix
        -> road/lane route coverage
        -> CARLA physical coordinates
        -> spatial de-duplication
        -> marginal route coverage
        -> final 3 monitoring stations

Selection policy:
1) First station: strongest haul-route coverage.
2) Later stations:
   - must be at least --min-distance-m away from every selected station
   - prefer NEW haul routes not already covered
   - then prefer NEW total routes not already covered
   - then fall back to original haul/total coverage

This script DOES NOT spawn cameras, modify Runtime, or modify Decision.
"""

import argparse
import glob
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path


def add_carla_paths(carla_root):
    carla_root = os.path.expanduser(carla_root)
    pythonapi_carla = os.path.join(carla_root, "PythonAPI", "carla")
    if pythonapi_carla not in sys.path:
        sys.path.insert(0, pythonapi_carla)

    dist_dir = os.path.join(pythonapi_carla, "dist")
    patterns = [
        os.path.join(dist_dir, "carla-0.9.10-py3.7-linux-x86_64.egg"),
        os.path.join(dist_dir, "carla-*py3.7-linux-x86_64.egg"),
    ]
    for pattern in patterns:
        matches = sorted(glob.glob(pattern))
        if matches:
            if matches[-1] not in sys.path:
                sys.path.insert(0, matches[-1])
            return

    raise RuntimeError(
        "CARLA Python 3.7 egg not found under {}".format(dist_dir)
    )


def analyze_routes(matrix):
    routes = [
        r for r in matrix.get("routes", [])
        if r.get("reachable", False)
    ]

    stats = defaultdict(lambda: {
        "route_ids": set(),
        "haul_route_ids": set(),
        "empty_route_ids": set(),
        "sequence_occurrences": 0,
    })

    for route in routes:
        route_id = str(route.get("route_id", ""))
        route_type = str(route.get("route_type", "unknown"))
        seen = set()

        for item in route.get("road_lane_sequence", []):
            key = (int(item["road_id"]), int(item["lane_id"]))
            stats[key]["sequence_occurrences"] += 1

            # Coverage is per route, not per repeated appearance in one route.
            if key in seen:
                continue
            seen.add(key)

            stats[key]["route_ids"].add(route_id)
            if route_type == "haul_to_dump":
                stats[key]["haul_route_ids"].add(route_id)
            elif route_type == "empty_to_loading":
                stats[key]["empty_route_ids"].add(route_id)

    rows = []
    total_routes = len(routes)

    for (road_id, lane_id), value in stats.items():
        route_ids = sorted(value["route_ids"])
        haul_ids = sorted(value["haul_route_ids"])
        empty_ids = sorted(value["empty_route_ids"])

        rows.append({
            "road_id": road_id,
            "lane_id": lane_id,
            "route_coverage_count": len(route_ids),
            "route_coverage_ratio": (
                round(float(len(route_ids)) / float(total_routes), 6)
                if total_routes else 0.0
            ),
            "haul_route_coverage_count": len(haul_ids),
            "empty_route_coverage_count": len(empty_ids),
            "sequence_occurrences": value["sequence_occurrences"],
            "route_ids": route_ids,
            "haul_route_ids": haul_ids,
            "empty_route_ids": empty_ids,
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


def choose_representative_waypoint(matches):
    """
    Choose a waypoint close to the center of the road/lane sample cloud.
    This is more stable than taking the first waypoint.
    """
    if not matches:
        return None

    cx = sum(float(wp.transform.location.x) for wp in matches) / len(matches)
    cy = sum(float(wp.transform.location.y) for wp in matches) / len(matches)

    return min(
        matches,
        key=lambda wp: (
            (float(wp.transform.location.x) - cx) ** 2
            + (float(wp.transform.location.y) - cy) ** 2
        ),
    )


def horizontal_distance_xy(a, b):
    dx = float(a["x"]) - float(b["x"])
    dy = float(a["y"]) - float(b["y"])
    return math.sqrt(dx * dx + dy * dy)


def resolve_physical_candidates(ranked, all_waypoints):
    resolved = []

    for row in ranked:
        road_id = int(row["road_id"])
        lane_id = int(row["lane_id"])

        matches = [
            wp for wp in all_waypoints
            if int(wp.road_id) == road_id
            and int(wp.lane_id) == lane_id
        ]

        wp = choose_representative_waypoint(matches)
        if wp is None:
            continue

        loc = wp.transform.location
        item = dict(row)
        item.update({
            "x": round(float(loc.x), 3),
            "y": round(float(loc.y), 3),
            "z": round(float(loc.z), 3),
            "road_yaw_deg": round(float(wp.transform.rotation.yaw), 3),
            "matched_waypoint_count": len(matches),
        })
        resolved.append(item)

    return resolved


def _score_candidate(candidate, covered_haul, covered_total):
    haul_ids = set(candidate.get("haul_route_ids", []))
    total_ids = set(candidate.get("route_ids", []))

    marginal_haul = len(haul_ids - covered_haul)
    marginal_total = len(total_ids - covered_total)

    return (
        marginal_haul,
        marginal_total,
        int(candidate["haul_route_coverage_count"]),
        int(candidate["route_coverage_count"]),
        int(candidate["matched_waypoint_count"]),
    )


def select_final_stations(candidates, count=3, min_distance_m=150.0):
    """
    Pure selection function used by both the script and tests.
    """
    if count < 1:
        return []

    remaining = list(candidates)
    selected = []
    covered_haul = set()
    covered_total = set()

    while remaining and len(selected) < count:
        eligible = []

        for candidate in remaining:
            if selected:
                nearest = min(
                    horizontal_distance_xy(candidate, chosen)
                    for chosen in selected
                )
                if nearest < min_distance_m:
                    continue
            else:
                nearest = None

            score = _score_candidate(
                candidate,
                covered_haul,
                covered_total,
            )
            eligible.append((score, nearest, candidate))

        if not eligible:
            break

        # Descending score. For later stations, larger physical spacing wins
        # only after route-coverage criteria tie.
        eligible.sort(
            key=lambda item: (
                item[0][0],
                item[0][1],
                item[0][2],
                item[0][3],
                item[1] if item[1] is not None else 1e12,
                item[0][4],
            ),
            reverse=True,
        )

        score, nearest, chosen = eligible[0]

        chosen = dict(chosen)
        chosen["marginal_haul_route_count"] = score[0]
        chosen["marginal_total_route_count"] = score[1]
        chosen["nearest_selected_distance_m"] = (
            None if nearest is None else round(float(nearest), 3)
        )

        selected.append(chosen)
        covered_haul.update(chosen.get("haul_route_ids", []))
        covered_total.update(chosen.get("route_ids", []))

        chosen_key = (chosen["road_id"], chosen["lane_id"])
        remaining = [
            item for item in remaining
            if (item["road_id"], item["lane_id"]) != chosen_key
        ]

    return selected


def build_output(matrix, selected, analyzed_count, min_distance_m):
    total_haul_ids = set()
    total_route_ids = set()

    stations = []
    for index, item in enumerate(selected, 1):
        total_haul_ids.update(item.get("haul_route_ids", []))
        total_route_ids.update(item.get("route_ids", []))

        station = {
            "station_id": "station_road_{:02d}".format(index),
            "station_type": "road_monitor",
            "road_id": item["road_id"],
            "lane_id": item["lane_id"],
            "x": item["x"],
            "y": item["y"],
            "z": item["z"],
            "road_yaw_deg": item["road_yaw_deg"],
            "monitor_radius_m": 80.0,
            "camera_enabled": True,
            "route_coverage_count": item["route_coverage_count"],
            "haul_route_coverage_count": item["haul_route_coverage_count"],
            "empty_route_coverage_count": item["empty_route_coverage_count"],
            "marginal_haul_route_count": item["marginal_haul_route_count"],
            "marginal_total_route_count": item["marginal_total_route_count"],
            "nearest_selected_distance_m": item["nearest_selected_distance_m"],
            "matched_waypoint_count": item["matched_waypoint_count"],
            "placement_status": "FINAL_ROUTE_AND_DISTANCE_SELECTED",
            # Keep IDs so later Monitoring/Closed Loop can explain exactly
            # which Decision routes are covered by a station.
            "route_ids": item.get("route_ids", []),
            "haul_route_ids": item.get("haul_route_ids", []),
            "empty_route_ids": item.get("empty_route_ids", []),
        }
        stations.append(station)

    return {
        "schema_version": "1.0-monitoring-stations",
        "map_id": matrix.get("map_id"),
        "source_route_matrix_schema": matrix.get("schema_version"),
        "selection_policy": {
            "primary": "marginal_haul_route_coverage",
            "secondary": "marginal_total_route_coverage",
            "min_station_distance_m": min_distance_m,
        },
        "road_lane_candidate_count": analyzed_count,
        "final_station_count": len(stations),
        "combined_unique_route_coverage_count": len(total_route_ids),
        "combined_unique_haul_route_coverage_count": len(total_haul_ids),
        "stations": stations,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--matrix",
        default="configs/decision_route_matrix.json",
    )
    parser.add_argument(
        "--output",
        default="configs/monitoring_stations.json",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=3,
    )
    parser.add_argument(
        "--min-distance-m",
        type=float,
        default=150.0,
    )
    parser.add_argument(
        "--carla-root",
        default="/home/xiaoa/carla/Dist/CARLA_Shipping_0.9.10-dirty/LinuxNoEditor",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--waypoint-spacing", type=float, default=2.0)
    args = parser.parse_args()

    if args.count < 1:
        raise SystemExit("--count must be >= 1")
    if args.min_distance_m < 0:
        raise SystemExit("--min-distance-m must be >= 0")

    with Path(args.matrix).open("r", encoding="utf-8") as f:
        matrix = json.load(f)

    ranked, total_routes = analyze_routes(matrix)
    if not ranked:
        raise RuntimeError(
            "No reachable route contains road_lane_sequence."
        )

    add_carla_paths(args.carla_root)
    import carla

    client = carla.Client(args.host, args.port)
    client.set_timeout(args.timeout)
    world = client.get_world()
    carla_map = world.get_map()

    current_map = str(carla_map.name).split("/")[-1]
    expected_map = matrix.get("map_id")
    if expected_map and current_map != expected_map:
        raise RuntimeError(
            "CARLA map mismatch: current={} route_matrix={}".format(
                current_map,
                expected_map,
            )
        )

    all_waypoints = carla_map.generate_waypoints(args.waypoint_spacing)
    physical_candidates = resolve_physical_candidates(
        ranked,
        all_waypoints,
    )

    selected = select_final_stations(
        physical_candidates,
        count=args.count,
        min_distance_m=args.min_distance_m,
    )

    if len(selected) < args.count:
        raise RuntimeError(
            "Only {} stations satisfy min distance {:.1f}m. "
            "Try a smaller --min-distance-m if needed.".format(
                len(selected),
                args.min_distance_m,
            )
        )

    output = build_output(
        matrix,
        selected,
        len(physical_candidates),
        args.min_distance_m,
    )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("========================================")
    print("MONITORING V1A.2 FINAL SITING COMPLETE")
    print("map                        : {}".format(current_map))
    print("reachable routes           : {}".format(total_routes))
    print("physical road/lane pairs   : {}".format(len(physical_candidates)))
    print("min station distance       : {:.1f} m".format(
        args.min_distance_m
    ))
    print("final stations             : {}".format(len(selected)))
    print("----------------------------------------")

    for index, station in enumerate(output["stations"], 1):
        print(
            "station_road_{:02d} | road={} lane={} | "
            "xyz=({:.1f},{:.1f},{:.1f}) | haul={} | "
            "new_haul={} | total={} | new_total={} | nearest={}".format(
                index,
                station["road_id"],
                station["lane_id"],
                station["x"],
                station["y"],
                station["z"],
                station["haul_route_coverage_count"],
                station["marginal_haul_route_count"],
                station["route_coverage_count"],
                station["marginal_total_route_count"],
                (
                    "-"
                    if station["nearest_selected_distance_m"] is None
                    else "{:.1f}m".format(
                        station["nearest_selected_distance_m"]
                    )
                ),
            )
        )

    print("----------------------------------------")
    print(
        "combined unique routes       : {}".format(
            output["combined_unique_route_coverage_count"]
        )
    )
    print(
        "combined unique haul routes  : {}".format(
            output["combined_unique_haul_route_coverage_count"]
        )
    )
    print("output                      : {}".format(out))
    print("========================================")


if __name__ == "__main__":
    main()
