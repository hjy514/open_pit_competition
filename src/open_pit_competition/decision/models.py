from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class OperatingPoint:
    """Logical mine operating point.

    The point_id is intentionally independent from a CARLA spawn-point index.
    A later map/resource layer can map this logical id to CARLA geometry.
    """

    point_id: str
    point_type: str
    capacity: int = 1


@dataclass
class RoadState:
    road_id: str
    start_point_id: str
    end_point_id: str
    distance_m: float
    speed_limit_kmh: float
    open: bool = True
    bidirectional: bool = True


@dataclass
class VehicleState:
    vehicle_id: str
    current_point_id: str
    available: bool = True
    healthy: bool = True
    current_task_id: Optional[str] = None


@dataclass
class TransportTask:
    task_id: str
    origin_point_id: str
    destination_point_id: str
    release_time_s: float = 0.0
    priority: int = 1
    status: str = "pending"


@dataclass
class RoutePlan:
    point_ids: List[str] = field(default_factory=list)
    road_ids: List[str] = field(default_factory=list)
    distance_m: float = 0.0
    estimated_time_s: float = 0.0


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
    roads: List[RoadState] = field(default_factory=list)
    operating_points: List[OperatingPoint] = field(default_factory=list)
