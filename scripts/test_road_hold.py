#!/usr/bin/env python3
"""CARLA physical road-closure hold / reopen recovery test.

Expected state chain:

    CRUISE
      -> ROAD_HOLD
      -> physical stop
      -> RESUME
      -> CRUISE

Road closure is injected through BehaviorContext.road_open=False.
This is the low-level behavior that future road-closure scenarios
will trigger through the simulation runtime.
"""

from __future__ import print_function

import argparse
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


EGO_ID = "truck_road_hold_test"


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
        "--spawn",
        type=int,
        default=78,
    )

    parser.add_argument(
        "--destination",
        type=int,
        default=48,
    )

    parser.add_argument(
        "--speed",
        type=float,
        default=18.0,
    )

    parser.add_argument(
        "--blueprint",
        default="vehicle.cat.cat",
    )

    parser.add_argument(
        "--hold-duration",
        type=float,
        default=5.0,
    )

    parser.add_argument(
        "--inject-min-speed",
        type=float,
        default=5.0,
        help="Close road after ego reaches this speed in km/h",
    )

    parser.add_argument(
        "--post-resume-speed",
        type=float,
        default=3.0,
    )

    parser.add_argument(
        "--max-runtime",
        type=float,
        default=75.0,
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


    phase = "startup"

    road_hold_seen_at = None

    seen_cruise = False
    seen_road_hold = False
    confirmed_stationary = False
    seen_resume = False
    seen_post_resume_motion = False

    last_state = None
    tick_index = 0


    try:

        # ========================================================
        # Connect and spawn
        # ========================================================

        adapter.connect()


        print()
        print("=" * 76)
        print("CARLA ROAD CLOSURE HOLD / REOPEN TEST")
        print("=" * 76)

        print("map               :", args.map)
        print("spawn             :", args.spawn)
        print("destination       :", args.destination)
        print("cruise speed      :", args.speed, "km/h")
        print("road hold         :", args.hold_duration, "s")

        print()


        adapter.spawn_vehicle(
            vehicle_id=EGO_ID,
            spawn_point_index=args.spawn,
            blueprint_id=args.blueprint,
            role_name=EGO_ID,
        )


        time.sleep(0.5)


        adapter.set_destination_spawn_point(
            vehicle_id=EGO_ID,
            spawn_point_index=args.destination,
            target_speed_kmh=args.speed,
        )


        road_open = True


        print(
            "[TEST] ego started. Waiting for normal cruise before road closure..."
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


            snapshot = adapter.get_vehicle_snapshot(
                EGO_ID
            )

            speed_kmh = (
                snapshot.speed_mps
                * 3.6
            )


            context = BehaviorContext(
                cruise_speed_kmh=args.speed,
                road_open=road_open,
            )


            decision = adapter.step_vehicle(
                EGO_ID,
                context=context,
            )


            # ----------------------------------------------------
            # Phase 1: establish normal driving, then close road.
            # ----------------------------------------------------

            if phase == "startup":

                if (
                    decision.state
                    == DrivingState.CRUISE
                ):

                    seen_cruise = True


                if (
                    seen_cruise
                    and
                    speed_kmh
                    >= args.inject_min_speed
                ):

                    print()
                    print(
                        "[TEST] Closing road."
                    )

                    road_open = False
                    phase = "road_hold"


            # ----------------------------------------------------
            # Phase 2: ROAD_HOLD and physical stop.
            # ----------------------------------------------------

            elif phase == "road_hold":

                if (
                    decision.state
                    == DrivingState.ROAD_HOLD
                ):

                    if not seen_road_hold:

                        print()
                        print(
                            "[TEST] ROAD_HOLD detected."
                        )

                        road_hold_seen_at = now


                    seen_road_hold = True


                if (
                    seen_road_hold
                    and
                    speed_kmh <= 0.5
                ):

                    if not confirmed_stationary:

                        print()
                        print(
                            "[TEST] vehicle physically stopped for road closure."
                        )


                    confirmed_stationary = True


                if (
                    seen_road_hold
                    and
                    road_hold_seen_at is not None
                    and
                    now - road_hold_seen_at
                    >= args.hold_duration
                ):

                    print()
                    print(
                        "[TEST] Reopening road."
                    )

                    road_open = True
                    phase = "recovery"


            # ----------------------------------------------------
            # Phase 3: reopen -> RESUME -> moving again.
            # ----------------------------------------------------

            elif phase == "recovery":

                if (
                    decision.state
                    == DrivingState.RESUME
                ):

                    if not seen_resume:

                        print()
                        print(
                            "[TEST] RESUME detected."
                        )


                    seen_resume = True


                if (
                    seen_resume
                    and
                    speed_kmh
                    >= args.post_resume_speed
                    and
                    decision.state
                    in {
                        DrivingState.RESUME,
                        DrivingState.CRUISE,
                    }
                ):

                    seen_post_resume_motion = True


            # ----------------------------------------------------
            # State change logging
            # ----------------------------------------------------

            if (
                decision.state
                != last_state
            ):

                print(
                    "[STATE] {:.1f}s | {} | reason={}".format(
                        elapsed,
                        decision.state.value,
                        decision.reason,
                    )
                )

                last_state = (
                    decision.state
                )


            # ----------------------------------------------------
            # Telemetry
            # ----------------------------------------------------

            if tick_index % 10 == 0:

                print(
                    "[{:6.1f}s] "
                    "phase={:<10} | "
                    "speed={:5.1f} km/h | "
                    "state={:<12} | "
                    "target={:5.1f} | "
                    "road_open={}".format(
                        elapsed,
                        phase,
                        speed_kmh,
                        decision.state.value,
                        decision.target_speed_kmh,
                        road_open,
                    )
                )


            tick_index += 1


            # ----------------------------------------------------
            # Success
            # ----------------------------------------------------

            if (
                seen_cruise
                and
                seen_road_hold
                and
                confirmed_stationary
                and
                seen_resume
                and
                seen_post_resume_motion
            ):

                print()
                print(
                    "[TEST] Complete road-closure state chain observed."
                )

                break


            time.sleep(
                args.control_period
            )


        # ========================================================
        # Result
        # ========================================================

        print()
        print("=" * 76)
        print("TEST RESULT")
        print("=" * 76)

        print(
            "CRUISE          : {}".format(
                "PASS"
                if seen_cruise
                else "FAIL"
            )
        )

        print(
            "ROAD_HOLD       : {}".format(
                "PASS"
                if seen_road_hold
                else "FAIL"
            )
        )

        print(
            "PHYSICAL STOP   : {}".format(
                "PASS"
                if confirmed_stationary
                else "FAIL"
            )
        )

        print(
            "RESUME          : {}".format(
                "PASS"
                if seen_resume
                else "FAIL"
            )
        )

        print(
            "POST-RESUME     : {}".format(
                "PASS"
                if seen_post_resume_motion
                else "FAIL"
            )
        )

        print("=" * 76)


        success = (
            seen_cruise
            and
            seen_road_hold
            and
            confirmed_stationary
            and
            seen_resume
            and
            seen_post_resume_motion
        )


        if success:

            print()
            print(
                "RESULT: ROAD CLOSURE HOLD / REOPEN TEST PASSED"
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
