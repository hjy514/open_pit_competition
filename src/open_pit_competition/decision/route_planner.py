from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models import RoutePlan


class MatrixRoutePlanner:
    """Decision-layer route planner backed by CARLA-precomputed route costs.

    It does not call CARLA during scheduling.
    """

    def __init__(self, matrix_path: str) -> None:
        self.matrix_path = str(matrix_path)
        self._routes: Dict[Tuple[str, int, int], RoutePlan] = {}
        self._load()

    def _load(self) -> None:
        path = Path(self.matrix_path)
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        for item in data.get("routes", []):
            if not item.get("reachable", False):
                continue

            route_type = str(item["route_type"])
            from_index = int(item["from_spawn_point_index"])
            to_index = int(item["to_spawn_point_index"])

            plan = RoutePlan(
                route_id=str(item["route_id"]),
                route_type=route_type,
                from_spawn_index=from_index,
                to_spawn_index=to_index,
                distance_m=float(item.get("distance_m", 0.0)),
                estimated_time_s=float(item.get("estimated_time_s", 0.0)),
            )
            self._routes[(route_type, from_index, to_index)] = plan

    def plan_empty(
        self,
        from_spawn_index: int,
        loading_spawn_index: int,
    ) -> Optional[RoutePlan]:
        return self._routes.get(
            (
                "empty_to_loading",
                int(from_spawn_index),
                int(loading_spawn_index),
            )
        )

    def plan_haul(
        self,
        loading_spawn_index: int,
        dump_spawn_index: int,
    ) -> Optional[RoutePlan]:
        return self._routes.get(
            (
                "haul_to_dump",
                int(loading_spawn_index),
                int(dump_spawn_index),
            )
        )

    def reachable_haul_routes(
        self,
        min_distance_m: float = 0.0,
        max_distance_m: Optional[float] = None,
    ) -> List[RoutePlan]:
        result = []

        for (route_type, _, _), plan in self._routes.items():
            if route_type != "haul_to_dump":
                continue
            if plan.distance_m < float(min_distance_m):
                continue
            if max_distance_m is not None and plan.distance_m > float(max_distance_m):
                continue
            result.append(plan)

        return sorted(
            result,
            key=lambda item: (
                item.from_spawn_index,
                item.to_spawn_index,
            ),
        )
