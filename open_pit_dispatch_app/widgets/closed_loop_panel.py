# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout

from api_client import ApiClient


class ClosedLoopPanel(QFrame):
    def __init__(self, client: Optional[ApiClient] = None, parent=None):
        super().__init__(parent)
        self.client = client or ApiClient()
        self.setObjectName("Panel")

        root = QVBoxLayout(self)
        title = QLabel("闭环运行与数据采集")
        title.setObjectName("SectionTitle")
        root.addWidget(title)

        self.grid = QGridLayout()
        root.addLayout(self.grid)

        self.labels = {}
        for index, key in enumerate(
            ("tasks", "reschedule", "road", "telemetry", "station", "system")
        ):
            label = QLabel("—")
            label.setStyleSheet(
                "background:#10231d;border:1px solid rgba(174,213,191,35);"
                "border-radius:7px;padding:8px;"
            )
            label.setWordWrap(True)
            self.labels[key] = label
            self.grid.addWidget(label, index // 3, index % 3)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        QTimer.singleShot(200, self.refresh)

    def refresh(self):
        try:
            snapshot = self.client.state()
        except Exception:
            return

        m = snapshot.get("metrics", {})
        system = snapshot.get("system", {})
        collection = m.get("data_collection", {})

        self.labels["tasks"].setText(
            "任务\n完成 {}/{} ｜ 运行 {} ｜ 待调度 {}".format(
                m.get("completed_tasks", 0),
                m.get("task_count", 0),
                m.get("active_tasks", 0),
                m.get("pending_tasks", 0),
            )
        )
        self.labels["reschedule"].setText(
            "决策\n重调度 {} ｜ Assignment {}".format(
                m.get("reschedules", 0),
                collection.get("assignments", 0),
            )
        )
        self.labels["road"].setText(
            "道路\n{}".format("OPEN" if m.get("road_open", True) else "CLOSED")
        )
        self.labels["telemetry"].setText(
            "车辆遥测\n{} 条".format(collection.get("vehicle_telemetry", 0))
        )
        self.labels["station"].setText(
            "固定站采集\n{} 条".format(collection.get("station_readings", 0))
        )
        self.labels["system"].setText(
            "系统\nCARLA {} ｜ Monitoring {} ｜ DB {}".format(
                system.get("carla", "—"),
                system.get("monitoring", "—"),
                system.get("database", "—"),
            )
        )
