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
from open_pit_competition.simulation.task_generator import (
    RandomTaskConfigGenerator,
    load_json,
    write_generated_task_config,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate one reproducible random Scenario + Closed Loop task config."
        )
    )
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument(
        "--mode",
        choices=SUPPORTED_MODES,
        default="mixed",
    )
    parser.add_argument(
        "--base-closed-loop-config",
        default="configs/closed_loop_formal_s01.json",
    )
    parser.add_argument(
        "--failure-vehicles",
        default="truck_2,truck_3",
    )
    parser.add_argument(
        "--scenario-output",
        default=None,
    )
    parser.add_argument(
        "--closed-loop-output",
        default=None,
    )
    args = parser.parse_args()

    failure_vehicle_ids = [
        item.strip()
        for item in args.failure_vehicles.split(",")
        if item.strip()
    ]

    scenario = ScenarioGenerator(
        seed=args.seed,
        failure_vehicle_ids=failure_vehicle_ids,
    ).generate(mode=args.mode)

    scenario_output = args.scenario_output or str(
        Path("runtime_data")
        / "generated_scenarios"
        / "random_seed_{}.json".format(args.seed)
    )
    scenario_path = write_generated_scenario(
        scenario,
        scenario_output,
    )

    base_config = load_json(
        args.base_closed_loop_config
    )
    task_config = RandomTaskConfigGenerator(
        seed=args.seed,
        base_config=base_config,
    ).generate()

    closed_loop_output = args.closed_loop_output or str(
        Path("runtime_data")
        / "generated_closed_loop"
        / "random_seed_{}.json".format(args.seed)
    )
    closed_loop_path = write_generated_task_config(
        task_config,
        closed_loop_output,
    )

    print("RANDOM RUN READY")
    print("seed       :", args.seed)
    print("mode       :", scenario.mode)
    print("scenario   :", scenario.config.scenario_id)
    for event in scenario.config.events:
        print(
            "event      : {:18s} @ {:5.1f}s {}".format(
                event.event_type,
                event.at_seconds,
                event.params,
            )
        )

    print("tasks:")
    for task in task_config.tasks:
        print(
            "  {:20s} {}->{} release={:4.1f}s priority={}".format(
                str(task["task_id"]),
                int(task["origin_spawn_index"]),
                int(task["destination_spawn_index"]),
                float(task["release_time_s"]),
                int(task["priority"]),
            )
        )

    print("scenario   :", scenario_path)
    print("closed-loop:", closed_loop_path)
    print()
    print("CARLA command:")
    print(
        "PYTHONPATH=src python -m open_pit_competition.simulation.runtime "
        "--scenario {} --fleet configs/fleet.json --monitoring --closed-loop "
        "--closed-loop-config {}".format(
            scenario_path,
            closed_loop_path,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
