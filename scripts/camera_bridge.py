# -*- coding: utf-8 -*-
"""Read-only display camera bridge for the PyQt dispatch center.

The bridge runs in the Python 3.7 CARLA environment. It finds CAT vehicles by
their CARLA role_name (truck_1 ... truck_6), attaches one RGB display camera to
each live CAT, and writes latest PNG frames for the desktop UI.

It never controls or destroys CAT vehicles and never changes Decision routes.
"""

from __future__ import annotations

import argparse
import fcntl
import glob
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


DEFAULT_CONFIG = "configs/dashboard_camera_bridge.json"
DEFAULT_OUTPUT = "runtime_data/monitoring/dashboard_cameras"


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def target_role_names(config: Dict[str, Any]) -> List[str]:
    values = config.get("vehicle_ids") or []
    return [str(value) for value in values if str(value).strip()]


def frame_path(output_dir: Path, vehicle_id: str) -> Path:
    return output_dir / "{}_latest.png".format(str(vehicle_id))


def _candidate_carla_roots(project_root: Path, system: Dict[str, Any]) -> List[Path]:
    roots = []
    raw = str(system.get("carla_root") or "").strip()
    if raw:
        roots.append(Path(raw).expanduser())

    roots.extend(
        [
            Path("/home/xiaoa/carla"),
            Path("/home/xiaoa/carla/Dist/CARLA_Shipping_0.9.10-dirty/LinuxNoEditor"),
        ]
    )

    unique = []
    seen = set()
    for root in roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        unique.append(root)
    return unique


def add_carla_python_paths(project_root: Path, system: Dict[str, Any]) -> None:
    candidates = []

    for root in _candidate_carla_roots(project_root, system):
        candidates.extend(
            [
                root / "PythonAPI/carla",
                root / "PythonAPI",
                root / "Dist/CARLA_Shipping_0.9.10-dirty/LinuxNoEditor/PythonAPI/carla",
                root / "Dist/CARLA_Shipping_0.9.10-dirty/LinuxNoEditor/PythonAPI",
            ]
        )

        patterns = [
            root / "PythonAPI/carla/dist/carla-0.9.10-py3.7-linux-x86_64.egg",
            root / "Dist/CARLA_Shipping_0.9.10-dirty/LinuxNoEditor/PythonAPI/carla/dist/carla-0.9.10-py3.7-linux-x86_64.egg",
        ]
        for pattern in patterns:
            candidates.append(pattern)

    for path in candidates:
        text = str(path)
        if path.exists() and text not in sys.path:
            sys.path.insert(0, text)


def _role_name(actor: Any) -> str:
    try:
        return str(actor.attributes.get("role_name") or "")
    except Exception:
        return ""


def find_target_vehicles(world: Any, roles: Iterable[str]) -> Dict[str, Any]:
    wanted = set(str(role) for role in roles)
    result = {}
    for actor in world.get_actors().filter("vehicle.*"):
        role = _role_name(actor)
        if role in wanted and bool(getattr(actor, "is_alive", True)):
            result[role] = actor
    return result


def adaptive_chase_transform(
    carla: Any,
    actor: Any,
    options: Dict[str, Any],
) -> Any:
    """Match the proven chase-camera rule used by the old project.

    Mine trucks are much larger than passenger cars, so the camera distance
    and height are derived from the real actor bounding box instead of using
    a fixed close offset.
    """
    bounding_box = getattr(actor, "bounding_box", None)
    extent = getattr(bounding_box, "extent", None)

    half_length = float(getattr(extent, "x", 0.0))
    half_height = float(getattr(extent, "z", 0.0))

    min_distance = float(options.get("min_follow_distance_m", 20.0))
    extra_distance = float(options.get("extra_follow_distance_m", 8.0))
    min_height = float(options.get("min_height_m", 10.0))
    extra_height = float(options.get("extra_height_m", 7.0))

    follow_distance = max(
        min_distance,
        half_length * 2.0 + extra_distance,
    )
    camera_height = max(
        min_height,
        half_height + extra_height,
    )

    return carla.Transform(
        carla.Location(
            x=-follow_distance,
            y=0.0,
            z=camera_height,
        ),
        carla.Rotation(
            pitch=float(options.get("pitch", -16.0)),
            yaw=float(options.get("yaw", 0.0)),
            roll=float(options.get("roll", 0.0)),
        ),
    )


