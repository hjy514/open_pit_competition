# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from api_client import ApiClient


class EventPanel(QFrame):
    open_dispatch_requested = pyqtSignal()
    alert_changed = pyqtSignal(dict)

    def __init__(self, client: Optional[ApiClient] = None, parent=None):
        super().__init__(parent)
        self.client = client or ApiClient()
        self.setObjectName("Panel")
        self._last_alert_key = None

        root = QVBoxLayout(self)
        title = QLabel("异常事件")
        title.setObjectName("SectionTitle")
        root.addWidget(title)

        self.alert_label = QLabel("当前无异常")
        self.alert_label.setWordWrap(True)
        self.alert_label.setObjectName("Muted")
        root.addWidget(self.alert_label)

        button = QPushButton("进入决策调度中心")
        button.clicked.connect(self.open_dispatch_requested.emit)
        root.addWidget(button)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(850)
        QTimer.singleShot(150, self.refresh)

    def refresh(self):
        try:
            snapshot = self.client.state()
        except Exception:
            return
        alerts = snapshot.get("alerts", [])
        if not alerts:
            self.alert_label.setText("当前无异常")
            self.alert_label.setObjectName("Muted")
            self.alert_label.setStyleSheet("")
            return

        alert = alerts[0]
        title = str(alert.get("title") or "运行告警")
        detail = str(alert.get("detail") or "")
        self.alert_label.setText("{}\n{}".format(title, detail))
        self.alert_label.setObjectName("Alert")
        self.alert_label.setStyleSheet(
            "background:#401513;color:#ffd4d1;border:1px solid #a53d38;"
            "border-radius:7px;padding:8px 10px;font-weight:700;"
        )

        key = "{}|{}".format(title, detail)
        if key != self._last_alert_key:
            self._last_alert_key = key
            self.alert_changed.emit(dict(alert))
