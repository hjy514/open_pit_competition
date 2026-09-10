#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Monitoring V1A.1 CARLA preview.

Compared with V1A:
- automatically moves CARLA spectator to each station candidate
- uses much larger/debug-visible markers
- draws a tall station mast + label + road-direction arrow
- cycles through every station so the user can visually confirm placement

This still does NOT spawn RGB camera sensors and does NOT modify Runtime.
"""

import argparse
import glob
import json
import math
import os
import sys
import time


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
    raise RuntimeError("CARLA Python 3.7 egg not found under {}".format(dist_dir))


def choose_representative_waypoint(matches):
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


def focus_spectator(carla, spectator, transform):
    """Put the spectator behind and above the road, looking forward."""
    loc = transform.location
    yaw = float(transform.rotation.yaw)
    yaw_rad = math.radians(yaw)

    # 22 m behind the station along the lane direction, 12 m above it.
    sx = float(loc.x) - math.cos(yaw_rad) * 22.0
    sy = float(loc.y) - math.sin(yaw_rad) * 22.0
    sz = float(loc.z) + 12.0

    spectator.set_transform(
        carla.Transform(
            carla.Location(x=sx, y=sy, z=sz),
            carla.Rotation(pitch=-22.0, yaw=yaw, roll=0.0),
        )
    )


def draw_station(world, carla, station, wp, life_time):
    tr = wp.transform
    loc = tr.location
    yaw = float(tr.rotation.yaw)
    yaw_rad = math.radians(yaw)

    road_loc = carla.Location(
        x=float(loc.x),
        y=float(loc.y),
        z=float(loc.z) + 0.5,
    )
    mast_top = carla.Location(
        x=float(loc.x),
        y=float(loc.y),
        z=float(loc.z) + 10.0,
    )
    label_loc = carla.Location(
        x=float(loc.x),
        y=float(loc.y),
        z=float(loc.z) + 11.5,
    )

    # Tall mast: much easier to see than a small point on the road.
    world.debug.draw_line(
        road_loc,
        mast_top,
        thickness=0.25,
        color=carla.Color(255, 140, 0),
        life_time=life_time,
        persistent_lines=False,
    )

    world.debug.draw_point(
        mast_top,
        size=0.8,
        color=carla.Color(255, 60, 30),
        life_time=life_time,
        persistent_lines=False,
    )

    world.debug.draw_string(
        label_loc,
        "{} | R{} L{} | cov={}".format(
            station["station_id"],
            station["road_id"],
            station["lane_id"],
            station["route_coverage_count"],
        ),
        draw_shadow=True,
        color=carla.Color(255, 255, 255),
        life_time=life_time,
        persistent_lines=False,
    )

    # Lane-forward direction arrow, 18 m long.
    arrow_end = carla.Location(
        x=float(loc.x) + math.cos(yaw_rad) * 18.0,
        y=float(loc.y) + math.sin(yaw_rad) * 18.0,
        z=float(loc.z) + 1.2,
    )
    world.debug.draw_arrow(
        road_loc,
        arrow_end,
        thickness=0.22,
        arrow_size=0.7,
        color=carla.Color(30, 255, 80),
        life_time=life_time,
        persistent_lines=False,
    )


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
        "--candidates",
        default="configs/monitoring_station_candidates.json",
    )
    parser.add_argument(
        "--output",
        default="configs/monitoring_stations_preview.json",
    )
    parser.add_argument("--waypoint-spacing", type=float, default=2.0)
    parser.add_argument("--marker-life", type=float, default=180.0)
    parser.add_argument(
        "--focus-seconds",
        type=float,
        default=6.0,
        help="Seconds to keep spectator focused on each station",
    )
    args = parser.parse_args()

    add_carla_paths(args.carla_root)
    import carla

    with open(args.candidates, "r", encoding="utf-8") as f:
        candidate_data = json.load(f)

    client = carla.Client(args.host, args.port)
    client.set_timeout(args.timeout)
    world = client.get_world()
    carla_map = world.get_map()
    spectator = world.get_spectator()

    map_name = str(carla_map.name).split("/")[-1]
    expected_map = candidate_data.get("map_id")
    if expected_map and map_name != expected_map:
        raise RuntimeError(
            "CARLA map mismatch: current={} candidates={}".format(
                map_name, expected_map
            )
        )

    all_waypoints = carla_map.generate_waypoints(args.waypoint_spacing)

    resolved = []
    preview_items = []

    for station in candidate_data.get("stations", []):
        road_id = int(station["road_id"])
        lane_id = int(station["lane_id"])

        matches = [
            wp for wp in all_waypoints
            if int(wp.road_id) == road_id and int(wp.lane_id) == lane_id
        ]
        wp = choose_representative_waypoint(matches)

        if wp is None:
            print(
                "[MISS] {} road={} lane={} has no generated waypoint".format(
                    station["station_id"], road_id, lane_id
                )
            )
            continue

        draw_station(world, carla, station, wp, args.marker_life)

        tr = wp.transform
        loc = tr.location

        resolved_station = dict(station)
        resolved_station.update({
            "x": round(float(loc.x), 3),
            "y": round(float(loc.y), 3),
            "z": round(float(loc.z), 3),
            "road_yaw_deg": round(float(tr.rotation.yaw), 3),
            "placement_status": "CARLA_WAYPOINT_PREVIEWED",
            "matched_waypoint_count": len(matches),
        })
        resolved.append(resolved_station)
        preview_items.append((station, wp))

        print(
            "[OK] {} | road={} lane={} | xyz=({:.1f},{:.1f},{:.1f}) | yaw={:.1f} | samples={}".format(
                station["station_id"],
                road_id,
                lane_id,
                loc.x,
                loc.y,
                loc.z,
                tr.rotation.yaw,
                len(matches),
            )
        )

    output = {
        "schema_version": "1.0-monitoring-stations-preview",
        "map_id": map_name,
        "source_candidates": args.candidates,
        "stations": resolved,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("========================================")
    print("MONITORING V1A.1 CARLA PREVIEW")
    print("map      : {}".format(map_name))
    print("resolved : {}/{}".format(
        len(resolved), len(candidate_data.get("stations", []))
    ))
    print("output   : {}".format(args.output))
    print("Spectator will now jump to each station candidate.")
    print("ORANGE vertical mast + RED point = station")
    print("GREEN arrow = lane forward direction")
    print("========================================")

    if not preview_items:
        raise SystemExit("No station could be previewed.")

    for index, (station, wp) in enumerate(preview_items, 1):
        # Redraw just before focusing to make sure it is visible.
        draw_station(world, carla, station, wp, args.marker_life)
        focus_spectator(carla, spectator, wp.transform)

        print(
            "[FOCUS {}/{}] {} | road={} lane={} | watch CARLA window for {:.1f}s".format(
                index,
                len(preview_items),
                station["station_id"],
                station["road_id"],
                station["lane_id"],
                args.focus_seconds,
            )
        )
        time.sleep(max(0.5, args.focus_seconds))

    print("[DONE] All station candidates were focused once.")


if __name__ == "__main__":
    main()
