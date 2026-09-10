# -*- coding: utf-8 -*-
"""Small counters for the Closed Loop V1 MVP."""

from dataclasses import dataclass


@dataclass
class ClosedLoopMetrics:
    generated_tasks: int = 0
    completed_tasks: int = 0
    assignments: int = 0
    reschedules: int = 0
    vehicle_failures: int = 0
