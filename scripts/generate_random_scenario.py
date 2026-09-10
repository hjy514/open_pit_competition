#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import print_function

import argparse
from pathlib import Path

from open_pit_competition.simulation.scenario_generator import (
    SUPPORTED_MODES,
    ScenarioGenerator,
    write_generated_scenario,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate one reproducible seed-based mine scenario."
    )
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument(
        "--mode",
        choices=SUPPORTED_MODES,
        default="mixed",
    )
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Output JSON path. Default: "
            "runtime_data/generated_scenarios/random_seed_<seed>.json"
        ),
    )
    parser.add_argument(
        "--failure-vehicles",
        default="truck_2,truck_3",
        help="Comma-separated eligible failure vehicle ids",
    )
    args = parser.parse_args()

    failure_vehicle_ids = [
        item.strip()
        for item in args.failure_vehicles.split(",")
        if item.strip()
    ]

    generated = ScenarioGenerator(
        seed=args.seed,
        failure_vehicle_ids=failure_vehicle_ids,
    ).generate(mode=args.mode)

    output = args.output
    if output is None:
        output = str(
            Path("runtime_data")
            / "generated_scenarios"
            / "random_seed_{}.json".format(args.seed)
        )

    path = write_generated_scenario(
        generated,
        output,
    )

    print("RANDOM SCENARIO READY")
    print("seed     :", generated.seed)
    print("mode     :", generated.mode)
    print("scenario :", generated.config.scenario_id)
    for event in generated.config.events:
        print(
            "event    : {:18s} @ {:5.1f}s {}".format(
                event.event_type,
                event.at_seconds,
                event.params,
            )
        )
    print("output   :", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
