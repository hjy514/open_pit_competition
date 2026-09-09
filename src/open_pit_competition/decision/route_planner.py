from __future__ import annotations

import heapq
from typing import Dict, List, Optional, Tuple

from .models import RoadState, RoutePlan


class RoutePlanner:
    """Small deterministic shortest-time route planner.

    This is a pure Decision-layer component. It does not call CARLA.
    """

    def plan(
        self,
        start_point_id: str,
        end_point_id: str,
        roads: List[RoadState],
    ) -> Optional[RoutePlan]:
        if start_point_id == end_point_id:
            return RoutePlan(point_ids=[start_point_id])

        adjacency: Dict[str, List[Tuple[str, RoadState]]] = {}

        for road in roads:
            if not road.open:
                continue
            if road.distance_m < 0.0 or road.speed_limit_kmh <= 0.0:
                continue

            adjacency.setdefault(road.start_point_id, []).append(
                (road.end_point_id, road)
            )
            if road.bidirectional:
                adjacency.setdefault(road.end_point_id, []).append(
                    (road.start_point_id, road)
                )

        queue = [(0.0, start_point_id)]
        best_time = {start_point_id: 0.0}
        previous = {}

        while queue:
            current_time, point_id = heapq.heappop(queue)

            if current_time > best_time.get(point_id, float("inf")):
                continue

            if point_id == end_point_id:
                break

            edges = sorted(
                adjacency.get(point_id, []),
                key=lambda item: (item[1].road_id, item[0]),
            )

            for next_point, road in edges:
                speed_mps = road.speed_limit_kmh / 3.6
                travel_time_s = road.distance_m / speed_mps
                candidate_time = current_time + travel_time_s

                if candidate_time < best_time.get(next_point, float("inf")):
                    best_time[next_point] = candidate_time
                    previous[next_point] = (point_id, road)
                    heapq.heappush(queue, (candidate_time, next_point))

        if end_point_id not in best_time:
            return None

        point_ids = [end_point_id]
        road_ids = []
        distance_m = 0.0
        cursor = end_point_id

        while cursor != start_point_id:
            prev_point, road = previous[cursor]
            point_ids.append(prev_point)
            road_ids.append(road.road_id)
            distance_m += road.distance_m
            cursor = prev_point

        point_ids.reverse()
        road_ids.reverse()

        return RoutePlan(
            point_ids=point_ids,
            road_ids=road_ids,
            distance_m=distance_m,
            estimated_time_s=best_time[end_point_id],
        )
