from copy import deepcopy

from open_pit_competition.simulation.task_generator import (
    RandomTaskConfigGenerator,
)


BASE = {
    "schema_version": "closed-loop-formal-cat-calibrated-v1",
    "task_count": 6,
    "task_seed": 20260910,
    "task_release_interval_s": 0.0,
    "task_templates": [
        {
            "task_id": "formal_task_001",
            "origin_spawn_index": 12,
            "destination_spawn_index": 48,
            "release_time_s": 0.0,
            "priority": 3,
        },
        {
            "task_id": "formal_task_002",
            "origin_spawn_index": 78,
            "destination_spawn_index": 48,
            "release_time_s": 0.0,
            "priority": 2,
        },
        {
            "task_id": "formal_task_003",
            "origin_spawn_index": 78,
            "destination_spawn_index": 48,
            "release_time_s": 0.0,
            "priority": 2,
        },
        {
            "task_id": "formal_task_004",
            "origin_spawn_index": 78,
            "destination_spawn_index": 48,
            "release_time_s": 0.0,
            "priority": 2,
        },
        {
            "task_id": "formal_task_005",
            "origin_spawn_index": 78,
            "destination_spawn_index": 48,
            "release_time_s": 0.0,
            "priority": 2,
        },
        {
            "task_id": "formal_task_006",
            "origin_spawn_index": 78,
            "destination_spawn_index": 48,
            "release_time_s": 0.0,
            "priority": 2,
        },
    ],
    "route_matrix_path": "configs/decision_route_matrix_formal_calibrated.json",
    "operating_areas_path": "configs/operating_areas_formal_calibrated.json",
    "results_path": "runtime_data/results/s01_closed_loop_formal_summary.json",
}


def _signature(result):
    return [
        (
            task["task_id"],
            task["origin_spawn_index"],
            task["destination_spawn_index"],
            task["release_time_s"],
            task["priority"],
        )
        for task in result.tasks
    ]


def test_same_seed_reproduces_same_task_config():
    left = RandomTaskConfigGenerator(1001, deepcopy(BASE)).generate()
    right = RandomTaskConfigGenerator(1001, deepcopy(BASE)).generate()

    assert left.config == right.config


def test_physical_od_pairs_never_change():
    generated = RandomTaskConfigGenerator(1002, deepcopy(BASE)).generate()

    pairs = sorted(
        (
            int(task["origin_spawn_index"]),
            int(task["destination_spawn_index"]),
        )
        for task in generated.tasks
    )

    assert pairs == [(12, 48)] + [(78, 48)] * 5


def test_initial_origins_both_have_zero_release_task():
    generated = RandomTaskConfigGenerator(1003, deepcopy(BASE)).generate()

    assert any(
        task["origin_spawn_index"] == 12
        and task["release_time_s"] == 0.0
        for task in generated.tasks
    )
    assert any(
        task["origin_spawn_index"] == 78
        and task["release_time_s"] == 0.0
        for task in generated.tasks
    )


def test_multiple_seeds_produce_multiple_business_variants():
    signatures = set()

    for seed in range(2000, 2010):
        generated = RandomTaskConfigGenerator(
            seed,
            deepcopy(BASE),
        ).generate()
        signatures.add(tuple(_signature(generated)))

    assert len(signatures) > 1
