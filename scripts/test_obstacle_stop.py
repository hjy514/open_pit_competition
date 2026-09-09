#!/usr/bin/env python3
"""CARLA physical obstacle-stop-resume test."""

from __future__ import print_function

import argparse
import math
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from open_pit_competition.simulation.carla_adapter import (
    CarlaAdapter,
    CarlaAdapterError,
)
from open_pit_competition.simulation.vehicle_behavior import (
    BehaviorContext,
    DrivingState,
    ObstacleSnapshot,
)

EGO_ID = "truck_ego"
OBSTACLE_ROLE = "physical_obstacle"


def fmt(value, digits=1):
    if value is None:
        return "-"
    return ("{:.%df}" % digits).format(value)


def actor_length(actor, fallback=8.5):
    try:
        return max(0.1, float(actor.bounding_box.extent.x) * 2.0)
    except Exception:
        return float(fallback)


def physical_gap_m(ego_snapshot, obstacle_actor):
    loc = obstacle_actor.get_transform().location
    dx = loc.x - ego_snapshot.x
    dy = loc.y - ego_snapshot.y
    dz = loc.z - ego_snapshot.z
    center_distance = math.sqrt(dx * dx + dy * dy + dz * dz)
    return max(
        0.0,
        center_distance
        - ego_snapshot.length_m * 0.5
        - actor_length(obstacle_actor) * 0.5,
    )


