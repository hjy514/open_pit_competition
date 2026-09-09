import json

from open_pit_competition.decision import (
    GreedyScheduler,
    MatrixRoutePlanner,
    TransportTask,
    VehicleState,
    WorldState,
)


def _matrix(tmp_path):
    data = {
        "routes": [
            {
                "route_id": "empty_12_to_18",
                "route_type": "empty_to_loading",
                "from_spawn_point_index": 12,
                "to_spawn_point_index": 18,
                "reachable": True,
                "distance_m": 100.0,
                "estimated_time_s": 20.0,
            },
            {
                "route_id": "empty_78_to_18",
                "route_type": "empty_to_loading",
                "from_spawn_point_index": 78,
                "to_spawn_point_index": 18,
                "reachable": True,
                "distance_m": 300.0,
                "estimated_time_s": 60.0,
            },
            {
                "route_id": "haul_18_to_17",
                "route_type": "haul_to_dump",
                "from_spawn_point_index": 18,
                "to_spawn_point_index": 17,
                "reachable": True,
                "distance_m": 400.0,
                "estimated_time_s": 80.0,
            },
        ]
    }
    path = tmp_path / "matrix.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_scheduler_prefers_lower_total_route_cost(tmp_path):
    planner = MatrixRoutePlanner(_matrix(tmp_path))
    world = WorldState(
        current_time_s=0.0,
        vehicles=[
            VehicleState("truck_1", current_spawn_index=12),
            VehicleState("truck_2", current_spawn_index=78),
        ],
        pending_tasks=[
            TransportTask(
                "task_1",
                origin_spawn_index=18,
                destination_spawn_index=17,
                priority=1,
            )
        ],
    )

    assignments = GreedyScheduler(planner).schedule(world)

    assert len(assignments) == 1
    assert assignments[0].vehicle_id == "truck_1"


def test_unavailable_vehicle_is_excluded(tmp_path):
    planner = MatrixRoutePlanner(_matrix(tmp_path))
    world = WorldState(
        current_time_s=0.0,
        vehicles=[
            VehicleState(
                "truck_1",
                current_spawn_index=12,
                available=False,
            ),
            VehicleState("truck_2", current_spawn_index=78),
        ],
        pending_tasks=[
            TransportTask(
                "task_1",
                origin_spawn_index=18,
                destination_spawn_index=17,
                priority=1,
            )
        ],
    )

    assignments = GreedyScheduler(planner).schedule(world)

    assert len(assignments) == 1
    assert assignments[0].vehicle_id == "truck_2"


def test_unreachable_task_is_not_assigned(tmp_path):
    planner = MatrixRoutePlanner(_matrix(tmp_path))
    world = WorldState(
        current_time_s=0.0,
        vehicles=[VehicleState("truck_1", current_spawn_index=12)],
        pending_tasks=[
            TransportTask(
                "task_missing",
                origin_spawn_index=18,
                destination_spawn_index=999,
            )
        ],
    )

    assert GreedyScheduler(planner).schedule(world) == []
