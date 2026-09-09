import json

from open_pit_competition.decision import (
    DecisionReplanner,
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
                "distance_m": 200.0,
                "estimated_time_s": 40.0,
            },
            {
                "route_id": "haul_18_to_17",
                "route_type": "haul_to_dump",
                "from_spawn_point_index": 18,
                "to_spawn_point_index": 17,
                "reachable": True,
                "distance_m": 300.0,
                "estimated_time_s": 60.0,
            },
        ]
    }
    path = tmp_path / "matrix.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def _world():
    return WorldState(
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


def test_apply_assignment_marks_vehicle_and_task_busy(tmp_path):
    planner = MatrixRoutePlanner(_matrix(tmp_path))
    scheduler = GreedyScheduler(planner)
    replanner = DecisionReplanner()
    world = _world()

    assignments = scheduler.schedule(world)
    replanner.apply_assignments(world, assignments)

    assert assignments[0].vehicle_id == "truck_1"
    assert world.vehicles[0].current_task_id == "task_1"
    assert world.pending_tasks[0].status == "assigned"


def test_failure_releases_task_and_marks_vehicle_unavailable(tmp_path):
    planner = MatrixRoutePlanner(_matrix(tmp_path))
    scheduler = GreedyScheduler(planner)
    replanner = DecisionReplanner()
    world = _world()

    assignments = scheduler.schedule(world)
    replanner.apply_assignments(world, assignments)
    released = replanner.fail_vehicle(world, "truck_1")

    assert released == "task_1"
    assert world.vehicles[0].healthy is False
    assert world.vehicles[0].available is False
    assert world.vehicles[0].current_task_id is None
    assert world.pending_tasks[0].status == "pending"


def test_released_task_is_taken_over_by_idle_vehicle(tmp_path):
    planner = MatrixRoutePlanner(_matrix(tmp_path))
    scheduler = GreedyScheduler(planner)
    replanner = DecisionReplanner()
    world = _world()

    initial = scheduler.schedule(world)
    replanner.apply_assignments(world, initial)

    replanner.fail_vehicle(world, "truck_1")
    replanned = scheduler.schedule(world)

    assert len(replanned) == 1
    assert replanned[0].vehicle_id == "truck_2"
    assert replanned[0].task_id == "task_1"


def test_recovered_vehicle_returns_to_available_pool(tmp_path):
    replanner = DecisionReplanner()
    world = _world()

    replanner.fail_vehicle(world, "truck_1")
    replanner.recover_vehicle(world, "truck_1")

    assert world.vehicles[0].healthy is True
    assert world.vehicles[0].available is True
