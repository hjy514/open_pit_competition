# -*- coding: utf-8 -*-
"""Dynamic desktop map visual refinement V1.5.

No backend/business changes.  CARLA-world geometry remains authoritative.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional, Tuple

from PyQt6.QtCore import QPointF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PyQt6.QtWidgets import (
    QGraphicsPolygonItem,
    QGraphicsScene,
    QGraphicsView,
    QMenu,
    QPushButton,
)

from api_client import ApiClient
from ui.vehicle_labels import business_label, health_label


SCENE_W = 1180.0
SCENE_H = 720.0
MARGIN = 42.0


class VehicleItem(QGraphicsPolygonItem):
    def __init__(
        self,
        vehicle: Dict[str, Any],
        x: float,
        y: float,
        yaw_deg: float,
        color: QColor,
    ):
        super().__init__(
            QPolygonF(
                [
                    QPointF(18.0, 0.0),
                    QPointF(-13.0, -10.0),
                    QPointF(-8.0, 0.0),
                    QPointF(-13.0, 10.0),
                ]
            )
        )
        self.vehicle_id = str(vehicle.get("vehicle_id") or "unknown")
        self.setPos(float(x), float(y))
        self.setRotation(float(yaw_deg))
        self.setBrush(QBrush(color))
        self.setPen(QPen(QColor("#f7fbf9"), 1.15))
        self.setZValue(70)
        self.setData(0, self.vehicle_id)
        self.setToolTip(
            "车辆：{id}\n状态：{state}\n健康：{health}\n速度：{speed:.1f} km/h\n"
            "任务：{task}\nRoad/Lane：{road}/{lane}\n位置：({x:.1f}, {y:.1f}, {z:.1f})".format(
                id=self.vehicle_id,
                state=business_label(vehicle.get("business_state")),
                health=health_label(vehicle.get("healthy")),
                speed=float(vehicle.get("speed_kmh") or 0.0),
                task=vehicle.get("current_task_id") or "—",
                road=vehicle.get("road_id"),
                lane=vehicle.get("lane_id"),
                x=float(vehicle.get("x") or 0.0),
                y=float(vehicle.get("y") or 0.0),
                z=float(vehicle.get("z") or 0.0),
            )
        )


class MapWidget(QGraphicsView):
    vehicle_clicked = pyqtSignal(str)

    ROUTE_COLORS = [
        "#bf5af2",
        "#64d2ff",
        "#ff9f0a",
        "#30d158",
        "#ff375f",
        "#5ac7a1",
    ]

    def __init__(self, client: Optional[ApiClient] = None, parent=None):
        super().__init__(parent)
        self.client = client or ApiClient()
        self.scene_obj = QGraphicsScene(self)
        self.setScene(self.scene_obj)
        self.setSceneRect(0.0, 0.0, SCENE_W, SCENE_H)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setBackgroundBrush(QColor("#0d171d"))
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.snapshot: Dict[str, Any] = {}
        self.map_data: Dict[str, Any] = {}
        self._manual_zoom = False
        self.selected_vehicle_id: Optional[str] = None

        self.layers = {
            "roads": True,
            "routes": True,
            "trails": True,
            "areas": True,
            "stations": True,
            "vehicle_labels": False,
        }

        self._zoom_in = QPushButton("＋", self.viewport())
        self._zoom_out = QPushButton("－", self.viewport())
        self._reset = QPushButton("全图", self.viewport())
        self._layers_button = QPushButton("图层", self.viewport())

        for button in (
            self._zoom_in,
            self._zoom_out,
            self._reset,
            self._layers_button,
        ):
            button.setFixedHeight(28)
            button.setStyleSheet(
                "QPushButton{background:rgba(7,17,15,225);color:#edf5ef;"
                "border:1px solid #40554c;border-radius:5px;padding:2px 8px;"
                "font-weight:700;}"
                "QPushButton:hover{border-color:#5ac7a1;background:#10231e;}"
            )

        self._zoom_in.setFixedWidth(34)
        self._zoom_out.setFixedWidth(34)
        self._reset.setFixedWidth(48)
        self._layers_button.setFixedWidth(48)

        self._zoom_in.clicked.connect(lambda: self._zoom(1.18))
        self._zoom_out.clicked.connect(lambda: self._zoom(1 / 1.18))
        self._reset.clicked.connect(self.reset_view)

        self._layer_menu = QMenu(self)
        self._layer_menu.setStyleSheet(
            "QMenu{background:#0d1a17;color:#edf5ef;border:1px solid #40554c;}"
            "QMenu::item{padding:7px 24px 7px 10px;}"
            "QMenu::item:selected{background:#183328;}"
        )
        layer_names = [
            ("roads", "完整路网"),
            ("routes", "规划路线"),
            ("trails", "车辆轨迹"),
            ("areas", "任务区域"),
            ("stations", "固定站点"),
            ("vehicle_labels", "车辆文字标签"),
        ]
        for key, title in layer_names:
            action = QAction(title, self)
            action.setCheckable(True)
            action.setChecked(self.layers[key])
            action.toggled.connect(
                lambda checked, layer_key=key: self._toggle_layer(
                    layer_key,
                    checked,
                )
            )
            self._layer_menu.addAction(action)
        self._layers_button.clicked.connect(self._show_layer_menu)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_data)
        self.timer.start(500)
        QTimer.singleShot(30, self.refresh_data)

    def _show_layer_menu(self):
        pos = self._layers_button.mapToGlobal(
            self._layers_button.rect().bottomLeft()
        )
        self._layer_menu.popup(pos)

    def _toggle_layer(self, key: str, checked: bool):
        self.layers[key] = bool(checked)
        self.draw_map()

    def refresh_data(self):
        try:
            self.snapshot = self.client.state()
        except Exception:
            return

        if (
            not self.map_data
            or self.map_data.get("schema_version")
            != "carla-runtime-map-v14"
            or self.map_data.get("source") != "carla_world"
        ):
            try:
                candidate = self.client.map_data()
                if isinstance(candidate, dict):
                    self.map_data = candidate
            except Exception:
                pass

        self.draw_map()

    def _projection(self):
        bounds = self.map_data.get("bounds")
        if not bounds:
            return None

        min_x = float(bounds["min_x"])
        max_x = float(bounds["max_x"])
        min_y = float(bounds["min_y"])
        max_y = float(bounds["max_y"])
        span_x = max(max_x - min_x, 1.0)
        span_y = max(max_y - min_y, 1.0)

        scale = min(
            (SCENE_W - MARGIN * 2) / span_x,
            (SCENE_H - MARGIN * 2) / span_y,
        )
        draw_w = span_x * scale
        draw_h = span_y * scale
        ox = (SCENE_W - draw_w) / 2.0
        oy = (SCENE_H - draw_h) / 2.0

        def project(x: float, y: float) -> Tuple[float, float]:
            return (
                ox + (float(x) - min_x) * scale,
                oy + (float(y) - min_y) * scale,
            )

        return project

    @staticmethod
    def _vehicle_color(vehicle: Dict[str, Any]) -> QColor:
        if not bool(vehicle.get("healthy", True)):
            return QColor("#ff3b30")
        state = str(vehicle.get("business_state") or "IDLE").upper()
        speed = float(vehicle.get("speed_kmh") or 0.0)
        if state in {"LOADING", "UNLOADING"}:
            return QColor("#0a84ff")
        if state == "IDLE":
            return QColor("#8e8e93")
        if speed < 0.5:
            return QColor("#ff9500")
        return QColor("#32d74b")

    def _estimated_yaw(self, vehicle_id: str) -> float:
        values = self.snapshot.get("vehicle_trails", {}).get(vehicle_id, [])
        if len(values) < 2:
            return 0.0
        a = values[-2]
        b = values[-1]
        dx = float(b.get("x", 0.0)) - float(a.get("x", 0.0))
        dy = float(b.get("y", 0.0)) - float(a.get("y", 0.0))
        if abs(dx) + abs(dy) < 0.05:
            return 0.0
        return math.degrees(math.atan2(dy, dx))

    def _add_text(
        self,
        text,
        x,
        y,
        color="#e6eee9",
        size=8,
        z=100,
    ):
        item = self.scene_obj.addText(str(text))
        item.setDefaultTextColor(QColor(color))
        font = item.font()
        font.setPointSize(int(size))
        item.setFont(font)
        item.setPos(float(x), float(y))
        item.setZValue(float(z))
        return item

    def _draw_grid(self):
        pen = QPen(QColor("#18262e"), 0.8)
        for index in range(12):
            x = index * (SCENE_W / 11.0)
            self.scene_obj.addLine(x, 0.0, x, SCENE_H, pen).setZValue(0)
        for index in range(9):
            y = index * (SCENE_H / 8.0)
            self.scene_obj.addLine(0.0, y, SCENE_W, y, pen).setZValue(0)

    def _draw_roads(self, project):
        if not self.layers["roads"]:
            return

        closed_pairs = {
            (int(item.get("road_id")), int(item.get("lane_id")))
            for item in self.snapshot.get("road_state", [])
            if not bool(item.get("open", True))
        }

        normal_pen = QPen(QColor(105, 124, 136, 190), 1.3)
        junction_pen = QPen(QColor(148, 164, 174, 215), 1.65)
        closed_pen = QPen(QColor("#ff453a"), 3.0)

        for road in self.map_data.get("roads", []):
            points = road.get("points", [])
            if len(points) < 2:
                continue

            path = QPainterPath()
            sx, sy = project(points[0]["x"], points[0]["y"])
            path.moveTo(sx, sy)
            for point in points[1:]:
                sx, sy = project(point["x"], point["y"])
                path.lineTo(sx, sy)

            pair = (
                int(road.get("road_id", 0)),
                int(road.get("lane_id", 0)),
            )
            if pair in closed_pairs:
                pen = closed_pen
            elif road.get("is_junction"):
                pen = junction_pen
            else:
                pen = normal_pen

            item = self.scene_obj.addPath(path, pen)
            item.setZValue(4)
            item.setToolTip(
                "Road {} / Lane {}".format(
                    road.get("road_id"),
                    road.get("lane_id"),
                )
            )

    def _draw_task_areas(self, project):
        if not self.layers["areas"]:
            return

        for area in self.map_data.get("task_areas", []):
            sx, sy = project(area["x"], area["y"])
            loading = area.get("kind") == "loading"
            edge = QColor("#ffd60a" if loading else "#bf5af2")
            fill = (
                QColor(255, 214, 10, 70)
                if loading
                else QColor(191, 90, 242, 82)
            )
            radius = 10.0
            item = self.scene_obj.addEllipse(
                sx - radius,
                sy - radius,
                radius * 2,
                radius * 2,
                QPen(edge, 2.1),
                QBrush(fill),
            )
            item.setZValue(22)
            item.setToolTip(
                "{}\nSpawn {}".format(
                    "装载区" if loading else "卸载区",
                    area.get("spawn_index"),
                )
            )

            tag = str(area.get("name") or "")
            if tag:
                self._add_text(
                    tag,
                    sx + 8,
                    sy - 17,
                    "#f2f6f4",
                    7,
                    90,
                )

    def _draw_route_arrows(self, project, points, color: QColor, z: float):
        if len(points) < 8:
            return

        projected = [project(p["x"], p["y"]) for p in points]
        target_spacing = 95.0
        traveled = 0.0
        next_marker = target_spacing

        for index in range(1, len(projected)):
            x0, y0 = projected[index - 1]
            x1, y1 = projected[index]
            segment = math.hypot(x1 - x0, y1 - y0)
            if segment < 0.01:
                continue

            traveled += segment
            if traveled < next_marker:
                continue

            angle = math.atan2(y1 - y0, x1 - x0)
            tip = QPointF(x1, y1)
            back = 9.0
            wing = 4.5
            left = QPointF(
                x1 - back * math.cos(angle) + wing * math.sin(angle),
                y1 - back * math.sin(angle) - wing * math.cos(angle),
            )
            right = QPointF(
                x1 - back * math.cos(angle) - wing * math.sin(angle),
                y1 - back * math.sin(angle) + wing * math.cos(angle),
            )

            arrow = self.scene_obj.addPolygon(
                QPolygonF([tip, left, right]),
                QPen(color, 0.8),
                QBrush(color),
            )
            arrow.setZValue(z)
            next_marker += target_spacing

    def _draw_routes(self, project):
        if not self.layers["routes"]:
            return

        active_pairs = set()
        for task in self.snapshot.get("tasks", []):
            status = str(task.get("status") or "PENDING").upper()
            if (
                status not in {"COMPLETED", "CANCELLED"}
                and task.get("assigned_vehicle_id")
            ):
                try:
                    active_pairs.add(
                        (
                            int(task.get("origin_spawn_index")),
                            int(task.get("destination_spawn_index")),
                        )
                    )
                except (TypeError, ValueError):
                    pass

        for index, route in enumerate(self.map_data.get("routes", [])):
            points = route.get("points", [])
            if len(points) < 2:
                continue

            path = QPainterPath()
            sx, sy = project(points[0]["x"], points[0]["y"])
            path.moveTo(sx, sy)
            for point in points[1:]:
                sx, sy = project(point["x"], point["y"])
                path.lineTo(sx, sy)

            pair = (
                int(route.get("from_spawn_index")),
                int(route.get("to_spawn_index")),
            )
            active = pair in active_pairs
            color = QColor(
                self.ROUTE_COLORS[index % len(self.ROUTE_COLORS)]
            )
            color.setAlpha(250 if active else 180)

            # Dark halo keeps the highlighted route readable on dense road lines.
            halo = QPen(QColor(5, 12, 11, 180), 6.2 if active else 4.8)
            halo.setCapStyle(Qt.PenCapStyle.RoundCap)
            halo.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            self.scene_obj.addPath(path, halo).setZValue(28)

            pen = QPen(color, 3.6 if active else 2.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            if not active:
                pen.setStyle(Qt.PenStyle.DashLine)

            item = self.scene_obj.addPath(path, pen)
            item.setZValue(34 if active else 30)
            item.setToolTip(route.get("name") or route.get("route_id"))

            if active:
                self._draw_route_arrows(
                    project,
                    points,
                    QColor(color),
                    36,
                )

    def _draw_trajectories(self, project):
        if not self.layers["trails"]:
            return

        for index, (vehicle_id, values) in enumerate(
            sorted(self.snapshot.get("vehicle_trails", {}).items())
        ):
            if len(values) < 2:
                continue

            path = QPainterPath()
            sx, sy = project(values[0]["x"], values[0]["y"])
            path.moveTo(sx, sy)
            for point in values[1:]:
                sx, sy = project(point["x"], point["y"])
                path.lineTo(sx, sy)

            color = QColor(
                self.ROUTE_COLORS[index % len(self.ROUTE_COLORS)]
            )
            color.setAlpha(70)
            pen = QPen(color, 1.0)
            pen.setStyle(Qt.PenStyle.DashLine)
            self.scene_obj.addPath(path, pen).setZValue(38)

    def _draw_stations(self, project):
        if not self.layers["stations"]:
            return

        for index, station in enumerate(
            self.snapshot.get("stations", []),
            start=1,
        ):
            sx, sy = project(station["x"], station["y"])
            dot = self.scene_obj.addEllipse(
                sx - 4.3,
                sy - 4.3,
                8.6,
                8.6,
                QPen(QColor("#dffff5"), 0.8),
                QBrush(QColor("#00d5ff")),
            )
            dot.setZValue(50)
            dot.setToolTip(
                "{}\nRoad/Lane {}/{}\nCamera {}".format(
                    station.get("station_id"),
                    station.get("road_id"),
                    station.get("lane_id"),
                    "ON"
                    if station.get("camera_enabled")
                    else "OFF",
                )
            )
            self._add_text(
                "S{}".format(index),
                sx + 6,
                sy + 1,
                "#76e1c0",
                7,
                90,
            )

    def _draw_vehicles(self, project):
        for vehicle in self.snapshot.get("vehicles", []):
            sx, sy = project(vehicle["x"], vehicle["y"])
            vehicle_id = str(vehicle.get("vehicle_id"))
            selected = vehicle_id == self.selected_vehicle_id

            item = VehicleItem(
                vehicle,
                sx,
                sy,
                self._estimated_yaw(vehicle_id),
                self._vehicle_color(vehicle),
            )

            if selected:
                # Selection halo.
                halo = self.scene_obj.addEllipse(
                    sx - 17,
                    sy - 17,
                    34,
                    34,
                    QPen(QColor(255, 255, 255, 170), 1.4),
                    QBrush(Qt.BrushStyle.NoBrush),
                )
                halo.setZValue(66)
                item.setScale(1.28)
                item.setPen(QPen(QColor("#ffffff"), 2.0))

            self.scene_obj.addItem(item)

            # Default view stays clean.  Full labels only when explicitly enabled;
            # selected CAT always gets one compact status label.
            if self.layers["vehicle_labels"] or selected:
                if selected:
                    text = "{} | {} | {:.1f} km/h".format(
                        vehicle_id,
                        business_label(vehicle.get("business_state")),
                        float(vehicle.get("speed_kmh") or 0.0),
                    )
                else:
                    text = vehicle_id
                self._add_text(
                    text,
                    sx + 14,
                    sy - 21,
                    "#ffffff",
                    7,
                    95,
                )

    def _draw_header(self):
        run = self.snapshot.get("run", {})
        source = str(
            self.map_data.get("source") or "WAITING"
        ).upper()
        line_count = int(
            self.map_data.get("road_line_count", 0) or 0
        )
        cat_count = len(self.snapshot.get("vehicles", []))

        self._add_text(
            "0325_5  |  {}  |  路网 {}  |  CAT {}".format(
                source,
                line_count,
                cat_count,
            ),
            17,
            7,
            "#f4f8f6",
            9,
            120,
        )
        self._add_text(
            "{}  |  Seed {}  |  {:.1f}s".format(
                run.get("scenario_id") or "WAITING",
                run.get("seed")
                if run.get("seed") is not None
                else "—",
                float(run.get("elapsed_s") or 0.0),
            ),
            17,
            29,
            "#91a69c",
            7,
            120,
        )

    def draw_map(self):
        project = self._projection()
        if project is None:
            self.scene_obj.clear()
            self._add_text(
                "等待 CARLA 0325_5 地图数据",
                30,
                30,
                "#ff9f0a",
                10,
                120,
            )
            return

        self.scene_obj.clear()
        self.scene_obj.setSceneRect(
            0.0,
            0.0,
            SCENE_W,
            SCENE_H,
        )
        self._draw_grid()
        self._draw_roads(project)
        self._draw_task_areas(project)
        self._draw_routes(project)
        self._draw_trajectories(project)
        self._draw_stations(project)
        self._draw_vehicles(project)
        self._draw_header()

        if not self._manual_zoom:
            self.fitInView(
                self.sceneRect(),
                Qt.AspectRatioMode.KeepAspectRatio,
            )

    def _zoom(self, factor: float):
        self._manual_zoom = True
        self.scale(float(factor), float(factor))

    def reset_view(self):
        self._manual_zoom = False
        self.resetTransform()
        self.fitInView(
            self.sceneRect(),
            Qt.AspectRatioMode.KeepAspectRatio,
        )

    def wheelEvent(self, event):
        self._zoom(
            1.15
            if event.angleDelta().y() > 0
            else 1 / 1.15
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self.setDragMode(
                QGraphicsView.DragMode.ScrollHandDrag
            )

        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.position().toPoint())
            vehicle_id = item.data(0) if item is not None else None
            if vehicle_id:
                self.selected_vehicle_id = str(vehicle_id)
                self.vehicle_clicked.emit(
                    self.selected_vehicle_id
                )
                self.draw_map()

        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.MiddleButton:
            self.setDragMode(
                QGraphicsView.DragMode.NoDrag
            )

    def mouseDoubleClickEvent(self, event):
        self.reset_view()
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_R:
            self.reset_view()
            event.accept()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)

        right = self.viewport().width() - 8
        x = right

        self._layers_button.move(
            x - self._layers_button.width(),
            8,
        )
        x -= self._layers_button.width() + 5

        self._reset.move(
            x - self._reset.width(),
            8,
        )
        x -= self._reset.width() + 5

        self._zoom_out.move(
            x - self._zoom_out.width(),
            8,
        )
        x -= self._zoom_out.width() + 5

        self._zoom_in.move(
            x - self._zoom_in.width(),
            8,
        )

        if not self._manual_zoom:
            self.fitInView(
                self.sceneRect(),
                Qt.AspectRatioMode.KeepAspectRatio,
            )
