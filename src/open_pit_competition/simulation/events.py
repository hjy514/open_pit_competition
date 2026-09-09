from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List

from .scenario import ScenarioEventSpec


@dataclass(frozen=True)
class RuntimeEvent:
    event_type: str
    at_seconds: float
    params: Dict[str, Any]


class EventQueue:
    """Small time-ordered event queue used by Simulation Runtime.

    S01 has no events. The same queue will later be reused by S02/S07.
    """

    def __init__(self, specs: Iterable[ScenarioEventSpec]):
        self._pending: List[RuntimeEvent] = sorted(
            (
                RuntimeEvent(
                    event_type=spec.event_type,
                    at_seconds=spec.at_seconds,
                    params=dict(spec.params),
                )
                for spec in specs
            ),
            key=lambda item: item.at_seconds,
        )

    def pop_due(self, elapsed_seconds: float) -> List[RuntimeEvent]:
        due = []

        while self._pending:
            if self._pending[0].at_seconds > elapsed_seconds:
                break
            due.append(self._pending.pop(0))

        return due

    def has_pending(self) -> bool:
        return bool(self._pending)
