# -*- coding: utf-8 -*-
"""Closed Loop V1 result summary."""

from __future__ import annotations

import json
from pathlib import Path


class ClosedLoopEvaluator:
    def summarize(self, coordinator, current_time_s: float):
        tasks = list(coordinator.tasks.values())
        completed = [task for task in tasks if task.status == "completed"]
        pending = [task for task in tasks if task.status == "pending"]
        active = [
            task
            for task in tasks
            if task.status not in ("pending", "completed")
        ]

        cycle_times = []
        for task in completed:
            meta = coordinator.task_meta.get(task.task_id)
            if (
                meta is not None
                and meta.started_at_s is not None
                and meta.completed_at_s is not None
            ):
                cycle_times.append(meta.completed_at_s - meta.started_at_s)

        generated = len(tasks)
        completed_count = len(completed)

        return {
            "schema_version": "closed-loop-v1",
            "scenario_time_s": round(float(current_time_s), 3),
            "generated_tasks": generated,
            "completed_tasks": completed_count,
            "active_tasks": len(active),
            "pending_tasks": len(pending),
            "completion_rate": (
                round(completed_count / float(generated), 4)
                if generated
                else 0.0
            ),
            "assignments": coordinator.metrics.assignments,
            "reschedules": coordinator.metrics.reschedules,
            "vehicle_failures": coordinator.metrics.vehicle_failures,
            "average_completed_cycle_time_s": (
                round(sum(cycle_times) / float(len(cycle_times)), 3)
                if cycle_times
                else None
            ),
        }

    def write(self, coordinator, current_time_s: float, output_path: str):
        summary = self.summarize(coordinator, current_time_s)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return summary
