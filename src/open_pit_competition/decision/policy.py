from __future__ import annotations

from dataclasses import dataclass

from .models import RoutePlan, TransportTask, VehicleState


@dataclass
class DispatchPolicyConfig:
    priority_reward_s: float = 20.0


@dataclass
class DispatchEvaluation:
    score: float
    reason: str


class DispatchPolicy:
    """Simple baseline: empty travel + loaded travel - priority reward.

    Lower score is better.
    """

    def __init__(self, config: DispatchPolicyConfig = None) -> None:
        self.config = config or DispatchPolicyConfig()

    def evaluate(
        self,
        vehicle: VehicleState,
        task: TransportTask,
        empty_route: RoutePlan,
        haul_route: RoutePlan,
    ) -> DispatchEvaluation:
        empty_s = empty_route.estimated_time_s
        haul_s = haul_route.estimated_time_s
        reward_s = max(0, int(task.priority)) * self.config.priority_reward_s
        score = empty_s + haul_s - reward_s

        return DispatchEvaluation(
            score=score,
            reason=(
                "empty={:.1f}s haul={:.1f}s priority={} reward={:.1f}s"
            ).format(
                empty_s,
                haul_s,
                task.priority,
                reward_s,
            ),
        )
