from __future__ import annotations

import random
from typing import Any, Dict, List, Sequence, Tuple


class ScenarioGenerator:
    """Seeded random scenario generator.

    Randomness lives here, not inside Decision.
    The same seed + template produces the same scenario instance.

    Generated runtime events intentionally use the event names already
    understood by SimulationRuntime:
      - vehicle_failure / vehicle_recovery
      - road_closure / road_reopen

    Task arrivals are returned as generated task records. They will be
    consumed by the WorldState/Decision integration layer in the next step.
    """

    def __init__(self, seed: int) -> None:
        self.seed = int(seed)
        self.rng = random.Random(self.seed)

    def build_instance(
        self,
        template: Dict[str, Any],
        vehicle_ids: Sequence[str],
    ) -> Dict[str, Any]:
        duration_s = float(template["duration_s"])
        randomization = dict(template.get("randomization", {}))

        events: List[Dict[str, Any]] = []

        failure_cfg = randomization.get("vehicle_failure", {})
        if failure_cfg.get("enabled", False):
            events.extend(
                self._vehicle_failure_events(
                    vehicle_ids=vehicle_ids,
                    duration_s=duration_s,
                    config=failure_cfg,
                )
            )

        closure_cfg = randomization.get("road_closure", {})
        if closure_cfg.get("enabled", False):
            events.extend(
                self._route_closure_events(
                    duration_s=duration_s,
                    config=closure_cfg,
                )
            )

        tasks_cfg = randomization.get("task_arrival", {})
        generated_tasks = []
        if tasks_cfg.get("enabled", False):
            generated_tasks = self._task_arrivals(
                duration_s=duration_s,
                config=tasks_cfg,
            )

        events.sort(
            key=lambda item: (
                float(item["at_seconds"]),
                str(item["type"]),
            )
        )

        return {
            "scenario_id": str(template.get("scenario_id", "RANDOM")),
            "name": str(template.get("name", "random_scenario")),
            "description": str(template.get("description", "")),
            "duration_s": duration_s,
            "seed": self.seed,
            "events": events,
            "generated_tasks": generated_tasks,
        }

    def _vehicle_failure_events(
        self,
        vehicle_ids: Sequence[str],
        duration_s: float,
        config: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        probability = float(config.get("probability", 0.0))
        start_s, end_s = self._range(
            config.get("time_range_s", [0.0, duration_s])
        )
        recovery_min_s, recovery_max_s = self._range(
            config.get("recovery_time_s", [10.0, 30.0])
        )

        end_s = min(end_s, duration_s)
        events = []

        for vehicle_id in sorted(str(item) for item in vehicle_ids):
            if self.rng.random() > probability:
                continue

            failure_at = self.rng.uniform(start_s, end_s)
            recovery_after = self.rng.uniform(
                recovery_min_s,
                recovery_max_s,
            )
            recovery_at = min(duration_s, failure_at + recovery_after)

            events.append(
                {
                    "type": "vehicle_failure",
                    "at_seconds": round(failure_at, 3),
                    "params": {"vehicle_id": vehicle_id},
                }
            )

            if recovery_at > failure_at:
                events.append(
                    {
                        "type": "vehicle_recovery",
                        "at_seconds": round(recovery_at, 3),
                        "params": {"vehicle_id": vehicle_id},
                    }
                )

        return events

    def _route_closure_events(
        self,
        duration_s: float,
        config: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        probability = float(config.get("probability", 0.0))
        if self.rng.random() > probability:
            return []

        start_s, end_s = self._range(
            config.get("time_range_s", [0.0, duration_s])
        )
        closure_min_s, closure_max_s = self._range(
            config.get("duration_s", [10.0, 30.0])
        )

        end_s = min(end_s, duration_s)
        closure_at = self.rng.uniform(start_s, end_s)
        reopen_at = min(
            duration_s,
            closure_at + self.rng.uniform(
                closure_min_s,
                closure_max_s,
            ),
        )

        events = [
            {
                "type": "road_closure",
                "at_seconds": round(closure_at, 3),
                "params": {"scope": "current_haul_route"},
            }
        ]

        if reopen_at > closure_at:
            events.append(
                {
                    "type": "road_reopen",
                    "at_seconds": round(reopen_at, 3),
                    "params": {"scope": "current_haul_route"},
                }
            )

        return events

    def _task_arrivals(
        self,
        duration_s: float,
        config: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        interval_min_s, interval_max_s = self._range(
            config.get("interval_s", [20.0, 40.0])
        )
        priority_min, priority_max = self._int_range(
            config.get("priority", [1, 5])
        )

        pairs = config.get("origin_destination_pairs", [])
        if not pairs:
            return []

        tasks = []
        current_time_s = 0.0
        task_index = 1

        while True:
            current_time_s += self.rng.uniform(
                interval_min_s,
                interval_max_s,
            )
            if current_time_s > duration_s:
                break

            pair = self.rng.choice(list(pairs))
            origin_id = str(pair["origin_point_id"])
            destination_id = str(pair["destination_point_id"])

            tasks.append(
                {
                    "task_id": "task_{:04d}".format(task_index),
                    "origin_point_id": origin_id,
                    "destination_point_id": destination_id,
                    "release_time_s": round(current_time_s, 3),
                    "priority": self.rng.randint(
                        priority_min,
                        priority_max,
                    ),
                }
            )
            task_index += 1

        return tasks

    @staticmethod
    def _range(value: Sequence[float]) -> Tuple[float, float]:
        if len(value) != 2:
            raise ValueError("range must contain exactly two values")
        lower = float(value[0])
        upper = float(value[1])
        if upper < lower:
            raise ValueError("range upper bound must be >= lower bound")
        return lower, upper

    @staticmethod
    def _int_range(value: Sequence[int]) -> Tuple[int, int]:
        if len(value) != 2:
            raise ValueError("integer range must contain exactly two values")
        lower = int(value[0])
        upper = int(value[1])
        if upper < lower:
            raise ValueError("integer range upper bound must be >= lower bound")
        return lower, upper
