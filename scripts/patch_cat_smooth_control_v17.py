#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import print_function

import py_compile
import shutil
from pathlib import Path

TARGET = Path("src/open_pit_competition/simulation/carla_adapter.py")
BACKUP = Path("src/open_pit_competition/simulation/carla_adapter.py.before_v17_cat_smooth")
MARKER = "CAT smooth-control V1.7"

ANCHOR = '''
        self._last_driving_decisions[
            vehicle_id
        ] = decision
'''

BLOCK = r'''
        # --------------------------------------------------------
        # CAT smooth-control V1.7
        #
        # Soften normal LocalPlanner actuator commands for the large CAT.
        # VehicleBehavior remains the sole safety owner.
        # brake_override remains immediate and is never smoothed down.
        # --------------------------------------------------------

        try:
            previous_control = actor.get_control()
        except Exception:
            previous_control = None

        requested_steer = float(
            getattr(
                control,
                "steer",
                0.0,
            )
        )

        previous_steer = (
            float(
                getattr(
                    previous_control,
                    "steer",
                    0.0,
                )
            )
            if previous_control is not None
            else 0.0
        )

        max_steer_delta = 0.035
        control.steer = max(
            -1.0,
            min(
                1.0,
                max(
                    previous_steer - max_steer_delta,
                    min(
                        previous_steer + max_steer_delta,
                        requested_steer,
                    ),
                ),
            ),
        )

        if decision.brake_override is None:

            previous_throttle = (
                float(
                    getattr(
                        previous_control,
                        "throttle",
                        0.0,
                    )
                )
                if previous_control is not None
                else 0.0
            )

            previous_brake = (
                float(
                    getattr(
                        previous_control,
                        "brake",
                        0.0,
                    )
                )
                if previous_control is not None
                else 0.0
            )

            requested_throttle = max(
                0.0,
                min(
                    1.0,
                    float(
                        getattr(
                            control,
                            "throttle",
                            0.0,
                        )
                    ),
                ),
            )

            requested_brake = max(
                0.0,
                min(
                    1.0,
                    float(
                        getattr(
                            control,
                            "brake",
                            0.0,
                        )
                    ),
                ),
            )

            current_speed_kmh = max(
                0.0,
                float(ego.speed_mps) * 3.6,
            )
            desired_speed_kmh = max(
                0.0,
                float(decision.target_speed_kmh),
            )
            overspeed_kmh = current_speed_kmh - desired_speed_kmh

            if overspeed_kmh > 0.8:
                control.throttle = 0.0
                control.brake = max(
                    requested_brake,
                    min(
                        0.28,
                        0.05 + 0.05 * overspeed_kmh,
                    ),
                )
            else:
                throttle_rise = 0.04
                throttle_fall = 0.08
                brake_rise = 0.08
                brake_fall = 0.10

                control.throttle = max(
                    0.0,
                    min(
                        1.0,
                        max(
                            previous_throttle - throttle_fall,
                            min(
                                previous_throttle + throttle_rise,
                                requested_throttle,
                            ),
                        ),
                    ),
                )

                control.brake = max(
                    0.0,
                    min(
                        1.0,
                        max(
                            previous_brake - brake_fall,
                            min(
                                previous_brake + brake_rise,
                                requested_brake,
                            ),
                        ),
                    ),
                )

                if control.brake > 0.05:
                    control.throttle = 0.0

            control.hand_brake = False


'''

def main():
    if not TARGET.exists():
        raise SystemExit("ERROR: target not found: {}".format(TARGET))

    text = TARGET.read_text(encoding="utf-8")

    if MARKER in text:
        print("V1.7 already installed; no changes made.")
        return

    count = text.count(ANCHOR)
    if count != 1:
        raise SystemExit(
            "ERROR: expected exactly one insertion anchor, found {}. "
            "No file changed.".format(count)
        )

    if not BACKUP.exists():
        shutil.copy2(str(TARGET), str(BACKUP))
        print("backup:", BACKUP)
    else:
        print("backup already exists:", BACKUP)

    patched = text.replace(ANCHOR, BLOCK + ANCHOR, 1)
    TARGET.write_text(patched, encoding="utf-8")

    try:
        py_compile.compile(str(TARGET), doraise=True)
    except Exception:
        shutil.copy2(str(BACKUP), str(TARGET))
        print("compile failed; original restored from backup")
        raise

    print("CAT smooth-control V1.7 installed successfully")
    print("modified:", TARGET)
    print("untouched: Decision / VehicleBehavior / Monitoring / Storage / scenarios")

if __name__ == "__main__":
    main()