def destroy_actor(actor):
    if actor is None:
        return
    try:
        if getattr(actor, "is_alive", True):
            actor.destroy()
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--carla-root", default="/home/xiaoa/carla")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--map", default="0325_5")
    parser.add_argument("--ego-spawn", type=int, default=78)
    parser.add_argument("--obstacle-spawn", type=int, default=12)
    parser.add_argument("--destination", type=int, default=48)
    parser.add_argument("--ego-speed", type=float, default=18.0)
    parser.add_argument("--blueprint", default="vehicle.cat.cat")
    parser.add_argument("--obstacle-detection-distance", type=float, default=60.0)
    parser.add_argument("--stop-hold-duration", type=float, default=3.0)
    parser.add_argument("--max-runtime", type=float, default=90.0)
    parser.add_argument("--control-period", type=float, default=0.05)
    args = parser.parse_args()

    adapter = CarlaAdapter(
        carla_root=args.carla_root,
        host=args.host,
        port=args.port,
        timeout_seconds=20.0,
        map_name=args.map,
        load_map=False,
    )

    obstacle_actor = None
    seen_decelerate = False
    seen_obstacle_stop = False
    seen_resume = False
    seen_post_resume_motion = False
    obstacle_stop_started = None
    obstacle_cleared = False
    last_state = None
    tick_index = 0

    try:
        adapter.connect()
        world = adapter.world
        carla = adapter.carla
        spawn_points = world.get_map().get_spawn_points()

        for index, label in (
            (args.ego_spawn, "ego"),
            (args.obstacle_spawn, "obstacle"),
            (args.destination, "destination"),
        ):
            if not (0 <= index < len(spawn_points)):
                raise CarlaAdapterError(
                    "{} spawn point {} out of range 0..{}".format(
                        label, index, len(spawn_points) - 1
                    )
                )

        print()
        print("=" * 76)
        print("CARLA PHYSICAL OBSTACLE STOP / RESUME TEST")
        print("=" * 76)
        print("map               :", args.map)
        print("ego spawn         :", args.ego_spawn)
        print("obstacle spawn    :", args.obstacle_spawn)
        print("destination       :", args.destination)
        print("ego cruise speed  :", args.ego_speed, "km/h")
        print()

        library = world.get_blueprint_library()
        try:
            obstacle_bp = library.find(args.blueprint)
        except RuntimeError as exc:
            raise CarlaAdapterError(
                "Obstacle blueprint '{}' not found: {}".format(
                    args.blueprint, exc
                )
            )

        if obstacle_bp.has_attribute("role_name"):
            obstacle_bp.set_attribute("role_name", OBSTACLE_ROLE)

        obstacle_actor = world.try_spawn_actor(
            obstacle_bp,
            spawn_points[args.obstacle_spawn],
        )
        if obstacle_actor is None:
            raise CarlaAdapterError(
                "Failed to spawn physical obstacle at spawn point {}".format(
                    args.obstacle_spawn
                )
            )

        obstacle_actor.apply_control(
            carla.VehicleControl(
                throttle=0.0,
                brake=1.0,
                hand_brake=True,
            )
        )

        print(
            "[TEST] physical obstacle spawned | actor={} | spawn={}".format(
                obstacle_actor.id,
                args.obstacle_spawn,
            )
        )

        adapter.spawn_vehicle(
            vehicle_id=EGO_ID,
            spawn_point_index=args.ego_spawn,
            blueprint_id=args.blueprint,
            role_name=EGO_ID,
        )

        time.sleep(0.5)

        adapter.set_destination_spawn_point(
            vehicle_id=EGO_ID,
            spawn_point_index=args.destination,
            target_speed_kmh=args.ego_speed,
        )

        print("[TEST] ego started. Waiting for obstacle approach...")
        print()

        start = time.monotonic()

        while True:
            now = time.monotonic()
            elapsed = now - start

            if elapsed >= args.max_runtime:
                print()
                print("[TEST] maximum runtime reached")
                break

            ego = adapter.get_vehicle_snapshot(EGO_ID)

            obstacle_gap = None
            obstacle_items = ()

            if (
                obstacle_actor is not None
                and not obstacle_cleared
                and getattr(obstacle_actor, "is_alive", True)
            ):
                obstacle_gap = physical_gap_m(
                    ego,
                    obstacle_actor,
                )

                if obstacle_gap <= args.obstacle_detection_distance:
                    obstacle_items = (
                        ObstacleSnapshot(
                            obstacle_id="parked_truck",
                            distance_m=obstacle_gap,
                            speed_mps=0.0,
                            in_path=True,
                        ),
                    )

            context = BehaviorContext(
                cruise_speed_kmh=args.ego_speed,
                obstacles=obstacle_items,
            )

            decision = adapter.step_vehicle(
                EGO_ID,
                context=context,
            )

            if decision.state == DrivingState.DECELERATE:
                seen_decelerate = True

            if decision.state == DrivingState.OBSTACLE_STOP:
                if not seen_obstacle_stop:
                    print()
                    print("[TEST] OBSTACLE_STOP detected.")
                seen_obstacle_stop = True
                if obstacle_stop_started is None:
                    obstacle_stop_started = now

            if (
                seen_obstacle_stop
                and not obstacle_cleared
                and obstacle_stop_started is not None
                and now - obstacle_stop_started >= args.stop_hold_duration
            ):
                print()
                print("[TEST] Clearing physical obstacle.")
                destroy_actor(obstacle_actor)
                obstacle_actor = None
                obstacle_cleared = True

            if (
                obstacle_cleared
                and decision.state == DrivingState.RESUME
            ):
                if not seen_resume:
                    print()
                    print("[TEST] RESUME detected.")
                seen_resume = True

            if (
                seen_resume
                and ego.speed_mps * 3.6 >= 3.0
                and decision.state in {
                    DrivingState.CRUISE,
                    DrivingState.RESUME,
                }
            ):
                seen_post_resume_motion = True

            if decision.state != last_state:
                print(
                    "[STATE] {:.1f}s | {} | reason={}".format(
                        elapsed,
                        decision.state.value,
                        decision.reason,
                    )
                )
                last_state = decision.state

            if tick_index % 10 == 0:
                print(
                    "[{:6.1f}s] "
                    "ego={:5.1f} km/h | "
                    "state={:<15} | "
                    "target={:5.1f} | "
                    "obstacle_gap={:>6} m | "
                    "safe={:>6} m | "
                    "ttc={:>5} s".format(
                        elapsed,
                        ego.speed_mps * 3.6,
                        decision.state.value,
                        decision.target_speed_kmh,
                        fmt(
                            decision.obstacle_distance_m
                            if decision.obstacle_distance_m is not None
                            else obstacle_gap
                        ),
                        fmt(decision.safe_gap_m),
                        fmt(decision.ttc_s),
                    )
                )

            tick_index += 1

            if (
                seen_decelerate
                and seen_obstacle_stop
                and seen_resume
                and seen_post_resume_motion
            ):
                print()
                print("[TEST] Complete obstacle state chain observed.")
                break

            time.sleep(args.control_period)

        print()
        print("=" * 76)
        print("TEST RESULT")
        print("=" * 76)
        print(
            "DECELERATE     : {}".format(
                "PASS" if seen_decelerate else "FAIL"
            )
        )
        print(
            "OBSTACLE_STOP  : {}".format(
                "PASS" if seen_obstacle_stop else "FAIL"
            )
        )
        print(
            "RESUME         : {}".format(
                "PASS" if seen_resume else "FAIL"
            )
        )
        print(
            "POST-RESUME    : {}".format(
                "PASS" if seen_post_resume_motion else "FAIL"
            )
        )
        print("=" * 76)

        success = (
            seen_decelerate
            and seen_obstacle_stop
            and seen_resume
            and seen_post_resume_motion
        )

        if success:
            print()
            print("RESULT: PHYSICAL OBSTACLE STOP / RESUME TEST PASSED")
            return 0

        print()
        print("RESULT: TEST DID NOT COMPLETE THE EXPECTED STATE CHAIN")
        return 1

    except CarlaAdapterError as exc:
        print()
        print("[CARLA ERROR]", exc)
        return 2

    except KeyboardInterrupt:
        print()
        print("[TEST] interrupted by user")
        return 130

    finally:
        destroy_actor(obstacle_actor)

        try:
            adapter.close()
        except Exception:
            pass

        try:
            destroyed = adapter.destroy_spawned_vehicles()
            print(
                "[CLEANUP] destroyed controlled vehicles: {}".format(
                    destroyed
                )
            )
        except Exception as exc:
            print("[CLEANUP WARNING]", exc)


if __name__ == "__main__":
    raise SystemExit(main())
