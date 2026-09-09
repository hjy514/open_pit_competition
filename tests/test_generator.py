from open_pit_competition.simulation.generator import ScenarioGenerator


TEMPLATE = {
    "scenario_id": "R01",
    "name": "random_complex",
    "duration_s": 200.0,
    "randomization": {
        "vehicle_failure": {
            "enabled": True,
            "probability": 0.5,
            "time_range_s": [30.0, 150.0],
            "recovery_time_s": [10.0, 20.0],
        },
        "road_closure": {
            "enabled": True,
            "probability": 1.0,
            "time_range_s": [50.0, 120.0],
            "duration_s": [10.0, 30.0],
        },
        "task_arrival": {
            "enabled": True,
            "interval_s": [10.0, 20.0],
            "priority": [1, 5],
            "origin_destination_pairs": [
                {
                    "origin_point_id": "load_a",
                    "destination_point_id": "dump_a",
                }
            ],
        },
    },
}


def test_same_seed_is_reproducible():
    a = ScenarioGenerator(seed=1001).build_instance(
        TEMPLATE,
        vehicle_ids=["truck_1", "truck_2", "truck_3"],
    )
    b = ScenarioGenerator(seed=1001).build_instance(
        TEMPLATE,
        vehicle_ids=["truck_1", "truck_2", "truck_3"],
    )

    assert a == b


def test_different_seed_changes_instance():
    a = ScenarioGenerator(seed=1001).build_instance(
        TEMPLATE,
        vehicle_ids=["truck_1", "truck_2", "truck_3"],
    )
    b = ScenarioGenerator(seed=1002).build_instance(
        TEMPLATE,
        vehicle_ids=["truck_1", "truck_2", "truck_3"],
    )

    assert a != b
