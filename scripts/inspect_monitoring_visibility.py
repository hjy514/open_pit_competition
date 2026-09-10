#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Monitoring V1A.3 - roadside environment / camera visibility inspection.

Reads:
    configs/monitoring_stations.json

For every final station it creates THREE TEMPORARY RGB camera viewpoints:
    left      : 8 m to the left of the monitored lane, 6.5 m above road anchor
    right     : 8 m to the right of the monitored lane, 6.5 m above road anchor
    overhead  : directly above road anchor, 10 m high

Each camera looks slightly forward along the monitored road so the resulting
image shows whether terrain, slope, rock walls, buildings or other roadside
objects block useful observation.

Important:
- only CARLA sensor.camera.rgb actors are spawned
- no vehicle / static prop / collision object is added
- cameras are destroyed immediately after each snapshot
- Runtime / VehicleBehavior / Decision are not touched

Output:
    runtime_data/monitoring_preview/
        station_road_01_left.png
        station_road_01_right.png
        station_road_01_overhead.png
        ...
        visibility_candidates.json
        monitoring_visibility_preview.zip
"""

import argparse
import glob
import json
import math
import os
import sys
import threading
import time
import zipfile
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
            egg = matches[-1]
            if egg not in sys.path:
                sys.path.insert(0, egg)
            return

    raise RuntimeError(
        "CARLA Python 3.7 egg not found under {}".format(dist_dir)
    )


def camera_position(station, placement, lateral_offset_m=8.0):
    x = float(station["x"])
    y = float(station["y"])
    z = float(station["z"])
    yaw_deg = float(station["road_yaw_deg"])
    yaw = math.radians(yaw_deg)

    # Left/right unit vector relative to lane-forward direction.
    left_x = -math.sin(yaw)
    left_y = math.cos(yaw)

    if placement == "left":
        return (
            x + left_x * lateral_offset_m,
            y + left_y * lateral_offset_m,
            z + 6.5,
        )

    if placement == "right":
        return (
            x - left_x * lateral_offset_m,
            y - left_y * lateral_offset_m,
            z + 6.5,
        )

    if placement == "overhead":
        return (x, y, z + 10.0)

    raise ValueError("unsupported placement: {}".format(placement))


def observation_target(station, forward_m=18.0):
    x = float(station["x"])
    y = float(station["y"])
    z = float(station["z"])
    yaw = math.radians(float(station["road_yaw_deg"]))

    return (
        x + math.cos(yaw) * forward_m,
        y + math.sin(yaw) * forward_m,
        z + 1.0,
    )


def look_at_rotation(source_xyz, target_xyz):
    sx, sy, sz = source_xyz
    tx, ty, tz = target_xyz

    dx = tx - sx
    dy = ty - sy
    dz = tz - sz

    horizontal = math.sqrt(dx * dx + dy * dy)
    yaw = math.degrees(math.atan2(dy, dx))
    pitch = math.degrees(math.atan2(dz, horizontal))

    return pitch, yaw


def make_camera_transform(carla, station, placement, lateral_offset_m):
    source = camera_position(
        station,
        placement,
        lateral_offset_m=lateral_offset_m,
    )
    target = observation_target(station)
    pitch, yaw = look_at_rotation(source, target)

    return carla.Transform(
        carla.Location(
            x=source[0],
            y=source[1],
            z=source[2],
        ),
        carla.Rotation(
            pitch=pitch,
            yaw=yaw,
            roll=0.0,
        ),
    )


def capture_one(
    world,
    carla,
    camera_bp,
    transform,
    output_path,
    timeout_seconds,
):
    sensor = None
    done = threading.Event()
    error_box = []

    def callback(image):
        if done.is_set():
            return
        try:
            image.save_to_disk(str(output_path))
        except Exception as exc:
            error_box.append(exc)
        finally:
            done.set()

    try:
        sensor = world.spawn_actor(camera_bp, transform)
        sensor.listen(callback)

        if not done.wait(timeout_seconds):
            raise RuntimeError(
                "Timed out waiting for RGB frame: {}".format(output_path)
            )

        if error_box:
            raise RuntimeError(
                "Failed to save RGB frame {}: {}".format(
                    output_path,
                    error_box[0],
                )
            )

    finally:
        if sensor is not None:
            try:
                sensor.stop()
            except Exception:
                pass
            try:
                sensor.destroy()
            except Exception:
                pass


def as_transform_dict(transform):
    return {
        "x": round(float(transform.location.x), 3),
        "y": round(float(transform.location.y), 3),
        "z": round(float(transform.location.z), 3),
        "pitch": round(float(transform.rotation.pitch), 3),
        "yaw": round(float(transform.rotation.yaw), 3),
        "roll": round(float(transform.rotation.roll), 3),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stations",
        default="configs/monitoring_stations.json",
    )
    parser.add_argument(
        "--output-dir",
        default="runtime_data/monitoring_preview",
    )
    parser.add_argument(
        "--carla-root",
        default="/home/xiaoa/carla/Dist/CARLA_Shipping_0.9.10-dirty/LinuxNoEditor",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--frame-timeout", type=float, default=5.0)
    parser.add_argument("--lateral-offset-m", type=float, default=8.0)
    parser.add_argument("--image-width", type=int, default=800)
    parser.add_argument("--image-height", type=int, default=450)
    parser.add_argument("--fov", type=float, default=90.0)
    args = parser.parse_args()

    add_carla_paths(args.carla_root)
    import carla

    with open(args.stations, "r", encoding="utf-8") as f:
        station_data = json.load(f)

    client = carla.Client(args.host, args.port)
    client.set_timeout(args.timeout)
    world = client.get_world()
    carla_map = world.get_map()

    current_map = str(carla_map.name).split("/")[-1]
    expected_map = station_data.get("map_id")
    if expected_map and current_map != expected_map:
        raise RuntimeError(
            "CARLA map mismatch: current={} stations={}".format(
                current_map,
                expected_map,
            )
        )

    bp_library = world.get_blueprint_library()
    camera_bp = bp_library.find("sensor.camera.rgb")
    camera_bp.set_attribute("image_size_x", str(args.image_width))
    camera_bp.set_attribute("image_size_y", str(args.image_height))
    camera_bp.set_attribute("fov", str(args.fov))
    if camera_bp.has_attribute("sensor_tick"):
        camera_bp.set_attribute("sensor_tick", "0.1")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results = []

    print("========================================")
    print("MONITORING V1A.3 VISIBILITY INSPECTION")
    print("map       : {}".format(current_map))
    print("stations  : {}".format(len(station_data.get("stations", []))))
    print("views     : left / right / overhead")
    print("important : temporary RGB sensors only; no physical obstacle")
    print("========================================")

    for station in station_data.get("stations", []):
        station_id = str(station["station_id"])

        for placement in ("left", "right", "overhead"):
            transform = make_camera_transform(
                carla,
                station,
                placement,
                args.lateral_offset_m,
            )

            filename = "{}_{}.png".format(station_id, placement)
            output_path = output_dir / filename

            print(
                "[CAPTURE] {} {:8s} xyz=({:.1f},{:.1f},{:.1f}) "
                "pitch={:.1f} yaw={:.1f}".format(
                    station_id,
                    placement,
                    transform.location.x,
                    transform.location.y,
                    transform.location.z,
                    transform.rotation.pitch,
                    transform.rotation.yaw,
                )
            )

            capture_one(
                world,
                carla,
                camera_bp,
                transform,
                output_path,
                args.frame_timeout,
            )

            results.append({
                "station_id": station_id,
                "placement": placement,
                "monitored_road_id": station["road_id"],
                "monitored_lane_id": station["lane_id"],
                "road_anchor": {
                    "x": station["x"],
                    "y": station["y"],
                    "z": station["z"],
                    "road_yaw_deg": station["road_yaw_deg"],
                },
                "camera_transform": as_transform_dict(transform),
                "image_file": filename,
                "review_status": "REQUIRES_VISUAL_REVIEW",
            })

            # Give CARLA a brief moment after actor destruction before the
            # next temporary camera is spawned.
            time.sleep(0.15)

    manifest = {
        "schema_version": "1.0-monitoring-visibility-preview",
        "map_id": current_map,
        "source_stations": args.stations,
        "camera_policy": {
            "temporary_sensor_only": True,
            "physical_station_actor_spawned": False,
            "lateral_offset_m": args.lateral_offset_m,
            "side_camera_height_above_anchor_m": 6.5,
            "overhead_camera_height_above_anchor_m": 10.0,
            "observation_target_forward_m": 18.0,
            "image_width": args.image_width,
            "image_height": args.image_height,
            "fov_deg": args.fov,
        },
        "candidates": results,
    }

    manifest_path = output_dir / "visibility_candidates.json"
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    zip_path = output_dir / "monitoring_visibility_preview.zip"
    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(
        str(zip_path),
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as zf:
        zf.write(
            str(manifest_path),
            arcname=manifest_path.name,
        )
        for item in results:
            image_path = output_dir / item["image_file"]
            zf.write(
                str(image_path),
                arcname=image_path.name,
            )

    print("----------------------------------------")
    print("captured images : {}".format(len(results)))
    print("manifest        : {}".format(manifest_path))
    print("review zip      : {}".format(zip_path))
    print("----------------------------------------")
    print("Review each station's LEFT / RIGHT / OVERHEAD image.")
    print("Choose the view with:")
    print("  - longest useful visible road section")
    print("  - least slope / rock / building obstruction")
    print("  - clear view of CAT trucks")
    print("  - no need for any physical roadside obstacle")
    print("========================================")


if __name__ == "__main__":
    main()
