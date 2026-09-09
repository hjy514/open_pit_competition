from open_pit_competition.decision import (
    GreedyScheduler,
    RoadState,
    TransportTask,
    VehicleState,
    WorldState,
)


def _world():
    roads = [
        RoadState(
            road_id="r_a_load",
            start_point_id="parking",
            end_point_id="load_a",
            distance_m=100.0,
            speed_limit_kmh=20.0,
        ),
        RoadState(
            road_id="r_load_dump",
            start_point_id="load_a",
            end_point_id="dump_a",
            distance_m=300.0,
            speed_limit_kmh=20.0,
        ),
        RoadState(
            road_id="r_b_load",
            start_point_id="parking_b",
            end_point_id="load_a",
            distance_m=200.0,
            speed_limit_kmh=20.0,
        ),
    ]

    return WorldState(
        current_time_s=100.0,
        vehicles=[
            VehicleState(
                vehicle_id="truck_1",
                current_point_id="parking",
            ),
            VehicleState(
                vehicle_id="truck_2",
                current_point_id="parking_b",
            ),
        ],
        pending_tasks=[
            TransportTask(
                task_id="task_1",
                origin_point_id="load_a",
                destination_point_id="dump_a",
                release_time_s=0.0,
                priority=1,
            ),
            TransportTask(
                task_id="task_2",
                origin_point_id="load_a",
                destination_point_id="dump_a",
                release_time_s=0.0,
                priority=2,
            ),
        ],
        roads=roads,
    )


def test_scheduler_assigns_unique_vehicles_and_tasks():
    scheduler = GreedyScheduler()
    assignments = scheduler.schedule(_world())

    assert len(assignments) == 2
    assert len({item.vehicle_id for item in assignments}) == 2
    assert len({item.task_id for item in assignments}) == 2


def test_unavailable_vehicle_is_not_assigned():
    world = _world()
    world.vehicles[0].available = False

    assignments = GreedyScheduler().schedule(world)

    assert all(item.vehicle_id != "truck_1" for item in assignments)


def test_closed_haul_road_makes_task_infeasible():
    world = _world()

    for road in world.roads:
        if road.road_id == "r_load_dump":
            road.open = False

    assignments = GreedyScheduler().schedule(world)

    assert assignments == []
