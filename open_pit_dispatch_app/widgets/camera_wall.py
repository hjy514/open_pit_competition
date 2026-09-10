# -*- coding: utf-8 -*-
"""Real multi-camera wall for CATs and fixed monitoring stations."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from api_client import ApiClient
from ui.vehicle_labels import business_label


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TRUCK_CAMERA_DIR = PROJECT_ROOT / "runtime_data/monitoring/dashboard_cameras"
STATION_CAMERA_DIR = PROJECT_ROOT / "runtime_data/monitoring/cameras"
STALE_AFTER_S = 3.0


def truck_frame_path(vehicle_id: str) -> Path:
    return TRUCK_CAMERA_DIR / "{}_latest.png".format(vehicle_id)


def station_frame_path(station_id: str) -> Path:
    return STATION_CAMERA_DIR / "{}_latest.png".format(station_id)


def frame_is_fresh(path: Path, stale_after_s: float = STALE_AFTER_S) -> bool:
    try:
        return (
            path.exists()
            and (time.time() - path.stat().st_mtime) <= float(stale_after_s)
        )
    except OSError:
        return False


class CameraPreviewDialog(QDialog):
    def __init__(
        self,
        title: str,
        frame_path: Path,
        status_text: str,
        parent=None,
    ):
        super().__init__(parent)
        self.frame_path = Path(frame_path)
        self.setWindowTitle(title)
        self.resize(1120, 700)

        root = QVBoxLayout(self)
        header = QHBoxLayout()

        self.title_label = QLabel(title)
        self.title_label.setObjectName("Title")
        header.addWidget(self.title_label, 1)

        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.close)
        header.addWidget(close_button)
        root.addLayout(header)

        self.image = QLabel("等待实时画面")
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumSize(900, 500)
        self.image.setStyleSheet(
            "background:#030907;border:1px solid #30453c;border-radius:8px;"
        )
        root.addWidget(self.image, 1)

        self.status = QLabel(status_text)
        self.status.setObjectName("Muted")
        root.addWidget(self.status)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_frame)
        self.timer.start(200)
        self.refresh_frame()

    def refresh_frame(self):
        if not frame_is_fresh(self.frame_path):
            self.image.setText("OFFLINE / 等待实时帧")
            return

        pixmap = QPixmap(str(self.frame_path))
        if pixmap.isNull():
            self.image.setText("读取画面失败")
            return

        self.image.setPixmap(
            pixmap.scaled(
                self.image.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )


class CameraTile(QFrame):
    double_clicked = pyqtSignal(str)

    def __init__(self, key: str, title: str, frame_path: Path, parent=None):
        super().__init__(parent)
        self.key = str(key)
        self.frame_path = Path(frame_path)
        self.setObjectName("Panel")
        self.setMinimumHeight(235)
        self._last_mtime_ns = None
        self._last_status = "OFFLINE"

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(5)

        top = QHBoxLayout()
        self.title = QLabel(title)
        self.title.setStyleSheet("font-size:14px;font-weight:800;")
        top.addWidget(self.title, 1)

        self.live = QLabel("OFFLINE")
        self.live.setStyleSheet(
            "color:#8ca499;font-size:10px;font-weight:800;"
        )
        top.addWidget(self.live)
        root.addLayout(top)

        self.image = QLabel("等待实时画面")
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumHeight(155)
        self.image.setStyleSheet(
            "background:#030907;color:#61796e;"
            "border:1px solid #263b33;border-radius:7px;"
        )
        root.addWidget(self.image, 1)

        self.status = QLabel("OFFLINE")
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.hint = QLabel("双击放大")
        self.hint.setStyleSheet("color:#566f64;font-size:9px;")
        root.addWidget(self.hint)

    def set_status(self, text: str):
        self._last_status = str(text)
        self.status.setText(self._last_status)

    def current_status(self) -> str:
        return self._last_status

    def refresh_frame(self):
        path = self.frame_path
        if not frame_is_fresh(path):
            self.live.setText("OFFLINE")
            self.live.setStyleSheet(
                "color:#8ca499;font-size:10px;font-weight:800;"
            )
            self.image.clear()
            self.image.setText("等待实时画面")
            self._last_mtime_ns = None
            return False

        try:
            stat = path.stat()
            mtime_ns = getattr(
                stat,
                "st_mtime_ns",
                int(stat.st_mtime * 1_000_000_000),
            )
        except OSError:
            return False

        # Avoid decoding the same PNG on every UI tick.
        if mtime_ns != self._last_mtime_ns:
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                self.image.setPixmap(
                    pixmap.scaled(
                        self.image.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                self._last_mtime_ns = mtime_ns

        self.live.setText("LIVE")
        self.live.setStyleSheet(
            "color:#a8e063;font-size:10px;font-weight:800;"
        )
        return True

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit(self.key)
        event.accept()


class CameraWall(QWidget):
    def __init__(self, client: Optional[ApiClient] = None, parent=None):
        super().__init__(parent)
        self.client = client or ApiClient()
        self.previews: Dict[str, CameraPreviewDialog] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        header = QHBoxLayout()
        title = QLabel("全局与多车实时视角")
        title.setObjectName("SectionTitle")
        header.addWidget(title, 1)

        self.summary = QLabel("CAT Camera 0/6 ｜ Fixed Station 0/3")
        self.summary.setObjectName("Muted")
        header.addWidget(self.summary)
        root.addLayout(header)

        note = QLabel(
            "CAT画面由独立 Camera Bridge 读取 CARLA；固定站画面直接复用 Monitoring。"
            "展示摄像头不参与车辆控制。"
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        root.addWidget(note)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        self.grid = QGridLayout(body)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(8)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        self.tiles: Dict[str, CameraTile] = {}

        for idx in range(1, 7):
            key = "truck_{}".format(idx)
            tile = CameraTile(
                key,
                "CAT-{:02d}".format(idx),
                truck_frame_path(key),
            )
            tile.double_clicked.connect(self.open_preview)
            self.tiles[key] = tile
            self.grid.addWidget(
                tile,
                (idx - 1) // 3,
                (idx - 1) % 3,
            )

        for idx in range(1, 4):
            key = "station_road_{:02d}".format(idx)
            tile = CameraTile(
                key,
                "固定站 {:02d}".format(idx),
                station_frame_path(key),
            )
            tile.double_clicked.connect(self.open_preview)
            self.tiles[key] = tile
            self.grid.addWidget(tile, 2, idx - 1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(250)
        QTimer.singleShot(100, self.refresh)

    def open_preview(self, key: str):
        tile = self.tiles.get(key)
        if tile is None:
            return

        dialog = self.previews.get(key)
        if dialog is None:
            dialog = CameraPreviewDialog(
                tile.title.text(),
                tile.frame_path,
                tile.current_status(),
                self,
            )
            self.previews[key] = dialog
        else:
            dialog.status.setText(tile.current_status())

        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def refresh(self):
        try:
            snapshot = self.client.state()
        except Exception:
            snapshot = {"vehicles": [], "stations": []}

        vehicles = {
            str(item.get("vehicle_id")): item
            for item in snapshot.get("vehicles", [])
        }
        stations = {
            str(item.get("station_id")): item
            for item in snapshot.get("stations", [])
        }

        truck_live = 0
        station_live = 0

        for key, tile in self.tiles.items():
            if key.startswith("truck_"):
                vehicle = vehicles.get(key)
                if vehicle:
                    tile.set_status(
                        "{} ｜ {:.1f} km/h ｜ {}".format(
                            business_label(vehicle.get("business_state")),
                            float(vehicle.get("speed_kmh") or 0.0),
                            vehicle.get("current_task_id") or "无任务",
                        )
                    )
                else:
                    tile.set_status("CAT 尚未生成 / 已退出场景")

                if tile.refresh_frame():
                    truck_live += 1
            else:
                station = stations.get(key)
                if station:
                    tile.set_status(
                        "Road/Lane {}/{} ｜ 车辆 {} ｜ Camera {}".format(
                            station.get("road_id"),
                            station.get("lane_id"),
                            station.get("vehicle_count", 0),
                            "ON" if station.get("camera_enabled") else "OFF",
                        )
                    )
                else:
                    tile.set_status("等待 Monitoring 固定站数据")

                if tile.refresh_frame():
                    station_live += 1

        self.summary.setText(
            "CAT Camera {}/6 ｜ Fixed Station {}/3".format(
                truck_live,
                station_live,
            )
        )
