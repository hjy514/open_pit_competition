#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Build Decision route matrix for CARLA 0.9.10 map 0325_5.

Includes:
1) initial/reposition routes: {12, 78, dump points} -> loading points
2) haul routes: loading points -> dump points

Output:
    configs/decision_route_matrix.json

No vehicles are spawned. CARLA GlobalRoutePlanner is used only for offline
reachability/distance precomputation.
"""

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
    raise RuntimeError("CARLA Python 3.7 egg not found under {}".format(dist_dir))


def load_areas(path):
    with open(os.path.expanduser(path), "r", encoding="utf-8") as f:
        data = json.load(f)

    loading, dump = [], []
    for area in data.get("areas", []):
        if area.get("area_type") == "haul_loading":
            loading = [int(x) for x in area.get("point_spawn_indices", [])]
        elif area.get("area_type") == "haul_dump":
            dump = [int(x) for x in area.get("point_spawn_indices", [])]

    if not loading or not dump:
        raise RuntimeError("haul_loading / haul_dump candidate pools not found")

    return sorted(set(loading)), sorted(set(dump))


def make_planner(carla_map, sampling_resolution):
    from agents.navigation.global_route_planner import GlobalRoutePlanner
    from agents.navigation.global_route_planner_dao import GlobalRoutePlannerDAO

    dao = GlobalRoutePlannerDAO(carla_map, sampling_resolution)
    planner = GlobalRoutePlanner(dao)
    planner.setup()
    return planner


def loc_dist(a, b):
    dx = float(a.x) - float(b.x)
    dy = float(a.y) - float(b.y)
    dz = float(a.z) - float(b.z)
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def route_distance(route):
    if not route:
        return 0.0
    locs = [wp.transform.location for wp, _ in route]
    return sum(loc_dist(locs[i - 1], locs[i]) for i in range(1, len(locs)))


def road_sequence(route):
    seq = []
    prev = None
    for wp, _ in route:
        cur = (int(wp.road_id), int(wp.lane_id))
        if cur != prev:
            seq.append({"road_id": cur[0], "lane_id": cur[1]})
            prev = cur
    return seq


def trace(planner, spawn_points, from_idx, to_idx, kind, speed_kmh):
    record = {
        "route_id": "{}_{}_to_{}".format(kind, from_idx, to_idx),
        "route_type": kind,
        "from_spawn_point_index": from_idx,
        "to_spawn_point_index": to_idx,
        "reachable": False,
    }

    try:
        route = planner.trace_route(
            spawn_points[from_idx].location,
            spawn_points[to_idx].location,
        )
        if not route:
            record["reason"] = "empty_route"
            return record

        distance_m = route_distance(route)
        speed_mps = speed_kmh / 3.6
        record.update({
            "reachable": True,
            "distance_m": round(distance_m, 3),
            "estimated_time_s": round(distance_m / speed_mps, 3),
            "waypoint_count": len(route),
            "road_lane_sequence": road_sequence(route),
        })
        return record
    except Exception as exc:
        record["reason"] = "{}: {}".format(type(exc).__name__, exc)
        return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--carla-root",
        default="/home/xiaoa/carla/Dist/CARLA_Shipping_0.9.10-dirty/LinuxNoEditor",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument(
        "--operating-areas",
        default="~/矿山调度/open_pit_agent_demo/configs/map_resource_operating_areas_v1.json",
    )
    parser.add_argument(
        "--output",
        default="configs/decision_route_matrix.json",
    )
    parser.add_argument("--sampling-resolution", type=float, default=2.0)
    parser.add_argument("--reference-speed-kmh", type=float, default=14.0)
    parser.add_argument(
        "--initial-spawn-indices",
        default="12,78",
        help="Comma-separated initial truck spawn indices",
    )
    args = parser.parse_args()

    add_carla_paths(args.carla_root)
    import carla

    loading, dump = load_areas(args.operating_areas)
    initial = sorted(set(
        int(x.strip())
        for x in args.initial_spawn_indices.split(",")
        if x.strip()
    ))

    client = carla.Client(args.host, args.port)
    client.set_timeout(args.timeout)
    world = client.get_world()
    carla_map = world.get_map()
    spawn_points = carla_map.get_spawn_points()

    map_name = str(carla_map.name).split("/")[-1]
    print("[MAP] {}".format(map_name))
    print("[INITIAL] {}".format(initial))
    print("[LOADING] {}".format(loading))
    print("[DUMP] {}".format(dump))

    needed = sorted(set(initial + loading + dump))
    bad = [x for x in needed if x < 0 or x >= len(spawn_points)]
    if bad:
        raise RuntimeError("Spawn indices out of range: {}".format(bad))

    planner = make_planner(carla_map, args.sampling_resolution)

    routes = []

    empty_origins = sorted(set(initial + dump))
    total_empty = len(empty_origins) * len(loading)
    total_haul = len(loading) * len(dump)

    print()
    print("=== EMPTY / REPOSITION ROUTES ===")
    for src in empty_origins:
        for dst in loading:
            rec = trace(
                planner, spawn_points, src, dst,
                "empty_to_loading", args.reference_speed_kmh
            )
            routes.append(rec)
            status = "OK" if rec["reachable"] else "NO"
            extra = "{:.1f} m".format(rec["distance_m"]) if rec["reachable"] else rec.get("reason", "")
            print("[{}] {:>2} -> {:>2} | {}".format(status, src, dst, extra))

    print()
    print("=== HAUL ROUTES ===")
    for src in loading:
        for dst in dump:
            rec = trace(
                planner, spawn_points, src, dst,
                "haul_to_dump", args.reference_speed_kmh
            )
            routes.append(rec)
            status = "OK" if rec["reachable"] else "NO"
            extra = "{:.1f} m".format(rec["distance_m"]) if rec["reachable"] else rec.get("reason", "")
            print("[{}] {:>2} -> {:>2} | {}".format(status, src, dst, extra))

    reachable = sum(1 for r in routes if r["reachable"])
    total = len(routes)

    output = {
        "schema_version": "1.0-decision-route-matrix",
        "map_id": map_name,
        "sampling_resolution_m": args.sampling_resolution,
        "reference_speed_kmh": args.reference_speed_kmh,
        "initial_spawn_indices": initial,
        "loading_spawn_indices": loading,
        "dump_spawn_indices": dump,
        "routes": routes,
        "summary": {
            "empty_route_pairs": total_empty,
            "haul_route_pairs": total_haul,
            "total_pairs": total,
            "reachable_pairs": reachable,
            "unreachable_pairs": total - reachable,
        },
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print()
    print("========================================")
    print("DECISION ROUTE MATRIX COMPLETE")
    print("empty pairs      : {}".format(total_empty))
    print("haul pairs       : {}".format(total_haul))
    print("total pairs      : {}".format(total))
    print("reachable pairs  : {}".format(reachable))
    print("unreachable pairs: {}".format(total - reachable))
    print("output           : {}".format(out))
    print("========================================")


if __name__ == "__main__":
    main()
