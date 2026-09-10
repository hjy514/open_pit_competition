# -*- coding: utf-8 -*-
"""Translate live execution/monitoring state into Decision WorldState."""

from __future__ import annotations

from typing import Dict, Iterable, Mapping, Optional

from open_pit_competition.decision.models import (
    OperatingPoint,
    TransportTask,
    VehicleState,
    WorldState,
)


class ClosedLoopStateBuilder:
    """Build a Decision WorldState without querying SQLite or CARLA directly."""

    def build(
        self,
        current_time_s: float,
        vehicle_states: Mapping[str, VehicleState],
        tasks: Mapping[str, TransportTask],
        operating_points: Iterable[OperatingPoint],
        monitoring_snapshot=None,
        min_vehicle_observation_time: Optional[Dict[str, float]] = None,
    ) -> WorldState:
        minimum_times = min_vehicle_observation_time or {}

        if monitoring_snapshot is not None:
            for vehicle_id, telemetry in monitoring_snapshot.vehicles.items():
                state = vehicle_states.get(vehicle_id)
                if state is None:
                    continue

                # A Runtime event is more authoritative than a stale Monitoring
                # sample collected immediately before that event.
                minimum = float(minimum_times.get(vehicle_id, -1.0))
                if float(telemetry.timestamp_s) + 1e-9 < minimum:
                    continue

                state.healthy = bool(telemetry.healthy)
                state.available = bool(telemetry.available)

        return WorldState(
            current_time_s=float(current_time_s),
            vehicles=list(vehicle_states.values()),
            pending_tasks=list(tasks.values()),
            operating_points=list(operating_points),
        )
