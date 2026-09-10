# -*- coding: utf-8 -*-
"""In-memory monitoring models.

These are live observation records. Persistent SQLite records remain in
open_pit_competition.storage.models.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass(frozen=True)
class FixedStationConfig:
    station_id: str
    road_id: int
    lane_id: int
    x: float
    y: float
    z: float
    monitor_radius_m: float = 80.0
    observation_vertical_tolerance_m: float = 20.0
    camera_enabled: bool = True


@dataclass(frozen=True)
class CameraConfig:
    station_id: str
    placement: str
    x: float
    y: float
    z: float
    pitch: float
    yaw: float
    roll: float = 0.0
    image_width: int = 640
    image_height: int = 360
    target_fps: float = 5.0
    fov_deg: float = 90.0


@dataclass(frozen=True)
class StationObservation:
    timestamp_s: float
    station_id: str
    road_id: int
    lane_id: int

    # Observation-area traffic: what the fixed station physically observes
    # around its route anchor. This is what station_readings / dashboard use.
    vehicle_count: int
    avg_speed_kmh: float
    congestion_level: float

    # Monitored-road traffic: exact road/lane subset used to build RoadState.
    # This keeps adjacent/nearby mine roads from contaminating Decision road
    # cost while still letting the fixed station report vehicles in its view.
    road_vehicle_count: int = 0
    road_avg_speed_kmh: float = 0.0
    road_congestion_level: float = 0.0

    road_risk: float = 0.0
    visibility: float = 1.0
    camera_active: bool = False
    latest_frame_path: Optional[str] = None
    traffic_source: str = "carla_ground_truth"
    environment_source: str = "simulated_baseline"


@dataclass(frozen=True)
class MobileTelemetry:
    timestamp_s: float
    vehicle_id: str
    x: float
    y: float
    z: float
    speed_kmh: float
    road_id: Optional[int]
    lane_id: Optional[int]
    healthy: bool
    available: bool
    business_state: str = "IDLE"
    current_task_id: Optional[str] = None


@dataclass
class MonitoringSnapshot:
    timestamp_s: float
    stations: Dict[str, StationObservation] = field(default_factory=dict)
    vehicles: Dict[str, MobileTelemetry] = field(default_factory=dict)
