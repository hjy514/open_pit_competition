from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class OperatingPoint:
    point_id: str
    point_type: str
    spawn_index: int
    capacity: int = 1
    active: bool = True


@dataclass
class VehicleState:
    vehicle_id: str
    current_spawn_index: int
    available: bool = True
    healthy: bool = True
    current_task_id: Optional[str] = None


@dataclass
class TransportTask:
    task_id: str
    origin_spawn_index: int
    destination_spawn_index: int
    release_time_s: float = 0.0
    priority: int = 1
    status: str = "pending"


@dataclass
class RoutePlan:
    route_id: str
    route_type: str
    from_spawn_index: int
    to_spawn_index: int
    distance_m: float
    estimated_time_s: float


@dataclass
class Assignment:
    vehicle_id: str
    task_id: str
    empty_route: RoutePlan
    haul_route: RoutePlan
    score: float
    reason: str


@dataclass
class WorldState:
    current_time_s: float
    vehicles: List[VehicleState] = field(default_factory=list)
    pending_tasks: List[TransportTask] = field(default_factory=list)
    operating_points: List[OperatingPoint] = field(default_factory=list)
