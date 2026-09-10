#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the S01/S02/S07 formal CAT-calibrated Decision route matrix.

This utility does NOT spawn or move any vehicle.
It only asks CARLA 0.9.10 GlobalRoutePlanner for:
    12 -> 48
    78 -> 48
"""

from __future__ import print_function

import argparse
import glob
import json
import math
import os
import sys
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
            sys.path.insert(0, matches[-1])
            return

    raise RuntimeError("CARLA Python3.7 egg not found under {}".format(dist_dir))


def make_planner(carla_map, resolution):
    from agents.navigation.global_route_planner import GlobalRoutePlanner
    from agents.navigation.global_route_planner_dao import GlobalRoutePlannerDAO

    dao = GlobalRoutePlannerDAO(carla_map, resolution)
    planner = GlobalRoutePlanner(dao)
    planner.setup()
    return planner


def distance(a, b):
    dx = float(a.x) - float(b.x)
    dy = float(a.y) - float(b.y)
    dz = float(a.z) - float(b.z)
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def route_distance(route):
    if not route:
        return 0.0
    locs = [wp.transform.location for wp, _ in route]
    return sum(distance(locs[i - 1], locs[i]) for i in range(1, len(locs)))


def road_lane_sequence(route):
    seq = []
    previous = None
    for waypoint, _ in route:
        current = (int(waypoint.road_id), int(waypoint.lane_id))
        if current != previous:
            seq.append({
                "road_id": current[0],
                "lane_id": current[1],
            })
            previous = current
    return seq


def trace(planner, spawn_points, src, dst, speed_kmh):
    route = planner.trace_route(
        spawn_points[src].location,
        spawn_points[dst].location,
    )
    if not route:
        raise RuntimeError("Empty CARLA route {} -> {}".format(src, dst))

    dist_m = route_distance(route)
    eta_s = dist_m / (float(speed_kmh) / 3.6)

    return {
        "route_id": "haul_to_dump_{}_to_{}".format(src, dst),
        "route_type": "haul_to_dump",
        "from_spawn_point_index": int(src),
        "to_spawn_point_index": int(dst),
        "reachable": True,
        "distance_m": round(dist_m, 3),
        "estimated_time_s": round(eta_s, 3),
        "waypoint_count": len(route),
        "road_lane_sequence": road_lane_sequence(route),
        "cat_validation_status": "formal_baseline_route_pool"
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--carla-root",
        default="/home/xiaoa/carla/Dist/CARLA_Shipping_0.9.10-dirty/LinuxNoEditor",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--sampling-resolution", type=float, default=2.0)
    parser.add_argument("--reference-speed-kmh", type=float, default=14.0)
    parser.add_argument(
        "--output",
        default="configs/decision_route_matrix_formal_calibrated.json",
    )
    args = parser.parse_args()

    add_carla_paths(args.carla_root)
    import carla

    client = carla.Client(args.host, args.port)
    client.set_timeout(args.timeout)
    world = client.get_world()
    carla_map = world.get_map()

    map_name = str(carla_map.name).split("/")[-1]
    if map_name != "0325_5":
        raise RuntimeError("Expected CARLA map 0325_5, got {}".format(map_name))

    spawn_points = carla_map.get_spawn_points()
    required = (12, 48, 78)
    invalid = [i for i in required if i < 0 or i >= len(spawn_points)]
    if invalid:
        raise RuntimeError("Spawn indices out of range: {}".format(invalid))

    planner = make_planner(carla_map, args.sampling_resolution)

    routes = [
        trace(planner, spawn_points, 12, 48, args.reference_speed_kmh),
        trace(planner, spawn_points, 78, 48, args.reference_speed_kmh),
    ]

    output = {
        "schema_version": "1.0-decision-route-matrix-formal-cat-calibrated",
        "map_id": map_name,
        "sampling_resolution_m": float(args.sampling_resolution),
        "reference_speed_kmh": float(args.reference_speed_kmh),
        "initial_spawn_indices": [12, 78],
        "loading_spawn_indices": [12, 78],
        "dump_spawn_indices": [48],
        "routes": routes,
        "summary": {
            "empty_route_pairs": 0,
            "haul_route_pairs": 2,
            "total_pairs": 2,
            "reachable_pairs": 2,
            "unreachable_pairs": 0,
        },
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("FORMAL CAT ROUTE MATRIX READY")
    for rec in routes:
        print(
            "{} -> {} | {:.1f}m | ETA {:.1f}s | wp={}".format(
                rec["from_spawn_point_index"],
                rec["to_spawn_point_index"],
                rec["distance_m"],
                rec["estimated_time_s"],
                rec["waypoint_count"],
            )
        )
    print("output:", out)


if __name__ == "__main__":
    main()
