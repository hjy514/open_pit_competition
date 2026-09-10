# -*- coding: utf-8 -*-
"""Mobile CAT mine-truck telemetry collector."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from .models import MobileTelemetry


class MobileCollector:
    """Convert existing CarlaAdapter snapshots into telemetry records."""

    def collect(
        self,
        timestamp_s: float,
        snapshots: Iterable[object],
        business_states: Optional[Dict[str, str]] = None,
        current_task_ids: Optional[Dict[str, Optional[str]]] = None,
    ) -> List[MobileTelemetry]:
        business_states = business_states or {}
        current_task_ids = current_task_ids or {}

        result = []
        for snapshot in snapshots:
            vehicle_id = str(getattr(snapshot, "vehicle_id"))
            healthy = bool(getattr(snapshot, "healthy", True))
            available = bool(getattr(snapshot, "available", True))

            if vehicle_id in business_states:
                business_state = str(business_states[vehicle_id])
            elif not healthy:
                business_state = "FAULT"
            else:
                # Runtime does not yet own task lifecycle; Closed Loop V1 will
                # supply TO_LOADING / LOADING / TO_DUMP / UNLOADING here.
                business_state = "IDLE"

            result.append(
                MobileTelemetry(
                    timestamp_s=float(timestamp_s),
                    vehicle_id=vehicle_id,
                    x=float(getattr(snapshot, "x")),
                    y=float(getattr(snapshot, "y")),
                    z=float(getattr(snapshot, "z")),
                    speed_kmh=round(
                        float(getattr(snapshot, "speed_mps", 0.0)) * 3.6,
                        3,
                    ),
                    road_id=getattr(snapshot, "road_id", None),
                    lane_id=getattr(snapshot, "lane_id", None),
                    healthy=healthy,
                    available=available,
                    business_state=business_state,
                    current_task_id=current_task_ids.get(vehicle_id),
                )
            )

        return result
