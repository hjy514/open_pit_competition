# -*- coding: utf-8 -*-
"""Decision scheduling center based on the old HumanDispatchWindow role.

The new competition Decision remains frozen.  This window is therefore a
decision/assignment console, not a direct CARLA control panel.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from api_client import ApiClient


class DispatchWindow(QDialog):
    def __init__(self, client: Optional[ApiClient] = None, parent=None):
        super().__init__(parent)
        self.client = client or ApiClient()
        self.setWindowTitle("决策调度中心")
        self.resize(1320, 860)

        root = QVBoxLayout(self)

        top = QHBoxLayout()
        title = QLabel("决策调度中心")
        title.setObjectName("Title")
        top.addWidget(title, 1)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh)
        top.addWidget(refresh)
        root.addLayout(top)

        self.alert = QLabel("当前无异常")
        self.alert.setWordWrap(True)
        self.alert.setObjectName("Alert")
        root.addWidget(self.alert)

        task_title = QLabel("任务队列")
        task_title.setObjectName("SectionTitle")
        root.addWidget(task_title)

        self.tasks = QTableWidget(0, 6)
        self.tasks.setHorizontalHeaderLabels(
            ["任务", "运输区间", "Priority", "Release", "执行 CAT", "状态"]
        )
        self.tasks.setAlternatingRowColors(True)
        self.tasks.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tasks.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.tasks, 3)

        assign_title = QLabel("Decision Assignment 记录")
        assign_title.setObjectName("SectionTitle")
        root.addWidget(assign_title)

        self.assignments = QTableWidget(0, 6)
        self.assignments.setHorizontalHeaderLabels(
            ["时间", "CAT", "任务", "Empty Route", "Haul Route", "Score / Reason"]
        )
        self.assignments.setAlternatingRowColors(True)
        self.assignments.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.assignments.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.assignments, 2)

        note = QLabel(
            "当前调度窗口展示真实任务、Assignment、故障/封路处置结果。"
            "不允许界面绕过 Decision 直接操作 CARLA。"
        )
        note.setObjectName("Muted")
        root.addWidget(note)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(900)
        QTimer.singleShot(100, self.refresh)

    def refresh(self):
        try:
            snapshot = self.client.state()
        except Exception as exc:
            self.alert.setText("API 不可用：{}".format(exc))
            return

        alerts = snapshot.get("alerts", [])
        if alerts:
            first = alerts[0]
            self.alert.setText(
                "⚠ {}  ｜  {}".format(
                    first.get("title") or "运行告警",
                    first.get("detail") or "",
                )
            )
        else:
            self.alert.setText("当前无异常，Decision 正常运行")

        tasks = snapshot.get("tasks", [])
        self.tasks.setRowCount(len(tasks))
        for row, item in enumerate(tasks):
            values = [
                item.get("task_id"),
                "{} → {}".format(
                    item.get("origin_spawn_index"),
                    item.get("destination_spawn_index"),
                ),
                item.get("priority"),
                "{:.1f}s".format(float(item.get("release_time_s") or 0.0)),
                item.get("assigned_vehicle_id") or "—",
                item.get("status") or "PENDING",
            ]
            for col, value in enumerate(values):
                self.tasks.setItem(row, col, QTableWidgetItem(str(value)))

        assignments = list(snapshot.get("assignments", []))[-80:]
        self.assignments.setRowCount(len(assignments))
        for row, item in enumerate(assignments):
            values = [
                "{:.1f}s".format(float(item.get("timestamp_s") or 0.0)),
                item.get("vehicle_id"),
                item.get("task_id"),
                item.get("empty_route_id") or "—",
                item.get("haul_route_id") or "—",
                "{:.1f} ｜ {}".format(
                    float(item.get("score") or 0.0),
                    item.get("reason") or "",
                ),
            ]
            for col, value in enumerate(values):
                self.assignments.setItem(row, col, QTableWidgetItem(str(value)))
