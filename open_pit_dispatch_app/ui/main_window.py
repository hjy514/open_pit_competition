# -*- coding: utf-8 -*-
"""Main desktop control center, intentionally based on the old PyQt layout."""

from __future__ import annotations

import random
from typing import Any, Dict, Optional

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from api_client import ApiClient
from ui.theme import APP_QSS
from widgets.camera_wall import CameraWall
from widgets.closed_loop_panel import ClosedLoopPanel
from widgets.event_panel import EventPanel
from widgets.map_widget import MapWidget
from widgets.vehicle_panel import VehiclePanel
from windows.data_window import DataWindow
from windows.dispatch_window import DispatchWindow


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.client = ApiClient()
        self.dispatch_window: Optional[DispatchWindow] = None
        self.data_window: Optional[DataWindow] = None
        self.scenario_catalog = []
        self._last_alert_key = None

        self.setWindowTitle("露天矿无人运输智能调度平台")
        self.resize(1720, 1020)
        self.setMinimumSize(1280, 760)
        self.setStyleSheet(APP_QSS)

        self._init_ui()
        self._init_shortcuts()
        self.load_scenarios()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_status)
        self.timer.start(850)
        QTimer.singleShot(120, self.refresh_status)

    @staticmethod
    def panel() -> QFrame:
        frame = QFrame()
        frame.setObjectName("Panel")
        return frame

    def _init_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        self.setCentralWidget(central)

        # Header.
        header = QHBoxLayout()
        brand = QVBoxLayout()
        eyebrow = QLabel("OPEN-PIT AUTONOMOUS HAULAGE")
        eyebrow.setObjectName("Eyebrow")
        brand.addWidget(eyebrow)
        title = QLabel("露天矿无人运输智能调度平台")
        title.setObjectName("Title")
        brand.addWidget(title)
        header.addLayout(brand, 1)

        self.connection = QLabel("API · 连接中")
        self.connection.setStyleSheet(
            "color:#ffb23e;font-weight:700;padding:5px 8px;"
        )
        header.addWidget(self.connection)

        dispatch = QPushButton("决策调度中心")
        dispatch.setObjectName("Nav")
        dispatch.clicked.connect(self.show_dispatch)
        header.addWidget(dispatch)

        data = QPushButton("运行 / 数据中心")
        data.setObjectName("Nav")
        data.clicked.connect(self.show_data)
        header.addWidget(data)

        root.addLayout(header)

        # Scenario control.
        control = self.panel()
        c = QHBoxLayout(control)
        c.addWidget(QLabel("场景"))
        self.scenario_combo = QComboBox()
        self.scenario_combo.setMinimumWidth(230)
        self.scenario_combo.currentIndexChanged.connect(self._scenario_changed)
        c.addWidget(self.scenario_combo)

        c.addWidget(QLabel("Seed"))
        self.seed = QSpinBox()
        self.seed.setRange(1, 2147483647)
        self.seed.setValue(1002)
        self.seed.setMinimumWidth(115)
        c.addWidget(self.seed)

        self.random_seed = QPushButton("随机 Seed")
        self.random_seed.clicked.connect(self._randomize_seed)
        c.addWidget(self.random_seed)

        c.addWidget(QLabel("模式"))
        self.mode = QComboBox()
        self.mode.addItems(["mixed", "compound", "failure", "closure"])
        c.addWidget(self.mode)

        self.generate_button = QPushButton("生成随机场景")
        self.generate_button.clicked.connect(self.generate_random)
        c.addWidget(self.generate_button)

        self.start_button = QPushButton("▶ 一键运行")
        self.start_button.setObjectName("Primary")
        self.start_button.clicked.connect(self.start_scenario)
        c.addWidget(self.start_button)

        self.stop_button = QPushButton("■ 安全停止")
        self.stop_button.setObjectName("Danger")
        self.stop_button.clicked.connect(self.stop_scenario)
        self.stop_button.setEnabled(False)
        c.addWidget(self.stop_button)

        self.run_status = QLabel("等待运行")
        self.run_status.setObjectName("Muted")
        self.run_status.setMinimumWidth(310)
        c.addWidget(self.run_status, 1)
        root.addWidget(control)

        # Global alert strip.
        self.alert_strip = QLabel("当前无异常")
        self.alert_strip.setWordWrap(True)
        self.alert_strip.setObjectName("Muted")
        root.addWidget(self.alert_strip)

        # Main splitter: old layout = map/camera on left, vehicle+agent+event on right.
        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)

        self.operations_tabs = QTabWidget()
        self.map_widget = MapWidget(self.client)
        self.camera_wall = CameraWall(self.client)
        self.operations_tabs.addTab(self.map_widget, "动态态势地图")
        self.operations_tabs.addTab(self.camera_wall, "全局与多车视角")
        splitter.addWidget(self.operations_tabs)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.vehicle_panel = VehiclePanel(self.client)
        self.vehicle_panel.vehicle_selected.connect(self.select_vehicle)
        right_layout.addWidget(self.vehicle_panel, 5)

        decision_panel = self.panel()
        decision_layout = QVBoxLayout(decision_panel)
        dtitle = QLabel("Decision 调度中心")
        dtitle.setObjectName("SectionTitle")
        decision_layout.addWidget(dtitle)
        self.decision_summary = QLabel(
            "任务、Assignment、故障释放与恢复重调度将在这里联动。"
        )
        self.decision_summary.setObjectName("Muted")
        self.decision_summary.setWordWrap(True)
        decision_layout.addWidget(self.decision_summary)
        open_dispatch = QPushButton("展开决策调度中心")
        open_dispatch.clicked.connect(self.show_dispatch)
        decision_layout.addWidget(open_dispatch)
        right_layout.addWidget(decision_panel, 2)

        self.event_panel = EventPanel(self.client)
        self.event_panel.open_dispatch_requested.connect(self.show_dispatch)
        self.event_panel.alert_changed.connect(self.on_alert)
        right_layout.addWidget(self.event_panel, 2)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)
        root.addWidget(splitter, 1)

        self.closed_loop = ClosedLoopPanel(self.client)
        self.closed_loop.setMaximumHeight(185)
        root.addWidget(self.closed_loop)

    def _init_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+D"), self, activated=self.show_dispatch)
        QShortcut(QKeySequence("Ctrl+M"), self, activated=lambda: self.operations_tabs.setCurrentIndex(0))
        QShortcut(QKeySequence("Ctrl+V"), self, activated=lambda: self.operations_tabs.setCurrentIndex(1))
        QShortcut(QKeySequence("Ctrl+I"), self, activated=self.show_data)
        QShortcut(QKeySequence("F11"), self, activated=self.toggle_fullscreen)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def load_scenarios(self):
        try:
            data = self.client.scenarios()
            self.scenario_catalog = data.get("scenarios", [])
            self.scenario_combo.clear()
            for item in self.scenario_catalog:
                self.scenario_combo.addItem(
                    item.get("display_name") or item.get("scenario_id"),
                    item.get("scenario_id"),
                )
            self.connection.setText("API · READY")
            self.connection.setStyleSheet(
                "color:#a8e063;font-weight:700;padding:5px 8px;"
            )
            self._scenario_changed()
        except Exception:
            self.connection.setText("API · OFFLINE")
            self.connection.setStyleSheet(
                "color:#ff665f;font-weight:700;padding:5px 8px;"
            )

    def _scenario_changed(self):
        is_random = self.scenario_combo.currentData() == "RANDOM"
        self.seed.setEnabled(is_random)
        self.random_seed.setEnabled(is_random)
        self.mode.setEnabled(is_random)
        self.generate_button.setEnabled(is_random)

    def _randomize_seed(self):
        self.seed.setValue(random.randint(1000, 999999))

    def generate_random(self):
        try:
            result = self.client.generate_random(
                self.seed.value(),
                self.mode.currentText(),
            )
            QMessageBox.information(
                self,
                "随机场景已生成",
                "{}\nSeed: {}\nMode: {}\nEvents: {}\nTasks: {}".format(
                    result.get("scenario_id"),
                    result.get("seed"),
                    result.get("mode"),
                    len(result.get("events", [])),
                    len(result.get("tasks", [])),
                ),
            )
        except Exception as exc:
            QMessageBox.critical(self, "生成失败", str(exc))

    def start_scenario(self):
        scenario_id = self.scenario_combo.currentData()
        if not scenario_id:
            return
        if QMessageBox.question(
            self,
            "启动场景",
            "确认启动 {}？\nCARLA Server 需要已运行。".format(scenario_id),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        ) != QMessageBox.StandardButton.Yes:
            return

        try:
            seed = self.seed.value() if scenario_id == "RANDOM" else None
            result = self.client.start(
                scenario_id,
                seed=seed,
                mode=self.mode.currentText(),
            )
            self.run_status.setText(
                "{} ｜ PID {}".format(
                    result.get("scenario_id"),
                    result.get("pid"),
                )
            )
        except Exception as exc:
            QMessageBox.critical(self, "启动失败", str(exc))

    def stop_scenario(self):
        if QMessageBox.question(
            self,
            "安全停止",
            "确认向当前 Runtime 发送 SIGINT 安全停止请求？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.client.stop()
        except Exception as exc:
            QMessageBox.warning(self, "停止失败", str(exc))

    def refresh_status(self):
        try:
            control = self.client.control_status()
            snapshot = self.client.state()
        except Exception:
            self.connection.setText("API · OFFLINE")
            self.connection.setStyleSheet(
                "color:#ff665f;font-weight:700;padding:5px 8px;"
            )
            return

        self.connection.setText("API · CONNECTED")
        self.connection.setStyleSheet(
            "color:#a8e063;font-weight:700;padding:5px 8px;"
        )

        running = bool(control.get("running"))
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)

        self.run_status.setText(
            "{} ｜ {} ｜ {:.1f}s{}".format(
                control.get("scenario_id") or "无运行",
                str(control.get("state") or "idle").upper(),
                float(control.get("elapsed_s") or 0.0),
                (
                    " ｜ Seed {} / {}".format(
                        control.get("seed"),
                        control.get("mode"),
                    )
                    if control.get("seed") is not None
                    else ""
                ),
            )
        )

        m = snapshot.get("metrics", {})
        self.decision_summary.setText(
            "任务完成 {}/{} ｜ 运行 {} ｜ 待调度 {} ｜ 重调度 {} ｜ 道路 {}".format(
                m.get("completed_tasks", 0),
                m.get("task_count", 0),
                m.get("active_tasks", 0),
                m.get("pending_tasks", 0),
                m.get("reschedules", 0),
                "OPEN" if m.get("road_open", True) else "CLOSED",
            )
        )

        alerts = snapshot.get("alerts", [])
        if alerts:
            first = alerts[0]
            self.alert_strip.setText(
                "⚠ {} ｜ {} ｜ 点击右侧“进入决策调度中心”查看".format(
                    first.get("title") or "运行告警",
                    first.get("detail") or "",
                )
            )
            self.alert_strip.setStyleSheet(
                "background:#401513;color:#ffd4d1;border:1px solid #a53d38;"
                "border-radius:7px;padding:8px 12px;font-weight:700;"
            )
        else:
            self.alert_strip.setText("当前无异常 ｜ Closed Loop 正常监控")
            self.alert_strip.setStyleSheet("color:#8ca499;padding:4px;")

    def on_alert(self, alert: Dict[str, Any]):
        key = "{}|{}".format(alert.get("title"), alert.get("detail"))
        if key == self._last_alert_key:
            return
        self._last_alert_key = key
        # Keep the main window non-blocking: alert strip + taskbar beep.
        QApplication = __import__("PyQt6.QtWidgets", fromlist=["QApplication"]).QApplication
        QApplication.beep()

    def select_vehicle(self, vehicle_id: str):
        self.operations_tabs.setCurrentIndex(0)
        self.map_widget.selected_vehicle_id = str(vehicle_id)
        self.map_widget.draw_map()

    def show_dispatch(self):
        if self.dispatch_window is None:
            self.dispatch_window = DispatchWindow(self.client, self)
        self.dispatch_window.show()
        self.dispatch_window.raise_()
        self.dispatch_window.activateWindow()

    def show_data(self):
        if self.data_window is None:
            self.data_window = DataWindow(self.client, self)
        self.data_window.show()
        self.data_window.raise_()
        self.data_window.activateWindow()
