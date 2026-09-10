# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QDialog,
    QGridLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from api_client import ApiClient


class DataWindow(QDialog):
    def __init__(self, client: Optional[ApiClient] = None, parent=None):
        super().__init__(parent)
        self.client = client or ApiClient()
        self.setWindowTitle("运行状态与数据中心")
        self.resize(1180, 760)

        root = QVBoxLayout(self)
        title = QLabel("运行状态与数据中心")
        title.setObjectName("Title")
        root.addWidget(title)

        self.health = QGridLayout()
        root.addLayout(self.health)
        self.health_labels = {}
        for i, name in enumerate(
            ("CARLA", "Closed Loop", "Decision", "Monitoring", "Storage", "SQLite")
        ):
            label = QLabel("{}\n—".format(name))
            label.setStyleSheet(
                "background:#10231d;padding:10px;border-radius:7px;"
            )
            self.health_labels[name] = label
            self.health.addWidget(label, i // 3, i % 3)

        self.counts = QLabel("等待数据采集统计")
        self.counts.setStyleSheet("font-size:15px;font-weight:700;padding:8px;")
        root.addWidget(self.counts)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["固定站", "Road/Lane", "车辆数", "均速", "拥堵", "风险", "可见度", "Camera"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        QTimer.singleShot(120, self.refresh)

    def refresh(self):
        try:
            snapshot = self.client.state()
        except Exception:
            return

        system = snapshot.get("system", {})
        mapping = {
            "CARLA": system.get("carla"),
            "Closed Loop": system.get("closed_loop"),
            "Decision": system.get("decision"),
            "Monitoring": system.get("monitoring"),
            "Storage": system.get("storage"),
            "SQLite": system.get("database"),
        }
        for name, value in mapping.items():
            self.health_labels[name].setText("{}\n{}".format(name, value or "—"))

        c = snapshot.get("metrics", {}).get("data_collection", {})
        self.counts.setText(
            "Vehicle Telemetry {} ｜ Station Readings {} ｜ Events {} ｜ Assignments {}".format(
                c.get("vehicle_telemetry", 0),
                c.get("station_readings", 0),
                c.get("events", 0),
                c.get("assignments", 0),
            )
        )

        stations = snapshot.get("stations", [])
        self.table.setRowCount(len(stations))
        for row, item in enumerate(stations):
            values = [
                item.get("station_id"),
                "{}/{}".format(item.get("road_id"), item.get("lane_id")),
                item.get("vehicle_count", 0),
                "{:.1f}".format(float(item.get("avg_speed_kmh") or 0.0)),
                "{:.2f}".format(float(item.get("congestion_level") or 0.0)),
                "{:.2f}".format(float(item.get("road_risk") or 0.0)),
                "{:.2f}".format(float(item.get("visibility") or 0.0)),
                "ON" if item.get("camera_enabled") else "OFF",
            ]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(str(value)))
