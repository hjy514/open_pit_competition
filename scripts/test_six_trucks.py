#!/usr/bin/env python3
"""CARLA six-truck continuous-following test v3.

This version focuses on separating two questions:

1. Can all six trucks actually be released and run?
2. When an immediate predecessor is physically nearby, does the rear
   truck select it as the front vehicle?

Changes from v2:
- sequential rear-spawn clearance: 25 m instead of 35 m
- leader speed: 12 km/h
- trucks 2..6: 14 km/h
- 3.5 m dangerous-gap threshold
- geometry diagnostics when an expected predecessor is nearby but
  not selected
- explicit spawn diagnostics, so a non-spawned truck cannot be
  confused with a front-detection failure
"""

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
)


TRUCK_IDS = [
    "truck_1",
    "truck_2",
    "truck_3",
    "truck_4",
    "truck_5",
    "truck_6",
]


FOLLOWING_STATES = {
    DrivingState.FOLLOW,
    DrivingState.DECELERATE,
    DrivingState.WAIT_FRONT,
    DrivingState.RESUME,
}


def fmt(value, digits=1):
    if value is None:
        return "-"
    return ("{:.%df}" % digits).format(value)


def horizontal_distance_xy(x1, y1, x2, y2):
    dx = x2 - x1
    dy = y2 - y1
    return math.sqrt(dx * dx + dy * dy)


def center_distance(a, b):
    dx = b.x - a.x
    dy = b.y - a.y
    dz = b.z - a.z
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def approximate_bumper_gap(a, b):
    return (
        center_distance(a, b)
        - 0.5 * a.length_m
        - 0.5 * b.length_m
    )


