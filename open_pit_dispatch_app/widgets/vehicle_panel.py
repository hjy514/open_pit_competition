# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Any, Dict, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from api_client import ApiClient
from ui.vehicle_labels import business_label


class VehiclePanel(QFrame):
    vehicle_selected = pyqtSignal(str)

    def __init__(self, client: Optional[ApiClient] = None, parent=None):
        super().__init__(parent)
        self.client = client or ApiClient()
        self.setObjectName("Panel")
        self._selected = None

        root = QVBoxLayout(self)
        title = QLabel("CAT 车辆实时状态")
        title.setObjectName("SectionTitle")
        root.addWidget(title)

        self.summary = QLabel("等待车辆数据")
        self.summary.setObjectName("Muted")
        root.addWidget(self.summary)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        body = QWidget()
        self.list_layout = QVBoxLayout(body)
        self.list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(body)
        root.addWidget(self.scroll, 1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(750)
        QTimer.singleShot(100, self.refresh)

    def refresh(self):
        try:
            snapshot = self.client.state()
            vehicles = snapshot.get("vehicles", [])
        except Exception:
            self.summary.setText("API 暂不可用")
            return

        healthy = sum(bool(v.get("healthy")) for v in vehicles)
        self.summary.setText("在线 {}/6 ｜ 健康 {}".format(len(vehicles), healthy))

        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        for vehicle in vehicles:
            self.list_layout.addWidget(self._card(vehicle))

    def _card(self, vehicle: Dict[str, Any]) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(9, 7, 9, 7)

        row = QHBoxLayout()
        name = QLabel(str(vehicle.get("vehicle_id")))
        name.setStyleSheet("font-weight:800;")
        row.addWidget(name, 1)

        speed = QLabel("{:.1f} km/h".format(float(vehicle.get("speed_kmh") or 0.0)))
        speed.setStyleSheet("color:#a8e063;font-weight:700;")
        row.addWidget(speed)
        layout.addLayout(row)

        status = QLabel(
            "{} ｜ {} ｜ {}".format(
                business_label(vehicle.get("business_state")),
                "正常" if vehicle.get("healthy") else "故障",
                vehicle.get("current_task_id") or "无任务",
            )
        )
        status.setObjectName("Muted")
        layout.addWidget(status)

        detail = QLabel(
            "Road/Lane {}/{} ｜ ({:.1f}, {:.1f})".format(
                vehicle.get("road_id"),
                vehicle.get("lane_id"),
                float(vehicle.get("x") or 0.0),
                float(vehicle.get("y") or 0.0),
            )
        )
        detail.setObjectName("Muted")
        layout.addWidget(detail)

        button = QPushButton("在地图中选中")
        vehicle_id = str(vehicle.get("vehicle_id"))
        button.clicked.connect(lambda _=False, v=vehicle_id: self.vehicle_selected.emit(v))
        layout.addWidget(button)
        return frame
