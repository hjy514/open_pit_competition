#!/usr/bin/env python3
"""CARLA two-truck physical following test.

Test sequence:

rear truck:
CRUISE
  -> FOLLOW / DECELERATE
  -> WAIT_FRONT
  -> RESUME
  -> FOLLOW

The front truck is deliberately stopped after the rear truck
enters the following region, then restarted several seconds later.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


# Allow running directly without installing the project.
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


FRONT_ID = "truck_front"
REAR_ID = "truck_rear"


def format_optional(value, digits=1):

    if value is None:
        return "-"

    return f"{value:.{digits}f}"


def print_status(
    elapsed,
    adapter,
    rear_decision,
    phase,
):

    front = adapter.get_vehicle_snapshot(
        FRONT_ID
    )

    rear = adapter.get_vehicle_snapshot(
        REAR_ID
    )

    print(
        f"[{elapsed:6.1f}s] "
        f"phase={phase:<9} | "
        f"front={front.speed_mps * 3.6:5.1f} km/h | "
        f"rear={rear.speed_mps * 3.6:5.1f} km/h | "
        f"state={rear_decision.state.value:<15} | "
        f"target={rear_decision.target_speed_kmh:5.1f} | "
        f"gap={format_optional(rear_decision.front_gap_m):>6} m | "
        f"safe={format_optional(rear_decision.safe_gap_m):>6} m | "
        f"ttc={format_optional(rear_decision.ttc_s):>5} s"
    )


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--carla-root",
        default="/home/xiaoa/carla",
        help="CARLA 0.9.10 root directory",
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
        "--load-map",
        action="store_true",
        help="Ask CARLA to load the configured map",
    )

    # Based on the verified old-project route:
    #
    # 78 -> 12 -> 49 -> 48

    parser.add_argument(
        "--front-spawn",
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
        "--front-speed",
        type=float,
        default=10.0,
    )

    parser.add_argument(
        "--rear-speed",
        type=float,
        default=18.0,
    )

    parser.add_argument(
        "--stop-duration",
        type=float,
        default=8.0,
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

    parser.add_argument(
        "--keep-vehicles",
        action="store_true",
        help="Do not destroy the two vehicles after the test",
    )

    args = parser.parse_args()


    adapter = CarlaAdapter(

        carla_root=args.carla_root,

        host=args.host,

        port=args.port,

        timeout_seconds=20.0,

        map_name=args.map,

        load_map=args.load_map,
    )


    follow_seen = False
    decelerate_seen = False
    wait_seen = False
    resume_seen = False
    post_resume_follow_seen = False

    phase = "approach"

    front_stop_started = None

    follow_started = None

    tick_index = 0


    try:

        # ====================================================
        # CARLA connection
        # ====================================================

        adapter.connect()


        print()
        print("=" * 72)
        print("CARLA TWO-TRUCK FOLLOWING TEST")
        print("=" * 72)

        print(
            f"map              : {args.map}"
        )

        print(
            f"front spawn      : {args.front_spawn}"
        )

        print(
            f"rear spawn       : {args.rear_spawn}"
        )

        print(
            f"destination      : {args.destination}"
        )

        print(
            f"front speed      : {args.front_speed} km/h"
        )

        print(
            f"rear cruise speed: {args.rear_speed} km/h"
        )

        print()


        # ====================================================
        # Spawn vehicles
        # ====================================================

        adapter.spawn_vehicle(

            vehicle_id=FRONT_ID,

            spawn_point_index=
                args.front_spawn,

            blueprint_id=
                "vehicle.cat.cat",

            role_name=FRONT_ID,
        )


        # Give CARLA a brief moment to register the first actor.
        time.sleep(0.5)


        adapter.spawn_vehicle(

            vehicle_id=REAR_ID,

            spawn_point_index=
                args.rear_spawn,

            blueprint_id=
                "vehicle.cat.cat",

            role_name=REAR_ID,
        )


        time.sleep(0.5)


        # ====================================================
        # Both vehicles use the same destination.
        # ====================================================

        adapter.set_destination_spawn_point(

            vehicle_id=FRONT_ID,

            spawn_point_index=
                args.destination,

            target_speed_kmh=
                args.front_speed,
        )


        adapter.set_destination_spawn_point(

            vehicle_id=REAR_ID,

            spawn_point_index=
                args.destination,

            target_speed_kmh=
                args.rear_speed,
        )


        front_context = BehaviorContext(

            cruise_speed_kmh=
                args.front_speed
        )


        rear_context = BehaviorContext(

            cruise_speed_kmh=
                args.rear_speed
        )


        print(
            "Vehicles started. Waiting for rear truck to catch front truck..."
        )

        print()


        start_time = time.monotonic()


        # ====================================================
        # Physical test loop
        # ====================================================

        while True:

            now = time.monotonic()

            elapsed = (
                now - start_time
            )


            if elapsed >= args.max_runtime:

                print()
                print(
                    "[TEST] maximum runtime reached"
                )

                break


            # ------------------------------------------------
            # APPROACH
            #
            # Both trucks drive normally.
            # Rear truck should eventually enter FOLLOW /
            # DECELERATE.
            # ------------------------------------------------

            if phase == "approach":

                adapter.step_vehicle(

                    FRONT_ID,

                    context=front_context,
                )


                rear_decision = (
                    adapter.step_vehicle(

                        REAR_ID,

                        context=rear_context,
                    )
                )


                if (
                    rear_decision.state
                    == DrivingState.FOLLOW
                ):

                    follow_seen = True


                    if follow_started is None:

                        follow_started = now

                        print()
                        print(
                            "[TEST] FOLLOW detected"
                        )


                if (
                    rear_decision.state
                    == DrivingState.DECELERATE
                ):

                    follow_seen = True

                    decelerate_seen = True

                    phase = "stop"

                    front_stop_started = now

                    print()
                    print(
                        "[TEST] DECELERATE detected."
                    )

                    print(
                        "[TEST] Forcing front truck to STOP."
                    )


                # If BasicAgent makes the rear truck settle into
                # FOLLOW without reaching DECELERATE, still start
                # the stop experiment after three seconds.

                elif (

                    follow_started is not None

                    and

                    now - follow_started >= 3.0

                ):

                    phase = "stop"

                    front_stop_started = now

                    print()
                    print(
                        "[TEST] Stable FOLLOW detected."
                    )

                    print(
                        "[TEST] Forcing front truck to STOP."
                    )


            # ------------------------------------------------
            # STOP
            #
            # Front truck is physically held.
            # Rear truck must stop behind it.
            # ------------------------------------------------

            elif phase == "stop":

                adapter.stop_vehicle(

                    FRONT_ID,

                    hand_brake=False,
                )


                rear_decision = (
                    adapter.step_vehicle(

                        REAR_ID,

                        context=rear_context,
                    )
                )


                if (
                    rear_decision.state
                    == DrivingState.WAIT_FRONT
                ):

                    if not wait_seen:

                        print()
                        print(
                            "[TEST] WAIT_FRONT detected."
                        )


                    wait_seen = True


                if (
                    rear_decision.state
                    == DrivingState.EMERGENCY_STOP
                ):

                    print()
                    print(
                        "[WARNING] Rear truck entered "
                        "EMERGENCY_STOP."
                    )


                if (

                    front_stop_started is not None

                    and

                    now - front_stop_started
                    >= args.stop_duration

                ):

                    phase = "resume"

                    print()
                    print(
                        "[TEST] Releasing front truck."
                    )


            # ------------------------------------------------
            # RESUME
            #
            # Front truck drives again.
            # Rear truck should leave WAIT_FRONT and continue.
            # ------------------------------------------------

            else:

                adapter.step_vehicle(

                    FRONT_ID,

                    context=front_context,
                )


                rear_decision = (
                    adapter.step_vehicle(

                        REAR_ID,

                        context=rear_context,
                    )
                )


                if (
                    rear_decision.state
                    == DrivingState.RESUME
                ):

                    if not resume_seen:

                        print()
                        print(
                            "[TEST] RESUME detected."
                        )


                    resume_seen = True


                elif (

                    resume_seen

                    and

                    rear_decision.state
                    in {
                        DrivingState.FOLLOW,
                        DrivingState.DECELERATE,
                        DrivingState.CRUISE,
                    }

                ):

                    post_resume_follow_seen = True


            # ------------------------------------------------
            # Console telemetry
            # ------------------------------------------------

            if tick_index % 10 == 0:

                print_status(

                    elapsed=elapsed,

                    adapter=adapter,

                    rear_decision=
                        rear_decision,

                    phase=phase,
                )


            tick_index += 1


            # ------------------------------------------------
            # Success
            # ------------------------------------------------

            if (

                follow_seen

                and

                wait_seen

                and

                resume_seen

                and

                post_resume_follow_seen

            ):

                print()
                print(
                    "[TEST] Complete state chain observed."
                )

                break


            time.sleep(
                args.control_period
            )


        # ====================================================
        # Result
        # ====================================================

        print()
        print("=" * 72)
        print("TEST RESULT")
        print("=" * 72)

        print(
            f"FOLLOW       : {'PASS' if follow_seen else 'FAIL'}"
        )

        print(
            f"DECELERATE   : {'PASS' if decelerate_seen else 'not required / not observed'}"
        )

        print(
            f"WAIT_FRONT   : {'PASS' if wait_seen else 'FAIL'}"
        )

        print(
            f"RESUME       : {'PASS' if resume_seen else 'FAIL'}"
        )

        print(
            "POST-RESUME  : {}".format(
                "PASS"
                if post_resume_follow_seen
                else "FAIL"
            )
        )

        print("=" * 72)


        success = (

            follow_seen
            and wait_seen
            and resume_seen
            and post_resume_follow_seen
        )


        if success:

            print()
            print(
                "RESULT: TWO-TRUCK PHYSICAL FOLLOWING TEST PASSED"
            )

            return 0


        print()
        print(
            "RESULT: TEST DID NOT COMPLETE THE EXPECTED STATE CHAIN"
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


        if not args.keep_vehicles:

            try:

                destroyed = (
                    adapter.destroy_spawned_vehicles()
                )

                print(
                    f"[CLEANUP] destroyed vehicles: {destroyed}"
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
