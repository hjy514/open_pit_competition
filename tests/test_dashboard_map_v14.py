from __future__ import annotations

from open_pit_competition.dashboard.service import DashboardService


class Location:
    def __init__(self, x, y, z=0.0):
        self.x = x
        self.y = y
        self.z = z


class Transform:
    def __init__(self, x, y, z=0.0):
        self.location = Location(x, y, z)


class Waypoint:
    def __init__(
        self,
        road_id,
        section_id,
        lane_id,
        s,
        x,
        y,
        is_junction=False,
    ):
        self.road_id = road_id
        self.section_id = section_id
        self.lane_id = lane_id
        self.s = s
        self.transform = Transform(x, y)
        self.is_junction = is_junction


def test_carla_road_polylines_preserve_world_coordinates():
    waypoints = [
        Waypoint(4, 0, -1, 4.0, -420.0, 188.0),
        Waypoint(4, 0, -1, 0.0, -424.0, 188.0),
        Waypoint(4, 0, -1, 2.0, -422.0, 188.0),
    ]

    roads = DashboardService._road_polylines_from_waypoints(
        waypoints,
        max_gap_m=8.0,
    )

    assert len(roads) == 1
    assert roads[0]["road_id"] == 4
    assert roads[0]["lane_id"] == -1
    assert roads[0]["points"] == [
        {"x": -424.0, "y": 188.0, "z": 0.0},
        {"x": -422.0, "y": 188.0, "z": 0.0},
        {"x": -420.0, "y": 188.0, "z": 0.0},
    ]


def test_carla_road_polylines_do_not_bridge_large_gap():
    waypoints = [
        Waypoint(50, 0, 1, 0.0, -650.0, -32.0),
        Waypoint(50, 0, 1, 2.0, -648.0, -32.0),
        Waypoint(50, 0, 1, 100.0, -500.0, -32.0),
        Waypoint(50, 0, 1, 102.0, -498.0, -32.0),
    ]

    roads = DashboardService._road_polylines_from_waypoints(
        waypoints,
        max_gap_m=8.0,
    )

    assert len(roads) == 2
    assert roads[0]["points"][0]["y"] == -32.0
    assert roads[1]["points"][0]["y"] == -32.0
