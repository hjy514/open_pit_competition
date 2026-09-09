from __future__ import annotations

from typing import List, Optional, Tuple

from .models import Assignment, TransportTask, VehicleState, WorldState
from .policy import DispatchPolicy
from .route_planner import RoutePlanner


class GreedyScheduler:
    """Deterministic baseline scheduler.

    It repeatedly selects the globally best feasible vehicle-task pair.
    No CARLA calls are made here.
    """

    def __init__(
        self,
        route_planner: RoutePlanner = None,
        policy: DispatchPolicy = None,
    ) -> None:
        self.route_planner = route_planner or RoutePlanner()
        self.policy = policy or DispatchPolicy()

    def schedule(self, world_state: WorldState) -> List[Assignment]:
        vehicles = [
            vehicle
            for vehicle in world_state.vehicles
            if vehicle.available
            and vehicle.healthy
            and vehicle.current_task_id is None
        ]

        tasks = [
            task
            for task in world_state.pending_tasks
            if task.status == "pending"
            and task.release_time_s <= world_state.current_time_s
        ]

        vehicles = sorted(vehicles, key=lambda item: item.vehicle_id)
        tasks = sorted(
            tasks,
            key=lambda item: (-item.priority, item.release_time_s, item.task_id),
        )

        remaining_vehicles = list(vehicles)
        remaining_tasks = list(tasks)
        assignments: List[Assignment] = []

        while remaining_vehicles and remaining_tasks:
            best = self._best_pair(
                remaining_vehicles,
                remaining_tasks,
                world_state,
            )

            if best is None:
                break

            vehicle, task, assignment = best
            assignments.append(assignment)
            remaining_vehicles.remove(vehicle)
            remaining_tasks.remove(task)

        return assignments

    def _best_pair(
        self,
        vehicles: List[VehicleState],
        tasks: List[TransportTask],
        world_state: WorldState,
    ) -> Optional[Tuple[VehicleState, TransportTask, Assignment]]:
        candidates = []

        for vehicle in vehicles:
            for task in tasks:
                empty_route = self.route_planner.plan(
                    start_point_id=vehicle.current_point_id,
                    end_point_id=task.origin_point_id,
                    roads=world_state.roads,
                )
                if empty_route is None:
                    continue

                haul_route = self.route_planner.plan(
                    start_point_id=task.origin_point_id,
                    end_point_id=task.destination_point_id,
                    roads=world_state.roads,
                )
                if haul_route is None:
                    continue

                evaluation = self.policy.evaluate(
                    vehicle=vehicle,
                    task=task,
                    empty_route=empty_route,
                    haul_route=haul_route,
                )

                assignment = Assignment(
                    vehicle_id=vehicle.vehicle_id,
                    task_id=task.task_id,
                    empty_route=empty_route,
                    haul_route=haul_route,
                    score=evaluation.score,
                    reason=evaluation.reason,
                )

                candidates.append(
                    (
                        evaluation.score,
                        vehicle.vehicle_id,
                        task.task_id,
                        vehicle,
                        task,
                        assignment,
                    )
                )

        if not candidates:
            return None

        candidates.sort(key=lambda item: (item[0], item[1], item[2]))
        _, _, _, vehicle, task, assignment = candidates[0]
        return vehicle, task, assignment
