#!/usr/bin/env python3
"""CARLA physical vehicle-fault stop / recovery test.

Expected state chain:

    CRUISE
      -> FAULT_STOP
      -> RESUME
      -> CRUISE

The fault is injected through CarlaAdapter.set_vehicle_operational(),
which is the same low-level interface that the future S02
VehicleFailureEvent will use.
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


EGO_ID = "truck_fault_test"


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
        "--fault-hold-duration",
        type=float,
        default=5.0,
    )

    parser.add_argument(
        "--inject-min-speed",
        type=float,
        default=5.0,
        help="Inject fault after ego reaches at least this speed in km/h",
    )

    parser.add_argument(
        "--post-resume-speed",
        type=float,
        default=3.0,
        help="Speed threshold used to confirm motion after recovery",
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

    fault_injected_at = None
    fault_stop_seen_at = None

    seen_cruise = False
    seen_fault_stop = False
    confirmed_fault_stationary = False
    seen_resume = False
    seen_post_resume_motion = False

    last_state = None
    tick_index = 0


    try:

        # ========================================================
        # Connect + spawn
        # ========================================================

        adapter.connect()


        print()
        print("=" * 76)
        print("CARLA VEHICLE FAULT STOP / RECOVERY TEST")
        print("=" * 76)

        print("map               :", args.map)
        print("spawn             :", args.spawn)
        print("destination       :", args.destination)
        print("cruise speed      :", args.speed, "km/h")
        print("fault hold        :", args.fault_hold_duration, "s")

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


        context = BehaviorContext(
            cruise_speed_kmh=args.speed,
        )


        print(
            "[TEST] ego started. Waiting for normal cruise before fault injection..."
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


            decision = adapter.step_vehicle(
                EGO_ID,
                context=context,
            )


            # ----------------------------------------------------
            # Phase 1:
            # Wait until real physical motion is established.
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
                        "[TEST] Injecting vehicle failure."
                    )

                    adapter.set_vehicle_operational(
                        EGO_ID,
                        healthy=False,
                        available=False,
                    )

                    fault_injected_at = now

                    phase = "fault"


            # ----------------------------------------------------
            # Phase 2:
            # Vehicle must enter FAULT_STOP and physically stop.
            # ----------------------------------------------------

            elif phase == "fault":

                if (
                    decision.state
                    == DrivingState.FAULT_STOP
                ):

                    if not seen_fault_stop:

                        print()
                        print(
                            "[TEST] FAULT_STOP detected."
                        )

                        fault_stop_seen_at = now


                    seen_fault_stop = True


                if (
                    seen_fault_stop
                    and
                    speed_kmh <= 0.5
                ):

                    if not confirmed_fault_stationary:

                        print()
                        print(
                            "[TEST] vehicle physically stopped under fault."
                        )


                    confirmed_fault_stationary = True


                # Start recovery timing from actual FAULT_STOP
                # detection, not merely from the injection call.
                if (
                    seen_fault_stop
                    and
                    fault_stop_seen_at is not None
                    and
                    now - fault_stop_seen_at
                    >= args.fault_hold_duration
                ):

                    print()
                    print(
                        "[TEST] Clearing vehicle failure."
                    )

                    adapter.set_vehicle_operational(
                        EGO_ID,
                        healthy=True,
                        available=True,
                    )

                    phase = "recovery"


            # ----------------------------------------------------
            # Phase 3:
            # Clearing fault should produce RESUME, then movement.
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
            # State-change logging
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
                    "phase={:<9} | "
                    "speed={:5.1f} km/h | "
                    "state={:<12} | "
                    "target={:5.1f} | "
                    "healthy={} | "
                    "available={}".format(
                        elapsed,
                        phase,
                        speed_kmh,
                        decision.state.value,
                        decision.target_speed_kmh,
                        snapshot.healthy,
                        snapshot.available,
                    )
                )


            tick_index += 1


            # ----------------------------------------------------
            # Success
            # ----------------------------------------------------

            if (
                seen_cruise
                and
                seen_fault_stop
                and
                confirmed_fault_stationary
                and
                seen_resume
                and
                seen_post_resume_motion
            ):

                print()
                print(
                    "[TEST] Complete fault state chain observed."
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
            "FAULT_STOP      : {}".format(
                "PASS"
                if seen_fault_stop
                else "FAIL"
            )
        )

        print(
            "PHYSICAL STOP   : {}".format(
                "PASS"
                if confirmed_fault_stationary
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
            seen_fault_stop
            and
            confirmed_fault_stationary
            and
            seen_resume
            and
            seen_post_resume_motion
        )


        if success:

            print()
            print(
                "RESULT: VEHICLE FAULT STOP / RECOVERY TEST PASSED"
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
