# -*- coding: utf-8 -*-
"""Persistent data records for the open-pit closed-loop data layer.

These records describe what is persisted to SQLite. They deliberately do not
replace Decision's in-memory WorldState models. Closed Loop / StateBuilder will
translate runtime/monitoring data into Decision models later.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class FixedStationRecord:
    station_id: str
    station_type: str
    x: float
    y: float
    z: float
    road_id: Optional[int] = None
    lane_id: Optional[int] = None
    monitor_radius_m: float = 80.0
    camera_enabled: bool = False
    active: bool = True


@dataclass
class StationReadingRecord:
    timestamp_s: float
    station_id: str
    vehicle_count: int = 0
    avg_speed_kmh: float = 0.0
    congestion_level: float = 0.0
    road_risk: float = 0.0
    visibility: float = 1.0


@dataclass
class VehicleTelemetryRecord:
    timestamp_s: float
    vehicle_id: str
    x: float
    y: float
    z: float
    speed_kmh: float
    road_id: Optional[int] = None
    lane_id: Optional[int] = None
    healthy: bool = True
    available: bool = True
    business_state: str = "IDLE"
    current_task_id: Optional[str] = None


@dataclass
class TaskRecord:
    task_id: str
    origin_spawn_index: int
    destination_spawn_index: int
    priority: int = 1
    release_time_s: float = 0.0
    status: str = "PENDING"
    assigned_vehicle_id: Optional[str] = None
    created_at_s: Optional[float] = None
    started_at_s: Optional[float] = None
    completed_at_s: Optional[float] = None


@dataclass
class RoadStateRecord:
    timestamp_s: float
    road_id: int
    lane_id: int
    open: bool = True
    traffic_level: float = 0.0
    risk_level: float = 0.0
    visibility: float = 1.0
    cost_multiplier: float = 1.0
    source_station_id: Optional[str] = None


@dataclass
class EventRecord:
    event_id: str
    timestamp_s: float
    event_type: str
    target_type: str
    target_id: str
    payload_json: str = "{}"
    handled: bool = False


@dataclass
class AssignmentRecord:
    timestamp_s: float
    vehicle_id: str
    task_id: str
    empty_route_id: Optional[str] = None
    haul_route_id: Optional[str] = None
    score: float = 0.0
    reason: str = ""
