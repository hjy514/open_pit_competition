#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import random

from open_pit_competition.decision import (
    DecisionReplanner,
    GreedyScheduler,
    MatrixRoutePlanner,
    TransportTask,
    VehicleState,
    WorldState,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--matrix",
        default="configs/decision_route_matrix.json",
    )
    parser.add_argument("--seed", type=int, default=1001)
    parser.add_argument(
        "--tasks",
        type=int,
        default=4,
        help="Keep this below 6 so an idle CAT truck can take over a failed task",
    )
    parser.add_argument("--min-haul-m", type=float, default=120.0)
    parser.add_argument("--max-haul-m", type=float, default=600.0)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    planner = MatrixRoutePlanner(args.matrix)
    scheduler = GreedyScheduler(route_planner=planner)
    replanner = DecisionReplanner()

    haul_routes = planner.reachable_haul_routes(
        min_distance_m=args.min_haul_m,
        max_distance_m=args.max_haul_m,
    )
    if not haul_routes:
        raise RuntimeError("No haul routes match the requested distance range")

    vehicles = [
        VehicleState("truck_1", current_spawn_index=12),
        VehicleState("truck_2", current_spawn_index=78),
        VehicleState("truck_3", current_spawn_index=78),
        VehicleState("truck_4", current_spawn_index=78),
        VehicleState("truck_5", current_spawn_index=78),
        VehicleState("truck_6", current_spawn_index=78),
    ]

    tasks = []
    for index in range(args.tasks):
        route = rng.choice(haul_routes)
        tasks.append(
            TransportTask(
                task_id="task_{:03d}".format(index + 1),
                origin_spawn_index=route.from_spawn_index,
                destination_spawn_index=route.to_spawn_index,
                release_time_s=0.0,
                priority=rng.randint(1, 5),
            )
        )

    world = WorldState(
        current_time_s=0.0,
        vehicles=vehicles,
        pending_tasks=tasks,
    )

    initial = scheduler.schedule(world)
    replanner.apply_assignments(world, initial)

    if not initial:
        raise RuntimeError("No initial assignment was generated")

    # Seeded choice makes the fault demo reproducible.
    victim_assignment = rng.choice(initial)
    victim_vehicle_id = victim_assignment.vehicle_id
    victim_task_id = victim_assignment.task_id

    print("========================================")
    print("DECISION V3 DYNAMIC REPLAN DEMO")
    print("seed          : {}".format(args.seed))
    print("initial tasks : {}".format(len(tasks)))
    print("initial assign: {}".format(len(initial)))
    print("========================================")

    print()
    print("[INITIAL ASSIGNMENTS]")
    for item in initial:
        print(
            "{} -> {} | empty {:.1f}m + haul {:.1f}m | score {:.1f}".format(
                item.vehicle_id,
                item.task_id,
                item.empty_route.distance_m,
                item.haul_route.distance_m,
                item.score,
            )
        )

    print()
    print(
        "[FAILURE] {} failed while executing {}".format(
            victim_vehicle_id,
            victim_task_id,
        )
    )

    released_task_id = replanner.fail_vehicle(
        world,
        victim_vehicle_id,
    )

    print(
        "[RELEASE] {} returned to pending queue".format(
            released_task_id
        )
    )

    replanned = scheduler.schedule(world)

    print()
    print("[REPLAN ASSIGNMENTS]")
    if not replanned:
        print("no feasible reassignment")
    else:
        for item in replanned:
            print(
                "{} -> {} | score {:.1f}".format(
                    item.vehicle_id,
                    item.task_id,
                    item.score,
                )
            )

    takeover = [
        item
        for item in replanned
        if item.task_id == released_task_id
    ]

    print()
    if takeover:
        print(
            "[TAKEOVER] {} takes over {} from failed {}".format(
                takeover[0].vehicle_id,
                released_task_id,
                victim_vehicle_id,
            )
        )
    else:
        print(
            "[TAKEOVER] released task {} has no current takeover".format(
                released_task_id
            )
        )

    replanner.recover_vehicle(world, victim_vehicle_id)
    print(
        "[RECOVERY] {} healthy={} available={}".format(
            victim_vehicle_id,
            True,
            True,
        )
    )


if __name__ == "__main__":
    main()
