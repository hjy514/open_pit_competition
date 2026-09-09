from __future__ import annotations

from typing import List, Optional

from .models import Assignment, TransportTask, VehicleState, WorldState
from .scheduler import GreedyScheduler


class DecisionReplanner:
    """Small state-transition helper for Decision V3.

    This remains a pure Decision-layer component:
    - no CARLA calls
    - no Runtime calls
    - only mutates the supplied WorldState

    It supports the MVP lifecycle needed for dynamic rescheduling:
    assignment -> vehicle failure -> task release -> reschedule -> recovery.
    """

    def apply_assignments(
        self,
        world_state: WorldState,
        assignments: List[Assignment],
    ) -> None:
        vehicles = {
            vehicle.vehicle_id: vehicle
            for vehicle in world_state.vehicles
        }
        tasks = {
            task.task_id: task
            for task in world_state.pending_tasks
        }

        for assignment in assignments:
            vehicle = vehicles.get(assignment.vehicle_id)
            task = tasks.get(assignment.task_id)

            if vehicle is None or task is None:
                continue

            vehicle.current_task_id = task.task_id
            task.status = "assigned"

    def fail_vehicle(
        self,
        world_state: WorldState,
        vehicle_id: str,
    ) -> Optional[str]:
        vehicle = self._vehicle(world_state, vehicle_id)

        vehicle.healthy = False
        vehicle.available = False

        released_task_id = vehicle.current_task_id
        vehicle.current_task_id = None

        if released_task_id is not None:
            task = self._task(world_state, released_task_id)
            if task is not None:
                task.status = "pending"

        return released_task_id

    def recover_vehicle(
        self,
        world_state: WorldState,
        vehicle_id: str,
    ) -> None:
        vehicle = self._vehicle(world_state, vehicle_id)
        vehicle.healthy = True
        vehicle.available = True

    def replan_after_failure(
        self,
        world_state: WorldState,
        vehicle_id: str,
        scheduler: GreedyScheduler,
    ) -> List[Assignment]:
        self.fail_vehicle(world_state, vehicle_id)
        return scheduler.schedule(world_state)

    @staticmethod
    def _vehicle(
        world_state: WorldState,
        vehicle_id: str,
    ) -> VehicleState:
        for vehicle in world_state.vehicles:
            if vehicle.vehicle_id == vehicle_id:
                return vehicle
        raise KeyError("Unknown vehicle_id: {}".format(vehicle_id))

    @staticmethod
    def _task(
        world_state: WorldState,
        task_id: str,
    ) -> Optional[TransportTask]:
        for task in world_state.pending_tasks:
            if task.task_id == task_id:
                return task
        return None
