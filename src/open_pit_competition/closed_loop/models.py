# -*- coding: utf-8 -*-
"""Closed Loop V1 execution-state models.

Decision models remain unchanged. These records only describe the business
lifecycle needed to execute Decision assignments in CARLA.
"""

from dataclasses import dataclass
from typing import Optional

from open_pit_competition.decision.models import Assignment


@dataclass
class VehicleExecutionState:
    vehicle_id: str
    business_state: str = "IDLE"
    assignment: Optional[Assignment] = None
    target_spawn_index: Optional[int] = None
    state_since_s: float = 0.0
    service_started_at_s: Optional[float] = None


@dataclass
class TaskRuntimeMeta:
    task_id: str
    assigned_vehicle_id: Optional[str] = None
    created_at_s: float = 0.0
    started_at_s: Optional[float] = None
    completed_at_s: Optional[float] = None
    assignment_count: int = 0
