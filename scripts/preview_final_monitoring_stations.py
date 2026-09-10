#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Preview FINAL monitoring stations selected by Monitoring V1A.2.

- moves spectator to each final station
- draws a tall marker
- draws lane-forward arrow
- does not spawn RGB camera sensors yet
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
    raise RuntimeError(
        "CARLA Python 3.7 egg not found under {}".format(dist_dir)
    )


def focus_spectator(carla, spectator, station):
    yaw = float(station["road_yaw_deg"])
    yaw_rad = math.radians(yaw)

    x = float(station["x"])
    y = float(station["y"])
    z = float(station["z"])

    spectator.set_transform(
        carla.Transform(
            carla.Location(
                x=x - math.cos(yaw_rad) * 24.0,
                y=y - math.sin(yaw_rad) * 24.0,
                z=z + 13.0,
            ),
            carla.Rotation(
                pitch=-22.0,
                yaw=yaw,
                roll=0.0,
            ),
        )
    )


def draw_station(world, carla, station, life_time):
    x = float(station["x"])
    y = float(station["y"])
    z = float(station["z"])
    yaw = float(station["road_yaw_deg"])
    yaw_rad = math.radians(yaw)

    base = carla.Location(x=x, y=y, z=z + 0.5)
    top = carla.Location(x=x, y=y, z=z + 10.0)
    label = carla.Location(x=x, y=y, z=z + 11.5)

    world.debug.draw_line(
        base,
        top,
        thickness=0.25,
        color=carla.Color(255, 140, 0),
        life_time=life_time,
        persistent_lines=False,
    )
    world.debug.draw_point(
        top,
        size=0.8,
        color=carla.Color(255, 60, 30),
        life_time=life_time,
        persistent_lines=False,
    )

    world.debug.draw_string(
        label,
        "{} | R{} L{} | haul={} | +haul={}".format(
            station["station_id"],
            station["road_id"],
            station["lane_id"],
            station["haul_route_coverage_count"],
            station["marginal_haul_route_count"],
        ),
        draw_shadow=True,
        color=carla.Color(255, 255, 255),
        life_time=life_time,
        persistent_lines=False,
    )

    arrow_end = carla.Location(
        x=x + math.cos(yaw_rad) * 18.0,
        y=y + math.sin(yaw_rad) * 18.0,
        z=z + 1.2,
    )
    world.debug.draw_arrow(
        base,
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
        "--stations",
        default="configs/monitoring_stations.json",
    )
    parser.add_argument(
        "--carla-root",
        default="/home/xiaoa/carla/Dist/CARLA_Shipping_0.9.10-dirty/LinuxNoEditor",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--focus-seconds", type=float, default=8.0)
    parser.add_argument("--marker-life", type=float, default=180.0)
    args = parser.parse_args()

    add_carla_paths(args.carla_root)
    import carla

    with open(args.stations, "r", encoding="utf-8") as f:
        data = json.load(f)

    client = carla.Client(args.host, args.port)
    client.set_timeout(args.timeout)
    world = client.get_world()
    carla_map = world.get_map()
    spectator = world.get_spectator()

    current_map = str(carla_map.name).split("/")[-1]
    expected_map = data.get("map_id")
    if expected_map and current_map != expected_map:
        raise RuntimeError(
            "CARLA map mismatch: current={} stations={}".format(
                current_map,
                expected_map,
            )
        )

    stations = data.get("stations", [])
    if not stations:
        raise RuntimeError("No final stations found in {}".format(
            args.stations
        ))

    for station in stations:
        draw_station(
            world,
            carla,
            station,
            args.marker_life,
        )

    print("========================================")
    print("MONITORING V1A.2 FINAL STATION PREVIEW")
    print("map      : {}".format(current_map))
    print("stations : {}".format(len(stations)))
    print("========================================")

    for index, station in enumerate(stations, 1):
        draw_station(
            world,
            carla,
            station,
            args.marker_life,
        )
        focus_spectator(carla, spectator, station)

        print(
            "[FOCUS {}/{}] {} | road={} lane={} | "
            "new_haul={} | watch CARLA {:.1f}s".format(
                index,
                len(stations),
                station["station_id"],
                station["road_id"],
                station["lane_id"],
                station["marginal_haul_route_count"],
                args.focus_seconds,
            )
        )
        time.sleep(max(0.5, args.focus_seconds))

    print("[DONE] Final stations previewed.")


if __name__ == "__main__":
    main()
