#!/usr/bin/env python3
"""CARLA three-truck continuous following physical test.

Purpose:
- verify three controlled mine trucks can run on the same route
- verify truck_2 identifies truck_1 as its immediate front vehicle
- verify truck_3 identifies truck_2 as its immediate front vehicle
- detect obvious wrong-front selection or dangerously small spacing
- keep the system running for a sustained observation period

Spawn strategy:
    truck_1: spawn 12
    truck_2: spawn 78
    truck_3: spawn 78 later, after truck_2 has moved far enough away

This avoids relying on spawn point 49, which is only a few metres from
spawn point 12 on the current custom map.
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


TRUCK_1 = "truck_1"
TRUCK_2 = "truck_2"
TRUCK_3 = "truck_3"


FOLLOWING_STATES = {
    DrivingState.FOLLOW,
    DrivingState.DECELERATE,
    DrivingState.WAIT_FRONT,
    DrivingState.RESUME,
}


def horizontal_distance_xy(x1, y1, x2, y2):
    dx = x2 - x1
    dy = y2 - y1
    return math.sqrt(dx * dx + dy * dy)


def approximate_bumper_gap(a, b):
    """Approximate longitudinal physical spacing from snapshots.

    Used only as a gross collision/safety sanity check.
    """
    center_distance = math.sqrt(
        (a.x - b.x) * (a.x - b.x)
        + (a.y - b.y) * (a.y - b.y)
        + (a.z - b.z) * (a.z - b.z)
    )

    return (
        center_distance
        - 0.5 * a.length_m
        - 0.5 * b.length_m
    )


def fmt(value, digits=1):
    if value is None:
        return "-"
    return ("{:.%df}" % digits).format(value)


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
        "--leader-speed",
        type=float,
        default=10.0,
    )

    parser.add_argument(
        "--middle-speed",
        type=float,
        default=14.0,
    )

    parser.add_argument(
        "--rear-speed",
        type=float,
        default=18.0,
    )

    parser.add_argument(
        "--blueprint",
        default="vehicle.cat.cat",
    )

    parser.add_argument(
        "--third-spawn-clearance",
        type=float,
        default=35.0,
        help=(
            "Spawn truck_3 after truck_2 has moved this far "
            "from rear spawn point"
        ),
    )

    parser.add_argument(
        "--required-relation-samples",
        type=int,
        default=3,
        help="Consecutive correct front-vehicle samples required",
    )

    parser.add_argument(
        "--sustain-duration",
        type=float,
        default=10.0,
        help=(
            "After both following relationships are confirmed, "
            "continue running for this many seconds"
        ),
    )

    parser.add_argument(
        "--danger-gap",
        type=float,
        default=1.0,
        help="Approximate bumper gap below which test fails",
    )

    parser.add_argument(
        "--max-runtime",
        type=float,
        default=120.0,
    )

    parser.add_argument(
        "--control-period",
        type=float,
        default=0.05,
    )

    args = parser.parse_args()


    adapter = CarlaAdapter(
        carla_root=args.carla_root,
        host=args.host,
        port=args.port,
        timeout_seconds=20.0,
        map_name=args.map,
        load_map=False,
    )


    contexts = {
        TRUCK_1: BehaviorContext(
            cruise_speed_kmh=args.leader_speed
        ),
        TRUCK_2: BehaviorContext(
            cruise_speed_kmh=args.middle_speed
        ),
        TRUCK_3: BehaviorContext(
            cruise_speed_kmh=args.rear_speed
        ),
    }


    truck_3_spawned = False

    truck_2_relation_samples = 0
    truck_3_relation_samples = 0

    truck_2_relation_pass = False
    truck_3_relation_pass = False

    all_three_moved = {
        TRUCK_1: False,
        TRUCK_2: False,
        TRUCK_3: False,
    }

    wrong_front_detected = False
    dangerous_gap_detected = False
    emergency_seen = False

    relation_confirmed_at = None

    last_states = {}
    state_transition_counts = {
        TRUCK_1: 0,
        TRUCK_2: 0,
        TRUCK_3: 0,
    }

    min_gap_12 = None
    min_gap_23 = None

    tick_index = 0


    try:

        # ========================================================
        # Connect and validate spawn indices
        # ========================================================

        adapter.connect()

        world = adapter.world
        spawn_points = world.get_map().get_spawn_points()


        for index, label in (
            (args.leader_spawn, "leader"),
            (args.rear_spawn, "rear"),
            (args.destination, "destination"),
        ):

            if not (
                0 <= index < len(spawn_points)
            ):

                raise CarlaAdapterError(
                    "{} spawn point {} out of range 0..{}".format(
                        label,
                        index,
                        len(spawn_points) - 1,
                    )
                )


        rear_spawn_location = (
            spawn_points[
                args.rear_spawn
            ].location
        )


        print()
        print("=" * 82)
        print("CARLA THREE-TRUCK CONTINUOUS FOLLOWING TEST")
        print("=" * 82)

        print("map                 :", args.map)
        print("truck_1 spawn       :", args.leader_spawn)
        print("truck_2 spawn       :", args.rear_spawn)
        print("truck_3 spawn       :", args.rear_spawn, "(delayed)")
        print("destination         :", args.destination)

        print(
            "speeds              : truck_1={} / truck_2={} / truck_3={} km/h".format(
                args.leader_speed,
                args.middle_speed,
                args.rear_speed,
            )
        )

        print(
            "truck_3 clearance   :",
            args.third_spawn_clearance,
            "m",
        )

        print()


        # ========================================================
        # Spawn truck_1 and truck_2
        # ========================================================

        adapter.spawn_vehicle(
            vehicle_id=TRUCK_1,
            spawn_point_index=args.leader_spawn,
            blueprint_id=args.blueprint,
            role_name=TRUCK_1,
        )

        adapter.spawn_vehicle(
            vehicle_id=TRUCK_2,
            spawn_point_index=args.rear_spawn,
            blueprint_id=args.blueprint,
            role_name=TRUCK_2,
        )


        time.sleep(0.5)


        adapter.set_destination_spawn_point(
            vehicle_id=TRUCK_1,
            spawn_point_index=args.destination,
            target_speed_kmh=args.leader_speed,
        )

        adapter.set_destination_spawn_point(
            vehicle_id=TRUCK_2,
            spawn_point_index=args.destination,
            target_speed_kmh=args.middle_speed,
        )


        print(
            "[TEST] truck_1 and truck_2 started."
        )

        print(
            "[TEST] truck_3 will be released from spawn {} after truck_2 moves {:.1f} m.".format(
                args.rear_spawn,
                args.third_spawn_clearance,
            )
        )

        print()


        start = time.monotonic()


        # ========================================================
        # Runtime loop
        # ========================================================

        while True:

            now = time.monotonic()
            elapsed = now - start


            if elapsed >= args.max_runtime:

                print()
                print(
                    "[TEST] maximum runtime reached"
                )

                break


            # ----------------------------------------------------
            # Spawn truck_3 only after truck_2 clears spawn 78.
            # ----------------------------------------------------

            if not truck_3_spawned:

                snap_2_before = (
                    adapter.get_vehicle_snapshot(
                        TRUCK_2
                    )
                )

                moved_from_spawn = (
                    horizontal_distance_xy(
                        rear_spawn_location.x,
                        rear_spawn_location.y,
                        snap_2_before.x,
                        snap_2_before.y,
                    )
                )


                if (
                    moved_from_spawn
                    >= args.third_spawn_clearance
                ):

                    print()
                    print(
                        "[TEST] truck_2 cleared rear spawn by {:.1f} m.".format(
                            moved_from_spawn
                        )
                    )

                    print(
                        "[TEST] Spawning truck_3."
                    )


                    adapter.spawn_vehicle(
                        vehicle_id=TRUCK_3,
                        spawn_point_index=args.rear_spawn,
                        blueprint_id=args.blueprint,
                        role_name=TRUCK_3,
                    )


                    time.sleep(0.4)


                    adapter.set_destination_spawn_point(
                        vehicle_id=TRUCK_3,
                        spawn_point_index=args.destination,
                        target_speed_kmh=args.rear_speed,
                    )


                    truck_3_spawned = True


            # ----------------------------------------------------
            # Step active trucks from front to rear.
            # ----------------------------------------------------

            decisions = {}


            for vehicle_id in (
                TRUCK_1,
                TRUCK_2,
                TRUCK_3,
            ):

                if (
                    vehicle_id == TRUCK_3
                    and not truck_3_spawned
                ):

                    continue


                decisions[
                    vehicle_id
                ] = adapter.step_vehicle(
                    vehicle_id,
                    context=contexts[
                        vehicle_id
                    ],
                )


            # ----------------------------------------------------
            # Fresh snapshots after control commands.
            # ----------------------------------------------------

            snapshots = {}


            for vehicle_id in (
                TRUCK_1,
                TRUCK_2,
                TRUCK_3,
            ):

                if (
                    vehicle_id == TRUCK_3
                    and not truck_3_spawned
                ):

                    continue


                snapshots[
                    vehicle_id
                ] = adapter.get_vehicle_snapshot(
                    vehicle_id
                )


            # ----------------------------------------------------
            # Movement confirmation
            # ----------------------------------------------------

            for vehicle_id, snapshot in snapshots.items():

                if snapshot.speed_mps * 3.6 >= 3.0:

                    all_three_moved[
                        vehicle_id
                    ] = True


            # ----------------------------------------------------
            # Immediate-front relation:
            # truck_2 should follow truck_1.
            # ----------------------------------------------------

            d2 = decisions.get(
                TRUCK_2
            )


            if (
                d2 is not None
                and
                d2.front_vehicle_id
                == TRUCK_1
                and
                d2.state
                in FOLLOWING_STATES
            ):

                truck_2_relation_samples += 1


                if (
                    truck_2_relation_samples
                    >= args.required_relation_samples
                    and
                    not truck_2_relation_pass
                ):

                    truck_2_relation_pass = True

                    print()
                    print(
                        "[TEST] truck_2 -> truck_1 front relation confirmed."
                    )


            else:

                truck_2_relation_samples = 0


            # ----------------------------------------------------
            # Immediate-front relation:
            # truck_3 should follow truck_2, NOT truck_1.
            # ----------------------------------------------------

            d3 = decisions.get(
                TRUCK_3
            )


            if (
                d3 is not None
                and
                d3.front_vehicle_id
                == TRUCK_2
                and
                d3.state
                in FOLLOWING_STATES
            ):

                truck_3_relation_samples += 1


                if (
                    truck_3_relation_samples
                    >= args.required_relation_samples
                    and
                    not truck_3_relation_pass
                ):

                    truck_3_relation_pass = True

                    print()
                    print(
                        "[TEST] truck_3 -> truck_2 front relation confirmed."
                    )


            else:

                truck_3_relation_samples = 0


            # A truck_3 selection of truck_1 is suspicious only when
            # truck_2 is physically available and between them.
            if (
                truck_3_spawned
                and
                d3 is not None
                and
                d3.front_vehicle_id
                == TRUCK_1
            ):

                wrong_front_detected = True

                print()
                print(
                    "[FAIL] truck_3 selected truck_1 instead of immediate truck_2."
                )

                break


            # ----------------------------------------------------
            # Emergency-state monitoring
            # ----------------------------------------------------

            for vehicle_id, decision in decisions.items():

                if (
                    decision.state
                    == DrivingState.EMERGENCY_STOP
                ):

                    emergency_seen = True

                    print()
                    print(
                        "[WARN] {} entered EMERGENCY_STOP.".format(
                            vehicle_id
                        )
                    )


            # ----------------------------------------------------
            # Approximate spacing sanity checks
            # ----------------------------------------------------

            if (
                TRUCK_1 in snapshots
                and
                TRUCK_2 in snapshots
            ):

                gap_12 = approximate_bumper_gap(
                    snapshots[TRUCK_1],
                    snapshots[TRUCK_2],
                )


                if (
                    min_gap_12 is None
                    or gap_12 < min_gap_12
                ):

                    min_gap_12 = gap_12


                if gap_12 < args.danger_gap:

                    dangerous_gap_detected = True

                    print()
                    print(
                        "[FAIL] truck_1 / truck_2 approximate gap {:.2f} m.".format(
                            gap_12
                        )
                    )

                    break


            if (
                truck_3_spawned
                and
                TRUCK_2 in snapshots
                and
                TRUCK_3 in snapshots
            ):

                gap_23 = approximate_bumper_gap(
                    snapshots[TRUCK_2],
                    snapshots[TRUCK_3],
                )


                if (
                    min_gap_23 is None
                    or gap_23 < min_gap_23
                ):

                    min_gap_23 = gap_23


                if gap_23 < args.danger_gap:

                    dangerous_gap_detected = True

                    print()
                    print(
                        "[FAIL] truck_2 / truck_3 approximate gap {:.2f} m.".format(
                            gap_23
                        )
                    )

                    break


            # ----------------------------------------------------
            # State transitions
            # ----------------------------------------------------

            for vehicle_id, decision in decisions.items():

                previous = last_states.get(
                    vehicle_id
                )


                if (
                    previous
                    != decision.state
                ):

                    state_transition_counts[
                        vehicle_id
                    ] += 1


                    print(
                        "[STATE] {:6.1f}s | {:7} | {:14} | front={} | reason={}".format(
                            elapsed,
                            vehicle_id,
                            decision.state.value,
                            decision.front_vehicle_id,
                            decision.reason,
                        )
                    )


                    last_states[
                        vehicle_id
                    ] = decision.state


            # ----------------------------------------------------
            # Telemetry
            # ----------------------------------------------------

            if tick_index % 10 == 0:

                parts = []


                for vehicle_id in (
                    TRUCK_1,
                    TRUCK_2,
                    TRUCK_3,
                ):

                    if vehicle_id not in snapshots:

                        parts.append(
                            "{}=not-spawned".format(
                                vehicle_id
                            )
                        )

                        continue


                    snapshot = snapshots[
                        vehicle_id
                    ]

                    decision = decisions[
                        vehicle_id
                    ]


                    parts.append(
                        "{}:{:.1f}km/h {} front={} gap={}".format(
                            vehicle_id,
                            snapshot.speed_mps * 3.6,
                            decision.state.value,
                            decision.front_vehicle_id,
                            fmt(
                                decision.front_gap_m
                            ),
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
            # Once both immediate-front relations are confirmed,
            # continue for a sustained observation period.
            # ----------------------------------------------------

            if (
                truck_2_relation_pass
                and
                truck_3_relation_pass
            ):

                if relation_confirmed_at is None:

                    relation_confirmed_at = now

                    print()
                    print(
                        "[TEST] Both front relations confirmed; starting {:.1f}s sustained run.".format(
                            args.sustain_duration
                        )
                    )


                elif (
                    now - relation_confirmed_at
                    >= args.sustain_duration
                ):

                    print()
                    print(
                        "[TEST] sustained three-truck run completed."
                    )

                    break


            time.sleep(
                args.control_period
            )


        # ========================================================
        # Result
        # ========================================================

        three_moved = (
            truck_3_spawned
            and
            all(
                all_three_moved[
                    vehicle_id
                ]
                for vehicle_id in (
                    TRUCK_1,
                    TRUCK_2,
                    TRUCK_3,
                )
            )
        )


        sustained_run_pass = (
            relation_confirmed_at is not None
            and
            time.monotonic()
            - relation_confirmed_at
            >= args.sustain_duration
        )


        print()
        print("=" * 82)
        print("TEST RESULT")
        print("=" * 82)

        print(
            "THREE SPAWNED       : {}".format(
                "PASS"
                if truck_3_spawned
                else "FAIL"
            )
        )

        print(
            "THREE MOVED         : {}".format(
                "PASS"
                if three_moved
                else "FAIL"
            )
        )

        print(
            "TRUCK2 -> TRUCK1    : {}".format(
                "PASS"
                if truck_2_relation_pass
                else "FAIL"
            )
        )

        print(
            "TRUCK3 -> TRUCK2    : {}".format(
                "PASS"
                if truck_3_relation_pass
                else "FAIL"
            )
        )

        print(
            "WRONG FRONT SELECT  : {}".format(
                "FAIL"
                if wrong_front_detected
                else "PASS"
            )
        )

        print(
            "DANGEROUS GAP       : {}".format(
                "FAIL"
                if dangerous_gap_detected
                else "PASS"
            )
        )

        print(
            "SUSTAINED RUN       : {}".format(
                "PASS"
                if sustained_run_pass
                else "FAIL"
            )
        )

        print(
            "EMERGENCY_STOP      : {}".format(
                "OBSERVED"
                if emergency_seen
                else "not observed"
            )
        )

        print(
            "MIN GAP 1-2         : {} m".format(
                fmt(
                    min_gap_12,
                    2,
                )
            )
        )

        print(
            "MIN GAP 2-3         : {} m".format(
                fmt(
                    min_gap_23,
                    2,
                )
            )
        )

        print(
            "STATE TRANSITIONS   : truck_1={} truck_2={} truck_3={}".format(
                state_transition_counts[
                    TRUCK_1
                ],
                state_transition_counts[
                    TRUCK_2
                ],
                state_transition_counts[
                    TRUCK_3
                ],
            )
        )

        print("=" * 82)


        success = (
            truck_3_spawned
            and
            three_moved
            and
            truck_2_relation_pass
            and
            truck_3_relation_pass
            and
            not wrong_front_detected
            and
            not dangerous_gap_detected
            and
            sustained_run_pass
        )


        if success:

            print()
            print(
                "RESULT: THREE-TRUCK CONTINUOUS FOLLOWING TEST PASSED"
            )

            return 0


        print()
        print(
            "RESULT: TEST DID NOT COMPLETE THE EXPECTED THREE-TRUCK CHAIN"
        )

        return 1


    except CarlaAdapterError as exc:

        print()
        print(
            "[CARLA ERROR]",
            exc,
        )

        return 2


    except KeyboardInterrupt:

        print()
        print(
            "[TEST] interrupted by user"
        )

        return 130


    finally:

        try:

            adapter.close()

        except Exception:

            pass


        try:

            destroyed = (
                adapter.destroy_spawned_vehicles()
            )

            print(
                "[CLEANUP] destroyed controlled vehicles: {}".format(
                    destroyed
                )
            )

        except Exception as exc:

            print(
                "[CLEANUP WARNING]",
                exc,
            )


if __name__ == "__main__":

    raise SystemExit(
        main()
    )
