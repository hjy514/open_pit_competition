#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import random

from open_pit_competition.decision import (
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
    parser.add_argument("--tasks", type=int, default=6)
    parser.add_argument("--min-haul-m", type=float, default=120.0)
    parser.add_argument("--max-haul-m", type=float, default=600.0)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    planner = MatrixRoutePlanner(args.matrix)

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

    scheduler = GreedyScheduler(route_planner=planner)
    assignments = scheduler.schedule(world)

    print("========================================")
    print("DECISION V2 DEMO")
    print("seed       : {}".format(args.seed))
    print("tasks      : {}".format(len(tasks)))
    print("assignments: {}".format(len(assignments)))
    print("========================================")

    print()
    print("[TASKS]")
    for task in tasks:
        print(
            "{} | load={} -> dump={} | priority={}".format(
                task.task_id,
                task.origin_spawn_index,
                task.destination_spawn_index,
                task.priority,
            )
        )

    print()
    print("[ASSIGNMENTS]")
    for item in assignments:
        print(
            "{} -> {} | empty {:.1f}m + haul {:.1f}m | score {:.1f}".format(
                item.vehicle_id,
                item.task_id,
                item.empty_route.distance_m,
                item.haul_route.distance_m,
                item.score,
            )
        )
        print("  {}".format(item.reason))


if __name__ == "__main__":
    main()
