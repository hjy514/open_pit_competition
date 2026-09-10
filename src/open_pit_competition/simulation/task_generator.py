from __future__ import annotations

import copy
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


@dataclass(frozen=True)
class GeneratedTaskConfig:
    seed: int
    config: Dict[str, Any]

    @property
    def tasks(self) -> List[Dict[str, Any]]:
        return list(self.config.get("task_templates", []))


class RandomTaskConfigGenerator:
    """Seed-based randomizer for the already-calibrated formal task pool.

    V1 of the task layer deliberately keeps every physical OD pair unchanged.
    It randomizes only business-level task attributes:
    - priority
    - release time
    - task list order

    This keeps the formal 12/78 -> 48 CAT routes intact.
    """

    def __init__(
        self,
        seed: int,
        base_config: Dict[str, Any],
        priority_choices: Sequence[int] = (1, 2, 2, 3),
        release_choices_s: Sequence[float] = (0.0, 8.0, 16.0, 24.0),
    ):
        self.seed = int(seed)
        self.base_config = copy.deepcopy(base_config)
        self.priority_choices = tuple(int(x) for x in priority_choices)
        self.release_choices_s = tuple(float(x) for x in release_choices_s)

        if not self.priority_choices:
            raise ValueError("priority_choices must not be empty")
        if not self.release_choices_s:
            raise ValueError("release_choices_s must not be empty")
        if min(self.priority_choices) < 1:
            raise ValueError("priority values must be >= 1")
        if min(self.release_choices_s) < 0.0:
            raise ValueError("release times must be >= 0")

    def generate(self) -> GeneratedTaskConfig:
        rng = random.Random(self.seed + 1000003)
        config = copy.deepcopy(self.base_config)

        templates = [
            copy.deepcopy(item)
            for item in config.get("task_templates", [])
        ]
        if not templates:
            raise ValueError("base config has no task_templates")

        # Keep OD pairs exactly as calibrated.  Only business attributes change.
        randomized: List[Dict[str, Any]] = []
        seen_origin_12 = False
        seen_origin_78_zero_release = False

        for index, task in enumerate(templates, start=1):
            origin = int(task["origin_spawn_index"])
            destination = int(task["destination_spawn_index"])

            if destination != 48:
                raise ValueError(
                    "V2 safety guard: destination must remain calibrated dump 48"
                )
            if origin not in (12, 78):
                raise ValueError(
                    "V2 safety guard: origin must remain calibrated 12 or 78"
                )

            priority = int(rng.choice(self.priority_choices))

            # The single 12-origin task stays available at t=0 so truck_1 can
            # start on its calibrated same-point route without an empty leg.
            if origin == 12 and not seen_origin_12:
                release_time_s = 0.0
                seen_origin_12 = True
            # Guarantee at least one 78-origin task is also available at t=0
            # for the initial truck_2.
            elif origin == 78 and not seen_origin_78_zero_release:
                release_time_s = 0.0
                seen_origin_78_zero_release = True
            else:
                release_time_s = float(rng.choice(self.release_choices_s))

            task["task_id"] = "rnd_{}_task_{:03d}".format(
                self.seed,
                index,
            )
            task["priority"] = priority
            task["release_time_s"] = release_time_s
            randomized.append(task)

        # Seed-dependent ordering influences deterministic tie resolution while
        # leaving every task's physical route unchanged.
        rng.shuffle(randomized)

        config["schema_version"] = "closed-loop-random-task-v1"
        config["task_count"] = len(randomized)
        config["task_seed"] = self.seed
        config["task_release_interval_s"] = 0.0
        config["task_templates"] = randomized
        config["results_path"] = (
            "runtime_data/results/random_seed_{}_summary.json".format(
                self.seed
            )
        )

        self._validate(config)

        return GeneratedTaskConfig(
            seed=self.seed,
            config=config,
        )

    @staticmethod
    def _validate(config: Dict[str, Any]) -> None:
        tasks = list(config.get("task_templates", []))
        if int(config.get("task_count", -1)) != len(tasks):
            raise ValueError("task_count does not match task_templates")

        ids = [str(task["task_id"]) for task in tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("generated task ids must be unique")

        if not any(
            int(task["origin_spawn_index"]) == 12
            and float(task["release_time_s"]) == 0.0
            for task in tasks
        ):
            raise ValueError("origin 12 needs one t=0 task")

        if not any(
            int(task["origin_spawn_index"]) == 78
            and float(task["release_time_s"]) == 0.0
            for task in tasks
        ):
            raise ValueError("origin 78 needs one t=0 task")

        for task in tasks:
            if int(task["origin_spawn_index"]) not in (12, 78):
                raise ValueError("unvalidated origin introduced")
            if int(task["destination_spawn_index"]) != 48:
                raise ValueError("unvalidated destination introduced")
            if int(task["priority"]) < 1:
                raise ValueError("priority must be >= 1")
            if float(task["release_time_s"]) < 0.0:
                raise ValueError("release time must be >= 0")


def load_json(path: str) -> Dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_generated_task_config(
    generated: GeneratedTaskConfig,
    output_path: str,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as handle:
        json.dump(
            generated.config,
            handle,
            ensure_ascii=False,
            indent=2,
        )
        handle.write("\n")

    return path