class CameraBridge:
    def __init__(
        self,
        project_root: Path,
        config_path: Path,
        output_dir: Path,
    ) -> None:
        self.project_root = project_root.resolve()
        self.config_path = config_path.resolve()
        self.output_dir = output_dir.resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.config = load_json(self.config_path)
        self.system = load_json(self.project_root / "configs/system.json")
        self.roles = target_role_names(self.config)

        self.carla = None
        self.client = None
        self.world = None
        self.sensors = {}       # role -> sensor
        self.parent_actor_ids = {}  # role -> vehicle actor id
        self.stop_requested = False

        self.status_path = self.output_dir / "bridge_status.json"

    def request_stop(self, *_args: Any) -> None:
        self.stop_requested = True

    def _write_json_atomic(self, path: Path, payload: Dict[str, Any]) -> None:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(str(tmp), str(path))

    def _write_status(
        self,
        connected: bool,
        attached: int = 0,
        error: Optional[str] = None,
    ) -> None:
        self._write_json_atomic(
            self.status_path,
            {
                "connected": bool(connected),
                "attached": int(attached),
                "target_count": len(self.roles),
                "vehicle_ids": list(self.roles),
                "fps": float(self.config.get("fps", 4.0)),
                "updated_at_unix": time.time(),
                "error": error,
            },
        )

    def _save_frame(self, image: Any, vehicle_id: str) -> None:
        try:
            final_path = frame_path(self.output_dir, vehicle_id)
            tmp_path = self.output_dir / "{}_next.png".format(vehicle_id)
            image.save_to_disk(str(tmp_path))
            os.replace(str(tmp_path), str(final_path))
        except Exception:
            # Sensor callback must never interrupt CARLA control execution.
            return

    def _connect(self) -> None:
        add_carla_python_paths(self.project_root, self.system)
        import carla  # type: ignore

        self.carla = carla
        host = str(self.system.get("host", "127.0.0.1"))
        port = int(self.system.get("port", 2000))
        timeout = min(float(self.system.get("timeout_seconds", 20.0)), 4.0)

        client = carla.Client(host, port)
        client.set_timeout(timeout)
        world = client.get_world()

        self.client = client
        self.world = world

        print(
            "[CAMERA BRIDGE] connected {}:{} | map={}".format(
                host,
                port,
                str(world.get_map().name).split("/")[-1],
            ),
            flush=True,
        )

    def _destroy_sensor(self, role: str) -> None:
        sensor = self.sensors.pop(role, None)
        self.parent_actor_ids.pop(role, None)
        if sensor is None:
            return
        try:
            sensor.stop()
        except Exception:
            pass
        try:
            if bool(getattr(sensor, "is_alive", False)):
                sensor.destroy()
        except Exception:
            pass

    def _destroy_all_sensors(self) -> None:
        for role in list(self.sensors):
            self._destroy_sensor(role)

    def _sensor_is_valid(self, role: str, vehicle: Any) -> bool:
        sensor = self.sensors.get(role)
        if sensor is None:
            return False
        if self.parent_actor_ids.get(role) != int(vehicle.id):
            return False
        try:
            return bool(sensor.is_alive)
        except Exception:
            return False

    def _spawn_camera(self, role: str, vehicle: Any) -> bool:
        assert self.world is not None
        assert self.carla is not None

        library = self.world.get_blueprint_library()
        blueprint = library.find("sensor.camera.rgb")

        width = int(self.config.get("image_width", 640))
        height = int(self.config.get("image_height", 360))
        fov = float(self.config.get("fov", 90.0))
        fps = max(0.5, float(self.config.get("fps", 4.0)))

        blueprint.set_attribute("image_size_x", str(width))
        blueprint.set_attribute("image_size_y", str(height))
        blueprint.set_attribute("fov", str(fov))
        if blueprint.has_attribute("sensor_tick"):
            blueprint.set_attribute("sensor_tick", str(1.0 / fps))
        if blueprint.has_attribute("role_name"):
            blueprint.set_attribute(
                "role_name",
                "dashboard_camera_{}".format(role),
            )

        camera_options = self.config.get("vehicle_camera") or {}
        transform = adaptive_chase_transform(
            self.carla,
            vehicle,
            camera_options,
        )

        try:
            sensor = self.world.try_spawn_actor(
                blueprint,
                transform,
                attach_to=vehicle,
            )
        except TypeError:
            # Compatibility with older PythonAPI bindings.
            sensor = self.world.try_spawn_actor(
                blueprint,
                transform,
                vehicle,
            )

        if sensor is None:
            print(
                "[CAMERA BRIDGE] failed to attach {}".format(role),
                flush=True,
            )
            return False

        sensor.listen(
            lambda image, vehicle_id=role: self._save_frame(
                image,
                vehicle_id,
            )
        )

        self.sensors[role] = sensor
        self.parent_actor_ids[role] = int(vehicle.id)

        location = transform.location
        rotation = transform.rotation
        print(
            "[CAMERA BRIDGE] attached {} | vehicle_actor={} | sensor_actor={} "
            "| chase x={:.1f} z={:.1f} pitch={:.1f}".format(
                role,
                vehicle.id,
                sensor.id,
                float(location.x),
                float(location.z),
                float(rotation.pitch),
            ),
            flush=True,
        )
        return True

    def _sync_sensors(self) -> int:
        assert self.world is not None
        vehicles = find_target_vehicles(self.world, self.roles)

        # Remove cameras whose CAT disappeared / was recreated.
        for role in list(self.sensors):
            vehicle = vehicles.get(role)
            if vehicle is None or not self._sensor_is_valid(role, vehicle):
                self._destroy_sensor(role)

        # Attach to newly spawned CATs.
        for role in self.roles:
            vehicle = vehicles.get(role)
            if vehicle is None:
                continue
            if self._sensor_is_valid(role, vehicle):
                continue
            self._spawn_camera(role, vehicle)

        return sum(
            1
            for role, sensor in self.sensors.items()
            if bool(getattr(sensor, "is_alive", False))
        )

    def run(self) -> int:
        reconnect_interval = max(
            0.5,
            float(self.config.get("reconnect_interval_s", 2.0)),
        )
        scan_interval = max(
            0.1,
            float(self.config.get("scan_interval_s", 0.5)),
        )

        signal.signal(signal.SIGINT, self.request_stop)
        signal.signal(signal.SIGTERM, self.request_stop)

        while not self.stop_requested:
            try:
                if self.world is None:
                    self._connect()

                attached = self._sync_sensors()
                self._write_status(
                    connected=True,
                    attached=attached,
                )
                time.sleep(scan_interval)
            except KeyboardInterrupt:
                self.stop_requested = True
            except Exception as exc:
                message = "{}: {}".format(type(exc).__name__, exc)
                print(
                    "[CAMERA BRIDGE] reconnect after error | {}".format(
                        message
                    ),
                    flush=True,
                )
                self._write_status(
                    connected=False,
                    attached=0,
                    error=message,
                )
                self._destroy_all_sensors()
                self.client = None
                self.world = None

                end = time.time() + reconnect_interval
                while time.time() < end and not self.stop_requested:
                    time.sleep(0.1)

        self._destroy_all_sensors()
        self._write_status(
            connected=False,
            attached=0,
            error=None,
        )
        print("[CAMERA BRIDGE] stopped", flush=True)
        return 0


def acquire_single_instance_lock(output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    lock_path = output_dir / ".camera_bridge.lock"
    handle = lock_path.open("w")
    try:
        fcntl.flock(
            handle.fileno(),
            fcntl.LOCK_EX | fcntl.LOCK_NB,
        )
    except OSError:
        handle.close()
        return None

    handle.write(str(os.getpid()))
    handle.flush()
    return handle


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]
    config_path = (project_root / args.config).resolve()
    output_dir = (project_root / args.output).resolve()

    lock = acquire_single_instance_lock(output_dir)
    if lock is None:
        print(
            "[CAMERA BRIDGE] another bridge is already running; exit.",
            flush=True,
        )
        return 0

    try:
        bridge = CameraBridge(
            project_root=project_root,
            config_path=config_path,
            output_dir=output_dir,
        )
        return bridge.run()
    finally:
        try:
            lock.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
