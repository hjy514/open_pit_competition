from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


@dataclass(frozen=True)
class ScenarioEventSpec:
    event_type: str
    at_seconds: float
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScenarioConfig:
    scenario_id: str
    name: str
    description: str
    duration_s: float
    initial_spawn_count: int
    spawn_clearance_m: float
    destination_spawn_index: int
    events: List[ScenarioEventSpec] = field(default_factory=list)


def load_scenario(path: str) -> ScenarioConfig:
    config_path = Path(path)

    with config_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    required = (
        "scenario_id",
        "name",
        "duration_s",
        "initial_spawn_count",
        "spawn_clearance_m",
        "destination_spawn_index",
    )

    missing = [key for key in required if key not in data]
    if missing:
        raise ValueError(
            "scenario config missing required keys: {}".format(
                ", ".join(missing)
            )
        )

    events = []
    for item in data.get("events", []):
        events.append(
            ScenarioEventSpec(
                event_type=str(item["type"]),
                at_seconds=float(item["at_seconds"]),
                params=dict(item.get("params", {})),
            )
        )

    return ScenarioConfig(
        scenario_id=str(data["scenario_id"]),
        name=str(data["name"]),
        description=str(data.get("description", "")),
        duration_s=float(data["duration_s"]),
        initial_spawn_count=int(data["initial_spawn_count"]),
        spawn_clearance_m=float(data["spawn_clearance_m"]),
        destination_spawn_index=int(data["destination_spawn_index"]),
        events=events,
    )