def expected_front_geometry(ego, front):
    dx = front.x - ego.x
    dy = front.y - ego.y
    dz = front.z - ego.z

    horizontal = math.sqrt(dx * dx + dy * dy)
    center = math.sqrt(dx * dx + dy * dy + dz * dz)

    yaw = math.radians(ego.yaw_deg)
    fx = math.cos(yaw)
    fy = math.sin(yaw)
    lx = -fy
    ly = fx

    longitudinal = dx * fx + dy * fy
    lateral = abs(dx * lx + dy * ly)

    if horizontal > 1e-6:
        forward_cos = longitudinal / horizontal
    else:
        forward_cos = 0.0

    front_yaw = math.radians(front.yaw_deg)
    ffx = math.cos(front_yaw)
    ffy = math.sin(front_yaw)

    heading_cos = fx * ffx + fy * ffy

    return {
        "center": center,
        "horizontal": horizontal,
        "dz": dz,
        "longitudinal": longitudinal,
        "lateral": lateral,
        "forward_cos": forward_cos,
        "heading_cos": heading_cos,
    }


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--carla-root",
        default="/home/xiaoa/carla",
    )

    parser.add_argument(
        "--host",
        default="127.0.0.1",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=2000,
    )

    parser.add_argument(
        "--map",
        default="0325_5",
    )

    parser.add_argument(
        "--leader-spawn",
        type=int,
        default=12,
    )

    parser.add_argument(
        "--rear-spawn",
        type=int,
        default=78,
    )

    parser.add_argument(
        "--destination",
        type=int,
        default=48,
    )

    parser.add_argument(
        "--blueprint",
        default="vehicle.cat.cat",
    )

    parser.add_argument(
        "--spawn-clearance",
        type=float,
        default=25.0,
    )

    parser.add_argument(
        "--leader-speed",
        type=float,
        default=12.0,
    )

    parser.add_argument(
        "--rear-speed",
        type=float,
        default=14.0,
    )

    parser.add_argument(
        "--required-relation-samples",
        type=int,
        default=3,
    )

    parser.add_argument(
        "--sustain-duration",
        type=float,
        default=12.0,
    )

    parser.add_argument(
        "--danger-gap",
        type=float,
        default=3.5,
    )

    parser.add_argument(
        "--max-runtime",
        type=float,
        default=130.0,
    )

    parser.add_argument(
        "--control-period",
        type=float,
        default=0.05,
    )

    parser.add_argument(
        "--diagnostic-period",
        type=float,
        default=2.0,
    )

    args = parser.parse_args()


    speeds = {
        "truck_1": args.leader_speed,
        "truck_2": args.rear_speed,
        "truck_3": args.rear_speed,
        "truck_4": args.rear_speed,
        "truck_5": args.rear_speed,
        "truck_6": args.rear_speed,
    }


    adapter = CarlaAdapter(
        carla_root=args.carla_root,
        host=args.host,
        port=args.port,
        timeout_seconds=20.0,
        map_name=args.map,
        load_map=False,
    )


    contexts = {
        vehicle_id: BehaviorContext(
            cruise_speed_kmh=speeds[vehicle_id]
        )
        for vehicle_id in TRUCK_IDS
    }


    spawned = {
        vehicle_id: False
        for vehicle_id in TRUCK_IDS
    }

    spawn_times = {
        vehicle_id: None
        for vehicle_id in TRUCK_IDS
    }

    moved = {
        vehicle_id: False
        for vehicle_id in TRUCK_IDS
    }


    relation_samples = {
        vehicle_id: 0
        for vehicle_id in TRUCK_IDS[1:]
    }

    relation_pass = {
        vehicle_id: False
        for vehicle_id in TRUCK_IDS[1:]
    }


    missed_expected_nearby = {
        vehicle_id: 0
        for vehicle_id in TRUCK_IDS[1:]
    }


    last_diag_time = {
        vehicle_id: -1e9
        for vehicle_id in TRUCK_IDS[1:]
    }


    min_neighbor_gaps = {
        (TRUCK_IDS[i], TRUCK_IDS[i + 1]): None
        for i in range(len(TRUCK_IDS) - 1)
    }


    state_transition_counts = {
        vehicle_id: 0
        for vehicle_id in TRUCK_IDS
    }


    last_states = {}

    wrong_front_detected = False
    dangerous_gap_detected = False
    emergency_seen = False

    next_spawn_index = 2
    all_relations_confirmed_at = None

    tick_index = 0


    try:

        adapter.connect()

        world = adapter.world
        spawn_points = world.get_map().get_spawn_points()


        for index, label in (
            (args.leader_spawn, "leader"),
            (args.rear_spawn, "rear"),
            (args.destination, "destination"),
        ):

            if not (0 <= index < len(spawn_points)):
                raise CarlaAdapterError(
                    "{} spawn point {} out of range 0..{}".format(
                        label,
                        index,
                        len(spawn_points) - 1,
                    )
                )


        rear_spawn_location = spawn_points[
            args.rear_spawn
        ].location


        print()
        print("=" * 92)
        print("CARLA SIX-TRUCK CONTINUOUS FOLLOWING TEST V3")
        print("=" * 92)
        print("map               :", args.map)
        print("leader spawn      :", args.leader_spawn)
        print("rear spawn        :", args.rear_spawn, "(sequential reuse)")
        print("destination       :", args.destination)
        print("spawn clearance   :", args.spawn_clearance, "m")
        print("leader speed      :", args.leader_speed, "km/h")
        print("rear speeds       :", args.rear_speed, "km/h")
        print("danger gap        :", args.danger_gap, "m")
        print()


        # --------------------------------------------------------
        # Initial two trucks
        # --------------------------------------------------------

        adapter.spawn_vehicle(
            vehicle_id="truck_1",
            spawn_point_index=args.leader_spawn,
            blueprint_id=args.blueprint,
            role_name="truck_1",
        )

        spawned["truck_1"] = True


        adapter.spawn_vehicle(
            vehicle_id="truck_2",
            spawn_point_index=args.rear_spawn,
            blueprint_id=args.blueprint,
            role_name="truck_2",
        )

        spawned["truck_2"] = True


        time.sleep(0.5)


        for vehicle_id in ("truck_1", "truck_2"):

            adapter.set_destination_spawn_point(
                vehicle_id=vehicle_id,
                spawn_point_index=args.destination,
                target_speed_kmh=speeds[vehicle_id],
            )


        start = time.monotonic()

        spawn_times["truck_1"] = 0.0
        spawn_times["truck_2"] = 0.0


        print("[TEST] truck_1 and truck_2 started.")
        print()


        # ========================================================
        # Main loop
        # ========================================================

        while True:

            now = time.monotonic()
            elapsed = now - start


            if elapsed >= args.max_runtime:
                print()
                print("[TEST] maximum runtime reached")
                break


            # ----------------------------------------------------
            # Spawn next truck when predecessor clears reusable
            # spawn point.
            # ----------------------------------------------------

            if next_spawn_index < len(TRUCK_IDS):

                previous_id = TRUCK_IDS[
                    next_spawn_index - 1
                ]

                previous_snapshot = adapter.get_vehicle_snapshot(
                    previous_id
                )

                cleared_distance = horizontal_distance_xy(
                    rear_spawn_location.x,
                    rear_spawn_location.y,
                    previous_snapshot.x,
                    previous_snapshot.y,
                )


                if cleared_distance >= args.spawn_clearance:

                    vehicle_id = TRUCK_IDS[
                        next_spawn_index
                    ]


                    print()
                    print(
                        "[SPAWN] {:.1f}s | {} cleared spawn by {:.1f} m".format(
                            elapsed,
                            previous_id,
                            cleared_distance,
                        )
                    )

                    print(
                        "[SPAWN] {:.1f}s | spawning {}".format(
                            elapsed,
                            vehicle_id,
                        )
                    )


                    adapter.spawn_vehicle(
                        vehicle_id=vehicle_id,
                        spawn_point_index=args.rear_spawn,
                        blueprint_id=args.blueprint,
                        role_name=vehicle_id,
                    )

                    spawned[vehicle_id] = True
                    spawn_times[vehicle_id] = elapsed


                    time.sleep(0.30)


                    adapter.set_destination_spawn_point(
                        vehicle_id=vehicle_id,
                        spawn_point_index=args.destination,
                        target_speed_kmh=speeds[vehicle_id],
                    )


                    next_spawn_index += 1


            # ----------------------------------------------------
            # Step all active vehicles
            # ----------------------------------------------------

            decisions = {}

            for vehicle_id in TRUCK_IDS:

                if not spawned[vehicle_id]:
                    continue

                decisions[vehicle_id] = adapter.step_vehicle(
                    vehicle_id,
                    context=contexts[vehicle_id],
                )


            snapshots = {}

            for vehicle_id in TRUCK_IDS:

                if not spawned[vehicle_id]:
                    continue

                snapshots[vehicle_id] = adapter.get_vehicle_snapshot(
                    vehicle_id
                )


            # ----------------------------------------------------
            # Movement confirmation
            # ----------------------------------------------------

            for vehicle_id, snapshot in snapshots.items():

                if snapshot.speed_mps * 3.6 >= 3.0:
                    moved[vehicle_id] = True


            # ----------------------------------------------------
            # Immediate predecessor validation + diagnostics
            # ----------------------------------------------------

            for index in range(1, len(TRUCK_IDS)):

                rear_id = TRUCK_IDS[index]
                expected_front_id = TRUCK_IDS[index - 1]


                if not spawned[rear_id]:
                    continue


                decision = decisions[rear_id]


                correct_relation = (
                    decision.front_vehicle_id
                    == expected_front_id
                    and
                    decision.state in FOLLOWING_STATES
                )


                if correct_relation:

                    relation_samples[rear_id] += 1

                    if (
                        relation_samples[rear_id]
                        >= args.required_relation_samples
                        and
                        not relation_pass[rear_id]
                    ):

                        relation_pass[rear_id] = True

                        print()
                        print(
                            "[TEST] {} -> {} relation confirmed.".format(
                                rear_id,
                                expected_front_id,
                            )
                        )


                else:

                    relation_samples[rear_id] = 0


                # Detect skipping over the immediate predecessor.
                selected = decision.front_vehicle_id

                if (
                    selected is not None
                    and selected != expected_front_id
                    and selected in TRUCK_IDS[:index - 1]
                ):

                    wrong_front_detected = True

                    print()
                    print(
                        "[FAIL] {} selected {} instead of immediate {}.".format(
                            rear_id,
                            selected,
                            expected_front_id,
                        )
                    )

                    break


                # Geometry diagnostics only when expected predecessor
                # is physically within normal detection range.
                if (
                    expected_front_id in snapshots
                    and rear_id in snapshots
                ):

                    ego_snap = snapshots[rear_id]
                    front_snap = snapshots[expected_front_id]

                    geom = expected_front_geometry(
                        ego_snap,
                        front_snap,
                    )


                    if (
                        geom["center"] <= 60.0
                        and
                        decision.front_vehicle_id != expected_front_id
                    ):

                        missed_expected_nearby[rear_id] += 1


                        if (
                            elapsed - last_diag_time[rear_id]
                            >= args.diagnostic_period
                        ):

                            last_diag_time[rear_id] = elapsed


                            print(
                                "[MISS] {:6.1f}s | {} expected={} selected={} "
                                "state={} | dist={:.1f} lon={:.1f} lat={:.1f} "
                                "dz={:.1f} fcos={:.3f} hcos={:.3f} "
                                "road={}/{} lane={}/{}".format(
                                    elapsed,
                                    rear_id,
                                    expected_front_id,
                                    decision.front_vehicle_id,
                                    decision.state.value,
                                    geom["center"],
                                    geom["longitudinal"],
                                    geom["lateral"],
                                    geom["dz"],
                                    geom["forward_cos"],
                                    geom["heading_cos"],
                                    ego_snap.road_id,
                                    front_snap.road_id,
                                    ego_snap.lane_id,
                                    front_snap.lane_id,
                                )
                            )


            if wrong_front_detected:
                break


            # ----------------------------------------------------
            # Emergency monitor
            # ----------------------------------------------------

            for vehicle_id, decision in decisions.items():

                if decision.state == DrivingState.EMERGENCY_STOP:

                    if not emergency_seen:

                        print()
                        print(
                            "[WARN] EMERGENCY_STOP observed."
                        )

                    emergency_seen = True


            # ----------------------------------------------------
            # Neighbor gap checks
            # ----------------------------------------------------

            for index in range(len(TRUCK_IDS) - 1):

                front_id = TRUCK_IDS[index]
                rear_id = TRUCK_IDS[index + 1]


                if (
                    front_id not in snapshots
                    or rear_id not in snapshots
                ):
                    continue


                gap = approximate_bumper_gap(
                    snapshots[front_id],
                    snapshots[rear_id],
                )

                key = (front_id, rear_id)

                old_min = min_neighbor_gaps[key]

                if old_min is None or gap < old_min:
                    min_neighbor_gaps[key] = gap


                if gap < args.danger_gap:

                    dangerous_gap_detected = True

                    print()
                    print(
                        "[FAIL] {} / {} approximate gap {:.2f} m < {:.2f} m.".format(
                            front_id,
                            rear_id,
                            gap,
                            args.danger_gap,
                        )
                    )

                    break


            if dangerous_gap_detected:
                break


            # ----------------------------------------------------
            # State transition logging
            # ----------------------------------------------------

            for vehicle_id, decision in decisions.items():

                previous_state = last_states.get(
                    vehicle_id
                )


                if previous_state != decision.state:

                    state_transition_counts[vehicle_id] += 1

                    print(
                        "[STATE] {:6.1f}s | {:7} | {:14} | front={} | reason={}".format(
                            elapsed,
                            vehicle_id,
                            decision.state.value,
                            decision.front_vehicle_id,
                            decision.reason,
                        )
                    )

                    last_states[vehicle_id] = decision.state


            # ----------------------------------------------------
            # Telemetry
            # ----------------------------------------------------

            if tick_index % 10 == 0:

                parts = []


                for vehicle_id in TRUCK_IDS:

                    if not spawned[vehicle_id]:

                        parts.append(
                            "{}=waiting".format(vehicle_id)
                        )

                        continue


                    snapshot = snapshots[vehicle_id]
                    decision = decisions[vehicle_id]


                    parts.append(
                        "{}:{:.1f} {} f={} g={}".format(
                            vehicle_id,
                            snapshot.speed_mps * 3.6,
                            decision.state.value,
                            decision.front_vehicle_id,
                            fmt(decision.front_gap_m),
                        )
                    )


                print(
                    "[{:6.1f}s] {}".format(
                        elapsed,
                        " | ".join(parts),
                    )
                )


            tick_index += 1


            # ----------------------------------------------------
            # Sustained run once all five relations are confirmed
            # ----------------------------------------------------

            if (
                all(spawned.values())
                and all(relation_pass.values())
            ):

                if all_relations_confirmed_at is None:

                    all_relations_confirmed_at = now

                    print()
                    print(
                        "[TEST] All five immediate-front relations confirmed."
                    )
                    print(
                        "[TEST] Starting {:.1f}s sustained run.".format(
                            args.sustain_duration
                        )
                    )


                elif (
                    now - all_relations_confirmed_at
                    >= args.sustain_duration
                ):

                    print()
                    print(
                        "[TEST] sustained six-truck run completed."
                    )

                    break


            time.sleep(args.control_period)


        # ========================================================
        # Result
        # ========================================================

        all_spawned_pass = all(spawned.values())
        all_moved_pass = all(moved.values())
        all_relations_pass = all(relation_pass.values())

        sustained_pass = (
            all_relations_confirmed_at is not None
            and
            time.monotonic() - all_relations_confirmed_at
            >= args.sustain_duration
        )


        print()
        print("=" * 92)
        print("TEST RESULT")
        print("=" * 92)

        print(
            "SIX SPAWNED         : {}".format(
                "PASS" if all_spawned_pass else "FAIL"
            )
        )

        print(
            "SIX MOVED           : {}".format(
                "PASS" if all_moved_pass else "FAIL"
            )
        )


        for index in range(1, len(TRUCK_IDS)):

            rear_id = TRUCK_IDS[index]
            front_id = TRUCK_IDS[index - 1]

            print(
                "{:<7} -> {:<7}: {}".format(
                    rear_id,
                    front_id,
                    "PASS" if relation_pass[rear_id] else "FAIL",
                )
            )


        print(
            "WRONG FRONT SELECT  : {}".format(
                "FAIL" if wrong_front_detected else "PASS"
            )
        )

        print(
            "DANGEROUS GAP       : {}".format(
                "FAIL" if dangerous_gap_detected else "PASS"
            )
        )

        print(
            "SUSTAINED RUN       : {}".format(
                "PASS" if sustained_pass else "FAIL"
            )
        )

        print(
            "EMERGENCY_STOP      : {}".format(
                "OBSERVED" if emergency_seen else "not observed"
            )
        )


        print("-" * 92)


        for vehicle_id in TRUCK_IDS:

            print(
                "SPAWN {:7}        : {}".format(
                    vehicle_id,
                    (
                        "{:.1f}s".format(spawn_times[vehicle_id])
                        if spawn_times[vehicle_id] is not None
                        else "NOT SPAWNED"
                    ),
                )
            )


        print("-" * 92)


        for index in range(len(TRUCK_IDS) - 1):

            front_id = TRUCK_IDS[index]
            rear_id = TRUCK_IDS[index + 1]
            key = (front_id, rear_id)

            print(
                "MIN GAP {}-{}         : {} m".format(
                    front_id[-1],
                    rear_id[-1],
                    fmt(min_neighbor_gaps[key], 2),
                )
            )


        print("-" * 92)


        print(
            "MISSED EXPECTED NEAR : {}".format(
                " | ".join(
                    "{}={}".format(
                        vehicle_id,
                        missed_expected_nearby[vehicle_id],
                    )
                    for vehicle_id in TRUCK_IDS[1:]
                )
            )
        )


        print(
            "STATE TRANSITIONS   : {}".format(
                " | ".join(
                    "{}={}".format(
                        vehicle_id,
                        state_transition_counts[vehicle_id],
                    )
                    for vehicle_id in TRUCK_IDS
                )
            )
        )


        print("=" * 92)


        success = (
            all_spawned_pass
            and
            all_moved_pass
            and
            all_relations_pass
            and
            not wrong_front_detected
            and
            not dangerous_gap_detected
            and
            sustained_pass
        )


        if success:

            print()
            print(
                "RESULT: SIX-TRUCK CONTINUOUS FOLLOWING TEST PASSED"
            )

            return 0


        print()
        print(
            "RESULT: TEST DID NOT COMPLETE THE EXPECTED SIX-TRUCK CHAIN"
        )

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

