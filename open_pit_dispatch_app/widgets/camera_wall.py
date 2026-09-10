# -*- coding: utf-8 -*-
"""Desktop multi-camera wall.

V1.1 intentionally does not fake RGB frames.  The tile layout is real and
already bound to vehicle/station status.  A Camera Bridge can later replace
the placeholder body with live QPixmap frames without touching Decision.
"""

from __future__ import annotations

from typing import Dict, Optional

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from api_client import ApiClient
from ui.vehicle_labels import business_label


class CameraTile(QFrame):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.setMinimumHeight(210)
        root = QVBoxLayout(self)

        self.title = QLabel(title)
        self.title.setStyleSheet("font-size:15px;font-weight:800;")
        root.addWidget(self.title)

        self.image = QLabel("RGB LIVE VIEW\nCamera Bridge 待接入")
        self.image.setAlignment(
            __import__("PyQt6.QtCore", fromlist=["Qt"]).Qt.AlignmentFlag.AlignCenter
        )
        self.image.setStyleSheet(
            "background:#06100d;color:#61796e;border:1px dashed #30453c;"
            "border-radius:7px;min-height:125px;"
        )
        root.addWidget(self.image, 1)

        self.status = QLabel("OFFLINE")
        self.status.setObjectName("Muted")
        root.addWidget(self.status)

    def update_status(self, text: str):
        self.status.setText(text)


class CameraWall(QWidget):
    def __init__(self, client: Optional[ApiClient] = None, parent=None):
        super().__init__(parent)
        self.client = client or ApiClient()

        root = QVBoxLayout(self)
        header = QLabel("全局与多车实时视角")
        header.setObjectName("SectionTitle")
        root.addWidget(header)

        note = QLabel(
            "六路 CAT + 三路固定站位已按旧版视频墙保留；V1.1 不伪造 RGB，"
            "下一步用独立 Camera Bridge 接真实 CARLA 帧。"
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        root.addWidget(note)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        self.grid = QGridLayout(body)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        self.tiles: Dict[str, CameraTile] = {}
        for idx in range(1, 7):
            key = "truck_{}".format(idx)
            tile = CameraTile("CAT-{:02d}".format(idx))
            self.tiles[key] = tile
            self.grid.addWidget(tile, (idx - 1) // 3, (idx - 1) % 3)

        for idx in range(1, 4):
            key = "station_road_{:02d}".format(idx)
            tile = CameraTile("固定站 {:02d}".format(idx))
            self.tiles[key] = tile
            self.grid.addWidget(tile, 2, idx - 1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(850)
        QTimer.singleShot(180, self.refresh)

    def refresh(self):
        try:
            snapshot = self.client.state()
        except Exception:
            return

        vehicles = {
            str(item.get("vehicle_id")): item
            for item in snapshot.get("vehicles", [])
        }
        stations = {
            str(item.get("station_id")): item
            for item in snapshot.get("stations", [])
        }

        for key, tile in self.tiles.items():
            if key.startswith("truck_"):
                vehicle = vehicles.get(key)
                if vehicle:
                    tile.update_status(
                        "{} ｜ {:.1f} km/h ｜ {}".format(
                            business_label(vehicle.get("business_state")),
                            float(vehicle.get("speed_kmh") or 0.0),
                            vehicle.get("current_task_id") or "无任务",
                        )
                    )
                else:
                    tile.update_status("OFFLINE")
            else:
                station = stations.get(key)
                if station:
                    tile.update_status(
                        "Road/Lane {}/{} ｜ 车辆 {} ｜ Camera {}".format(
                            station.get("road_id"),
                            station.get("lane_id"),
                            station.get("vehicle_count", 0),
                            "ON" if station.get("camera_enabled") else "OFF",
                        )
                    )
                else:
                    tile.update_status("OFFLINE")
