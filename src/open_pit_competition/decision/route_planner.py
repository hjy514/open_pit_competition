from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models import RoutePlan


class MatrixRoutePlanner:
    """Decision-layer route planner backed by CARLA-precomputed route costs.

    Scheduling never calls CARLA. Closed Loop may later ask the Simulation
    layer to execute the selected OD route using the same map/planner contract.
    """

    def __init__(self, matrix_path: str) -> None:
        self.matrix_path = str(matrix_path)
        self.map_id: Optional[str] = None
        self.sampling_resolution_m: float = 2.0
        self.reference_speed_kmh: float = 14.0
        self.loading_spawn_indices = set()
        self.dump_spawn_indices = set()
        self._routes: Dict[Tuple[str, int, int], RoutePlan] = {}
        self._load()

    def _load(self) -> None:
        path = Path(self.matrix_path)
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        self.map_id = str(data["map_id"]) if data.get("map_id") is not None else None
        self.sampling_resolution_m = float(data.get("sampling_resolution_m", 2.0))
        self.reference_speed_kmh = float(data.get("reference_speed_kmh", 14.0))
        self.loading_spawn_indices = {
            int(x) for x in data.get("loading_spawn_indices", [])
        }
        self.dump_spawn_indices = {
            int(x) for x in data.get("dump_spawn_indices", [])
        }

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
        from_index = int(from_spawn_index)
        loading_index = int(loading_spawn_index)

        if from_index == loading_index:
            return RoutePlan(
                route_id="empty_to_loading_{}_to_{}_zero".format(
                    from_index, loading_index
                ),
                route_type="empty_to_loading",
                from_spawn_index=from_index,
                to_spawn_index=loading_index,
                distance_m=0.0,
                estimated_time_s=0.0,
            )

        return self._routes.get(("empty_to_loading", from_index, loading_index))

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
            key=lambda item: (item.from_spawn_index, item.to_spawn_index),
        )
