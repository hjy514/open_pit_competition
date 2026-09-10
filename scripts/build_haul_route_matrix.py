#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Build a haul-route reachability/cost matrix for CARLA 0.9.10 map 0325_5.

It reads haul loading/dump candidate spawn indices from
map_resource_operating_areas_v1.json, then uses CARLA's GlobalRoutePlanner
to test every loading -> dump pair.

Output:
    configs/haul_route_matrix.json

This is an offline/pre-computation utility. It does not spawn or drive vehicles.
"""

import argparse
import glob
import json
import math
import os
import sys
from pathlib import Path


def _add_carla_paths(carla_root):
    carla_root = os.path.expanduser(carla_root)

    pythonapi_carla = os.path.join(carla_root, "PythonAPI", "carla")
    if os.path.isdir(pythonapi_carla) and pythonapi_carla not in sys.path:
        sys.path.insert(0, pythonapi_carla)

    dist_dir = os.path.join(pythonapi_carla, "dist")
    egg_patterns = [
        os.path.join(dist_dir, "carla-0.9.10-py3.7-linux-x86_64.egg"),
        os.path.join(dist_dir, "carla-*py3.7-linux-x86_64.egg"),
        os.path.join(dist_dir, "carla-*.egg"),
    ]
    for pattern in egg_patterns:
        matches = sorted(glob.glob(pattern))
        if matches:
            if matches[-1] not in sys.path:
                sys.path.insert(0, matches[-1])
            break


def _load_candidate_indices(path):
    path = Path(os.path.expanduser(path))
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    loading = None
    dump = None

    for area in data.get("areas", []):
        area_type = area.get("area_type")
        if area_type == "haul_loading":
            loading = list(area.get("point_spawn_indices", []))
        elif area_type == "haul_dump":
            dump = list(area.get("point_spawn_indices", []))

    if not loading:
        raise RuntimeError("No haul_loading candidate indices found in {}".format(path))
    if not dump:
        raise RuntimeError("No haul_dump candidate indices found in {}".format(path))

    return sorted(set(int(x) for x in loading)), sorted(set(int(x) for x in dump))


def _make_planner(carla_map, sampling_resolution):
    # CARLA 0.9.10 API
    try:
        from agents.navigation.global_route_planner import GlobalRoutePlanner
        from agents.navigation.global_route_planner_dao import GlobalRoutePlannerDAO

        dao = GlobalRoutePlannerDAO(carla_map, sampling_resolution)
        planner = GlobalRoutePlanner(dao)
        planner.setup()
        return planner
    except Exception as old_api_error:
        # Compatibility fallback for newer CARLA layouts.
        try:
            from agents.navigation.global_route_planner import GlobalRoutePlanner
            return GlobalRoutePlanner(carla_map, sampling_resolution)
        except Exception:
            raise RuntimeError(
                "Unable to initialize GlobalRoutePlanner. "
                "Old API error: {}".format(old_api_error)
            )


def _location_distance(a, b):
    dx = float(a.x) - float(b.x)
    dy = float(a.y) - float(b.y)
    dz = float(a.z) - float(b.z)
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def _route_distance(route):
    if not route:
        return 0.0

    locations = [item[0].transform.location for item in route]
    distance = 0.0
    for i in range(1, len(locations)):
        distance += _location_distance(locations[i - 1], locations[i])
    return distance


def _road_lane_sequence(route):
    result = []
    previous = None

    for waypoint, _road_option in route:
        current = (int(waypoint.road_id), int(waypoint.lane_id))
        if current != previous:
            result.append({
                "road_id": current[0],
                "lane_id": current[1],
            })
            previous = current

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--carla-root",
        default="/home/xiaoa/carla/Dist/CARLA_Shipping_0.9.10-dirty/LinuxNoEditor",
        help="CARLA packaged root",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument(
        "--operating-areas",
        default="configs/operating_areas.json",
    )
    parser.add_argument(
        "--output",
        default="configs/haul_route_matrix.json",
    )
    parser.add_argument(
        "--sampling-resolution",
        type=float,
        default=2.0,
    )
    parser.add_argument(
        "--reference-speed-kmh",
        type=float,
        default=14.0,
        help="Only used to estimate route travel time for Decision baseline",
    )
    args = parser.parse_args()

    _add_carla_paths(args.carla_root)

    import carla

    loading_indices, dump_indices = _load_candidate_indices(args.operating_areas)

    client = carla.Client(args.host, args.port)
    client.set_timeout(args.timeout)

    world = client.get_world()
    carla_map = world.get_map()
    spawn_points = carla_map.get_spawn_points()

    map_name = str(carla_map.name).split("/")[-1]
    print("[MAP] {}".format(map_name))
    print("[SPAWN POINTS] {}".format(len(spawn_points)))
    print("[LOADING] {}".format(loading_indices))
    print("[DUMP] {}".format(dump_indices))

    all_indices = loading_indices + dump_indices
    invalid = [i for i in all_indices if i < 0 or i >= len(spawn_points)]
    if invalid:
        raise RuntimeError(
            "Spawn indices out of range: {} (spawn count={})".format(
                invalid, len(spawn_points)
            )
        )

    planner = _make_planner(carla_map, args.sampling_resolution)

    routes = []
    reachable_count = 0
    total_pairs = len(loading_indices) * len(dump_indices)
    speed_mps = args.reference_speed_kmh / 3.6

    for from_index in loading_indices:
        for to_index in dump_indices:
            start = spawn_points[from_index].location
            end = spawn_points[to_index].location
            route_id = "haul_{}_to_{}".format(from_index, to_index)

            record = {
                "route_id": route_id,
                "from_spawn_point_index": from_index,
                "to_spawn_point_index": to_index,
                "reachable": False,
            }

            try:
                route = planner.trace_route(start, end)
                if route:
                    distance_m = _route_distance(route)
                    estimated_time_s = (
                        distance_m / speed_mps if speed_mps > 0.0 else None
                    )

                    record.update({
                        "reachable": True,
                        "distance_m": round(distance_m, 3),
                        "estimated_time_s_at_reference_speed": (
                            round(estimated_time_s, 3)
                            if estimated_time_s is not None
                            else None
                        ),
                        "waypoint_count": len(route),
                        "road_lane_sequence": _road_lane_sequence(route),
                    })
                    reachable_count += 1
                    print(
                        "[OK] {:>2} -> {:>2} | {:>8.1f} m | {:>4} wp".format(
                            from_index,
                            to_index,
                            distance_m,
                            len(route),
                        )
                    )
                else:
                    record["reason"] = "empty_route"
                    print("[NO] {:>2} -> {:>2} | empty route".format(
                        from_index, to_index
                    ))
            except Exception as exc:
                record["reason"] = "{}: {}".format(
                    type(exc).__name__,
                    str(exc),
                )
                print("[ERR] {:>2} -> {:>2} | {}".format(
                    from_index, to_index, record["reason"]
                ))

            routes.append(record)

    output = {
        "schema_version": "1.0-haul-route-matrix",
        "map_id": map_name,
        "source_operating_area_profile": str(
            Path(os.path.expanduser(args.operating_areas))
        ),
        "sampling_resolution_m": args.sampling_resolution,
        "reference_speed_kmh": args.reference_speed_kmh,
        "loading_spawn_indices": loading_indices,
        "dump_spawn_indices": dump_indices,
        "routes": routes,
        "summary": {
            "total_pairs": total_pairs,
            "reachable_pairs": reachable_count,
            "unreachable_pairs": total_pairs - reachable_count,
        },
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print()
    print("========================================")
    print("HAUL ROUTE MATRIX COMPLETE")
    print("map              : {}".format(map_name))
    print("total pairs      : {}".format(total_pairs))
    print("reachable pairs  : {}".format(reachable_count))
    print("unreachable pairs: {}".format(total_pairs - reachable_count))
    print("output           : {}".format(output_path))
    print("========================================")


if __name__ == "__main__":
    main()
