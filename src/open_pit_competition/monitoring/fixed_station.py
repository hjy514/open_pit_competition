# -*- coding: utf-8 -*-
"""Fixed monitoring-station observation logic.

Important semantics:
- station reading = nearby observation area around the camera/road anchor
- RoadState traffic = exact monitored road/lane subset

This split is intentional for open-pit mines where multiple road segments can
be close in XY or visible from one camera.
"""

from __future__ import annotations

import math
from typing import Iterable

from .models import FixedStationConfig, StationObservation


def _distance_3d(x1, y1, z1, x2, y2, z2):
    return math.sqrt(
        (float(x2) - float(x1)) ** 2
        + (float(y2) - float(y1)) ** 2
        + (float(z2) - float(z1)) ** 2
    )


def _congestion_level(vehicle_count, avg_speed_kmh, reference_speed_kmh=14.0):
    """Return a simple [0, 1] traffic indicator.

    Transparent baseline:
    - occupancy contributes 55%
    - slowdown contributes 45%
    Empty observation is always zero congestion.
    """
    count = int(vehicle_count)
    if count <= 0:
        return 0.0

    occupancy = min(1.0, float(count) / 3.0)
    ref = max(0.1, float(reference_speed_kmh))
    speed_ratio = min(1.0, max(0.0, float(avg_speed_kmh) / ref))
    slowdown = 1.0 - speed_ratio
    return min(1.0, max(0.0, 0.55 * occupancy + 0.45 * slowdown))


def simulated_environment_state(timestamp_s, station_index=0):
    """Low-amplitude deterministic baseline for fields not sensed by CARLA."""
    t = float(timestamp_s)
    phase = float(station_index) * 0.91

    wave_a = 0.5 + 0.5 * math.sin(t / 23.0 + phase)
    wave_b = 0.5 + 0.5 * math.sin(t / 31.0 + phase + 1.2)

    road_risk = 0.06 + 0.10 * wave_a
    visibility = 0.88 + 0.10 * wave_b

    return (
        round(min(1.0, max(0.0, road_risk)), 4),
        round(min(1.0, max(0.0, visibility)), 4),
    )


class FixedStationObserver:
    """Observe CAT trucks around one fixed monitoring station."""

    def __init__(self, config: FixedStationConfig, station_index: int = 0):
        self.config = config
        self.station_index = int(station_index)

    def _nearby_snapshots(self, snapshots: Iterable[object]):
        """Physical observation area, independent of CARLA road/lane ids.

        The Z tolerance prevents a station from accidentally counting traffic
        on a very different mine bench merely because the XY projection is
        close.
        """
        result = []
        cfg = self.config

        for snapshot in snapshots:
            sx = float(getattr(snapshot, "x"))
            sy = float(getattr(snapshot, "y"))
            sz = float(getattr(snapshot, "z"))

            if abs(sz - float(cfg.z)) > cfg.observation_vertical_tolerance_m:
                continue

            distance = _distance_3d(
                cfg.x,
                cfg.y,
                cfg.z,
                sx,
                sy,
                sz,
            )
            if distance <= cfg.monitor_radius_m:
                result.append(snapshot)

        return result

    def _road_snapshots(self, nearby):
        """Exact monitored-road/lane subset used for Decision RoadState."""
        cfg = self.config
        return [
            snapshot
            for snapshot in nearby
            if getattr(snapshot, "road_id", None) == cfg.road_id
            and getattr(snapshot, "lane_id", None) == cfg.lane_id
        ]

    @staticmethod
    def _traffic_values(snapshots):
        snapshots = list(snapshots)
        speeds = [
            float(getattr(item, "speed_mps", 0.0)) * 3.6
            for item in snapshots
        ]
        count = len(snapshots)
        avg = sum(speeds) / float(count) if count else 0.0
        congestion = _congestion_level(count, avg)
        return count, round(avg, 3), round(congestion, 4)

    def observe(
        self,
        timestamp_s: float,
        snapshots: Iterable[object],
        camera_active: bool = False,
        latest_frame_path: str = None,
    ) -> StationObservation:
        nearby = self._nearby_snapshots(snapshots)
        road_only = self._road_snapshots(nearby)

        area_count, area_avg, area_congestion = self._traffic_values(nearby)
        road_count, road_avg, road_congestion = self._traffic_values(road_only)

        road_risk, visibility = simulated_environment_state(
            timestamp_s,
            self.station_index,
        )

        return StationObservation(
            timestamp_s=float(timestamp_s),
            station_id=self.config.station_id,
            road_id=self.config.road_id,
            lane_id=self.config.lane_id,
            vehicle_count=area_count,
            avg_speed_kmh=area_avg,
            congestion_level=area_congestion,
            road_vehicle_count=road_count,
            road_avg_speed_kmh=road_avg,
            road_congestion_level=road_congestion,
            road_risk=road_risk,
            visibility=visibility,
            camera_active=bool(camera_active),
            latest_frame_path=latest_frame_path,
        )
