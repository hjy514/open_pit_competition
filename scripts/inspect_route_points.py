#!/usr/bin/env python3

from __future__ import print_function

import argparse
import math
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


from open_pit_competition.simulation.carla_adapter import (
    CarlaAdapter,
    CarlaAdapterError,
)


def angle_diff_deg(a, b):
    diff = (a - b + 180.0) % 360.0 - 180.0
    return abs(diff)


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--carla-root",
        default="/home/xiaoa/carla",
    )

    parser.add_argument(
        "--map",
        default="0325_5",
    )

    parser.add_argument(
        "--points",
        nargs="+",
        type=int,
        default=[78, 12, 49, 48],
    )

    args = parser.parse_args()


    adapter = CarlaAdapter(
        carla_root=args.carla_root,
        map_name=args.map,
        load_map=False,
        timeout_seconds=20.0,
    )


    try:

        adapter.connect()

        carla_map = adapter.world.get_map()

        spawn_points = carla_map.get_spawn_points()

        print()
        print("=" * 100)
        print("SPAWN POINT INSPECTION")
        print("=" * 100)

        infos = {}


        for index in args.points:

            if index < 0 or index >= len(spawn_points):

                print(
                    "spawn {}: OUT OF RANGE".format(index)
                )

                continue


            transform = spawn_points[index]

            loc = transform.location

            yaw = transform.rotation.yaw


            waypoint = carla_map.get_waypoint(loc)


            road_id = None
            lane_id = None
            s = None


            if waypoint is not None:

                road_id = waypoint.road_id
                lane_id = waypoint.lane_id

                s = getattr(
                    waypoint,
                    "s",
                    None,
                )


            infos[index] = {
                "x": loc.x,
                "y": loc.y,
                "z": loc.z,
                "yaw": yaw,
                "road_id": road_id,
                "lane_id": lane_id,
                "s": s,
            }


            print(
                "spawn {:>3}: "
                "x={:>9.2f} "
                "y={:>9.2f} "
                "z={:>7.2f} "
                "yaw={:>7.2f} "
                "road={} "
                "lane={} "
                "s={}".format(
                    index,
                    loc.x,
                    loc.y,
                    loc.z,
                    yaw,
                    road_id,
                    lane_id,
                    "{:.2f}".format(s)
                    if s is not None
                    else "-",
                )
            )


        print()
        print("=" * 100)
        print("PAIR RELATIONSHIPS")
        print("=" * 100)


        for i in range(len(args.points) - 1):

            a_index = args.points[i]
            b_index = args.points[i + 1]


            if (
                a_index not in infos
                or b_index not in infos
            ):
                continue


            a = infos[a_index]
            b = infos[b_index]


            dx = b["x"] - a["x"]
            dy = b["y"] - a["y"]
            dz = b["z"] - a["z"]


            distance = math.sqrt(
                dx * dx
                + dy * dy
                + dz * dz
            )


            heading_x = math.cos(
                math.radians(a["yaw"])
            )

            heading_y = math.sin(
                math.radians(a["yaw"])
            )


            horizontal_distance = math.sqrt(
                dx * dx + dy * dy
            )


            if horizontal_distance > 1e-6:

                forward_cos = (
                    dx * heading_x
                    + dy * heading_y
                ) / horizontal_distance

            else:

                forward_cos = 1.0


            yaw_diff = angle_diff_deg(
                a["yaw"],
                b["yaw"],
            )


            print(
                "{} -> {}: "
                "distance={:.2f} m | "
                "dz={:.2f} m | "
                "yaw_diff={:.2f} deg | "
                "forward_cos={:.3f} | "
                "same_road={} | "
                "same_lane={}".format(
                    a_index,
                    b_index,
                    distance,
                    dz,
                    yaw_diff,
                    forward_cos,
                    a["road_id"] == b["road_id"],
                    a["lane_id"] == b["lane_id"],
                )
            )


        print()
        print("=" * 100)


    except CarlaAdapterError as exc:

        print(
            "[CARLA ERROR]",
            exc,
        )

        return 1


    return 0


if __name__ == "__main__":
    raise SystemExit(main())
