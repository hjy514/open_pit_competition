import json

from open_pit_competition.simulation.scenario import load_scenario
from open_pit_competition.simulation.scenario_generator import (
    ScenarioGenerator,
    write_generated_scenario,
)


def _event_signature(generated):
    return [
        (
            event.event_type,
            event.at_seconds,
            tuple(sorted(event.params.items())),
        )
        for event in generated.config.events
    ]


def test_same_seed_is_reproducible():
    left = ScenarioGenerator(seed=1001).generate("mixed")
    right = ScenarioGenerator(seed=1001).generate("mixed")

    assert left.mode == right.mode
    assert _event_signature(left) == _event_signature(right)


def test_modes_produce_valid_event_pairs():
    failure = ScenarioGenerator(seed=2001).generate("failure")
    closure = ScenarioGenerator(seed=2002).generate("closure")
    compound = ScenarioGenerator(seed=2003).generate("compound")

    assert [x.event_type for x in failure.config.events] == [
        "vehicle_failure",
        "vehicle_recovery",
    ]
    assert [x.event_type for x in closure.config.events] == [
        "road_closure",
        "road_reopen",
    ]
    assert set(x.event_type for x in compound.config.events) == {
        "vehicle_failure",
        "vehicle_recovery",
        "road_closure",
        "road_reopen",
    }


def test_generated_json_is_load_scenario_compatible(tmp_path):
    generated = ScenarioGenerator(seed=3001).generate("compound")
    output = tmp_path / "scenario.json"

    write_generated_scenario(
        generated,
        str(output),
    )

    loaded = load_scenario(str(output))

    assert loaded.scenario_id == generated.config.scenario_id
    assert loaded.destination_spawn_index == 48
    assert len(loaded.events) == 4

    raw = json.loads(output.read_text(encoding="utf-8"))
    assert raw["seed"] == 3001
    assert raw["generated_mode"] == "compound"


def test_multiple_seeds_create_more_than_one_variant():
    signatures = set()

    for seed in range(10, 20):
        generated = ScenarioGenerator(seed=seed).generate("mixed")
        signatures.add(
            (
                generated.mode,
                tuple(_event_signature(generated)),
            )
        )

    assert len(signatures) > 1
