from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .scenario import ScenarioConfig, ScenarioEventSpec


SUPPORTED_MODES = ("failure", "closure", "compound", "mixed")


@dataclass(frozen=True)
class GeneratedScenario:
    """One deterministic random scenario and its generation metadata."""

    seed: int
    mode: str
    config: ScenarioConfig

    def to_dict(self) -> Dict[str, object]:
        return {
            "scenario_id": self.config.scenario_id,
            "name": self.config.name,
            "description": self.config.description,
            "duration_s": self.config.duration_s,
            "initial_spawn_count": self.config.initial_spawn_count,
            "spawn_clearance_m": self.config.spawn_clearance_m,
            "destination_spawn_index": self.config.destination_spawn_index,
            "seed": self.seed,
            "generated_mode": self.mode,
            "events": [
                {
                    "type": event.event_type,
                    "at_seconds": event.at_seconds,
                    "params": dict(event.params),
                }
                for event in self.config.events
            ],
        }


class ScenarioGenerator:
    """Deterministic seed-based Scenario generator.

    V1 intentionally randomizes only already-supported Scenario/Event concepts.
    It does NOT randomize CARLA map, CAT blueprint, route endpoints or Decision
    logic.  The generated JSON remains compatible with load_scenario().
    """

    def __init__(
        self,
        seed: int,
        failure_vehicle_ids: Sequence[str] = ("truck_2", "truck_3"),
        duration_s: float = 130.0,
        initial_spawn_count: int = 2,
        spawn_clearance_m: float = 25.0,
        destination_spawn_index: int = 48,
    ):
        self.seed = int(seed)
        self._rng = random.Random(self.seed)

        vehicle_ids = tuple(str(x) for x in failure_vehicle_ids if str(x))
        if not vehicle_ids:
            raise ValueError("failure_vehicle_ids must not be empty")

        self.failure_vehicle_ids = vehicle_ids
        self.duration_s = max(60.0, float(duration_s))
        self.initial_spawn_count = int(initial_spawn_count)
        self.spawn_clearance_m = float(spawn_clearance_m)
        self.destination_spawn_index = int(destination_spawn_index)

        if self.initial_spawn_count < 1:
            raise ValueError("initial_spawn_count must be >= 1")
        if self.spawn_clearance_m <= 0.0:
            raise ValueError("spawn_clearance_m must be > 0")

    def generate(self, mode: str = "mixed") -> GeneratedScenario:
        requested = str(mode).strip().lower()
        if requested not in SUPPORTED_MODES:
            raise ValueError(
                "unsupported mode '{}'; choose from {}".format(
                    mode,
                    ", ".join(SUPPORTED_MODES),
                )
            )

        resolved = requested
        if resolved == "mixed":
            resolved = self._rng.choice(
                ("failure", "closure", "compound")
            )

        if resolved == "failure":
            events = self._failure_events()
        elif resolved == "closure":
            events = self._closure_events()
        else:
            events = self._compound_events()

        events = sorted(events, key=lambda event: event.at_seconds)

        config = ScenarioConfig(
            scenario_id="RND_{}_{}".format(
                self.seed,
                resolved.upper(),
            ),
            name="random_{}".format(resolved),
            description=(
                "Seed随机场景：seed={}，mode={}。"
                "仅随机已支持的故障/恢复/封路/重开事件；"
                "地图、CAT车型、正式标定路线和Decision逻辑保持不变。"
            ).format(self.seed, resolved),
            duration_s=self.duration_s,
            initial_spawn_count=self.initial_spawn_count,
            spawn_clearance_m=self.spawn_clearance_m,
            destination_spawn_index=self.destination_spawn_index,
            events=events,
        )

        self._validate(config)

        return GeneratedScenario(
            seed=self.seed,
            mode=resolved,
            config=config,
        )

    def _failure_events(self) -> List[ScenarioEventSpec]:
        vehicle_id = self._rng.choice(self.failure_vehicle_ids)

        # Keep V1 events late enough for the regular fleet release process.
        failure_at = round(self._rng.uniform(35.0, 50.0), 1)
        recovery_delay = round(self._rng.uniform(15.0, 25.0), 1)
        recovery_at = round(failure_at + recovery_delay, 1)

        return [
            ScenarioEventSpec(
                event_type="vehicle_failure",
                at_seconds=failure_at,
                params={"vehicle_id": vehicle_id},
            ),
            ScenarioEventSpec(
                event_type="vehicle_recovery",
                at_seconds=recovery_at,
                params={"vehicle_id": vehicle_id},
            ),
        ]

    def _closure_events(
        self,
        earliest_at: float = 55.0,
    ) -> List[ScenarioEventSpec]:
        closure_at = round(
            self._rng.uniform(float(earliest_at), float(earliest_at) + 15.0),
            1,
        )
        closure_duration = round(self._rng.uniform(15.0, 25.0), 1)
        reopen_at = round(closure_at + closure_duration, 1)

        return [
            ScenarioEventSpec(
                event_type="road_closure",
                at_seconds=closure_at,
                params={"scope": "current_haul_route"},
            ),
            ScenarioEventSpec(
                event_type="road_reopen",
                at_seconds=reopen_at,
                params={"scope": "current_haul_route"},
            ),
        ]

    def _compound_events(self) -> List[ScenarioEventSpec]:
        failure = self._failure_events()
        recovery_at = failure[-1].at_seconds

        # Separate the two disturbances in V1 so the result is easier to
        # observe and diagnose than an intentionally overlapping stress case.
        closure_earliest = min(
            max(recovery_at + self._rng.uniform(8.0, 15.0), 68.0),
            82.0,
        )
        closure = self._closure_events(earliest_at=closure_earliest)

        return failure + closure

    def _validate(self, config: ScenarioConfig) -> None:
        previous_at = -1.0

        for event in config.events:
            if event.at_seconds < 0.0:
                raise ValueError("event time must be >= 0")
            if event.at_seconds >= config.duration_s:
                raise ValueError(
                    "event '{}' at {:.1f}s must be before duration {:.1f}s".format(
                        event.event_type,
                        event.at_seconds,
                        config.duration_s,
                    )
                )
            if event.at_seconds < previous_at:
                raise ValueError("events must be time ordered")
            previous_at = event.at_seconds

        event_types = [event.event_type for event in config.events]

        if "vehicle_failure" in event_types:
            if "vehicle_recovery" not in event_types:
                raise ValueError("vehicle_failure requires vehicle_recovery")

        if "road_closure" in event_types:
            if "road_reopen" not in event_types:
                raise ValueError("road_closure requires road_reopen")


def write_generated_scenario(
    generated: GeneratedScenario,
    output_path: str,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as handle:
        json.dump(
            generated.to_dict(),
            handle,
            ensure_ascii=False,
            indent=2,
        )
        handle.write("\n")

    return path
