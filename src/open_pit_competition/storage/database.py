# -*- coding: utf-8 -*-
"""Small SQLite persistence layer for Data Model V1.

Important architecture rule:
- CARLA / Runtime real-time control stays in memory.
- Decision consumes WorldState, not SQL queries.
- This database stores history, task/road snapshots, monitoring data and
  decision outputs for replay, dashboard and evaluation.
"""

import sqlite3
from pathlib import Path
from typing import Dict, List

from .models import (
    AssignmentRecord,
    EventRecord,
    FixedStationRecord,
    RoadStateRecord,
    StationReadingRecord,
    TaskRecord,
    VehicleTelemetryRecord,
)
from .schema import SCHEMA_SQL


class OpenPitDatabase:
    def __init__(self, path):
        self.path = Path(path)

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def initialize(self):
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)

    def table_names(self) -> List[str]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type='table'
                  AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()
        return [row["name"] for row in rows]

    def upsert_fixed_station(self, record: FixedStationRecord):
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO fixed_stations (
                    station_id, station_type, x, y, z,
                    road_id, lane_id, monitor_radius_m,
                    camera_enabled, active
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(station_id) DO UPDATE SET
                    station_type=excluded.station_type,
                    x=excluded.x,
                    y=excluded.y,
                    z=excluded.z,
                    road_id=excluded.road_id,
                    lane_id=excluded.lane_id,
                    monitor_radius_m=excluded.monitor_radius_m,
                    camera_enabled=excluded.camera_enabled,
                    active=excluded.active
                """,
                (
                    record.station_id,
                    record.station_type,
                    record.x,
                    record.y,
                    record.z,
                    record.road_id,
                    record.lane_id,
                    record.monitor_radius_m,
                    int(record.camera_enabled),
                    int(record.active),
                ),
            )

    def insert_station_reading(self, record: StationReadingRecord):
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO station_readings (
                    timestamp_s, station_id, vehicle_count,
                    avg_speed_kmh, congestion_level, road_risk, visibility
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.timestamp_s,
                    record.station_id,
                    record.vehicle_count,
                    record.avg_speed_kmh,
                    record.congestion_level,
                    record.road_risk,
                    record.visibility,
                ),
            )

    def insert_vehicle_telemetry(self, record: VehicleTelemetryRecord):
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO vehicle_telemetry (
                    timestamp_s, vehicle_id, x, y, z, speed_kmh,
                    road_id, lane_id, healthy, available,
                    business_state, current_task_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.timestamp_s,
                    record.vehicle_id,
                    record.x,
                    record.y,
                    record.z,
                    record.speed_kmh,
                    record.road_id,
                    record.lane_id,
                    int(record.healthy),
                    int(record.available),
                    record.business_state,
                    record.current_task_id,
                ),
            )

    def upsert_task(self, record: TaskRecord):
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO tasks (
                    task_id, origin_spawn_index, destination_spawn_index,
                    priority, release_time_s, status, assigned_vehicle_id,
                    created_at_s, started_at_s, completed_at_s
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    origin_spawn_index=excluded.origin_spawn_index,
                    destination_spawn_index=excluded.destination_spawn_index,
                    priority=excluded.priority,
                    release_time_s=excluded.release_time_s,
                    status=excluded.status,
                    assigned_vehicle_id=excluded.assigned_vehicle_id,
                    created_at_s=excluded.created_at_s,
                    started_at_s=excluded.started_at_s,
                    completed_at_s=excluded.completed_at_s
                """,
                (
                    record.task_id,
                    record.origin_spawn_index,
                    record.destination_spawn_index,
                    record.priority,
                    record.release_time_s,
                    record.status,
                    record.assigned_vehicle_id,
                    record.created_at_s,
                    record.started_at_s,
                    record.completed_at_s,
                ),
            )

    def upsert_road_state(self, record: RoadStateRecord):
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO road_state (
                    road_id, lane_id, timestamp_s, open,
                    traffic_level, risk_level, visibility,
                    cost_multiplier, source_station_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(road_id, lane_id) DO UPDATE SET
                    timestamp_s=excluded.timestamp_s,
                    open=excluded.open,
                    traffic_level=excluded.traffic_level,
                    risk_level=excluded.risk_level,
                    visibility=excluded.visibility,
                    cost_multiplier=excluded.cost_multiplier,
                    source_station_id=excluded.source_station_id
                """,
                (
                    record.road_id,
                    record.lane_id,
                    record.timestamp_s,
                    int(record.open),
                    record.traffic_level,
                    record.risk_level,
                    record.visibility,
                    record.cost_multiplier,
                    record.source_station_id,
                ),
            )

    def insert_event(self, record: EventRecord):
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO events (
                    event_id, timestamp_s, event_type,
                    target_type, target_id, payload_json, handled
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.event_id,
                    record.timestamp_s,
                    record.event_type,
                    record.target_type,
                    record.target_id,
                    record.payload_json,
                    int(record.handled),
                ),
            )

    def insert_assignment(self, record: AssignmentRecord):
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO assignments (
                    timestamp_s, vehicle_id, task_id,
                    empty_route_id, haul_route_id, score, reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.timestamp_s,
                    record.vehicle_id,
                    record.task_id,
                    record.empty_route_id,
                    record.haul_route_id,
                    record.score,
                    record.reason,
                ),
            )

    def insert_station_readings_batch(self, records):
        """Insert station samples using one SQLite transaction."""
        records = list(records)
        if not records:
            return
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO station_readings (
                    timestamp_s, station_id, vehicle_count,
                    avg_speed_kmh, congestion_level, road_risk, visibility
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        record.timestamp_s,
                        record.station_id,
                        record.vehicle_count,
                        record.avg_speed_kmh,
                        record.congestion_level,
                        record.road_risk,
                        record.visibility,
                    )
                    for record in records
                ],
            )

    def insert_vehicle_telemetry_batch(self, records):
        """Insert one monitoring tick for multiple vehicles efficiently."""
        records = list(records)
        if not records:
            return
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO vehicle_telemetry (
                    timestamp_s, vehicle_id, x, y, z, speed_kmh,
                    road_id, lane_id, healthy, available,
                    business_state, current_task_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        record.timestamp_s,
                        record.vehicle_id,
                        record.x,
                        record.y,
                        record.z,
                        record.speed_kmh,
                        record.road_id,
                        record.lane_id,
                        int(record.healthy),
                        int(record.available),
                        record.business_state,
                        record.current_task_id,
                    )
                    for record in records
                ],
            )

    def upsert_road_states_batch(self, records):
        """Persist road-state observations using one SQLite transaction."""
        records = list(records)
        if not records:
            return
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO road_state (
                    road_id, lane_id, timestamp_s, open,
                    traffic_level, risk_level, visibility,
                    cost_multiplier, source_station_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(road_id, lane_id) DO UPDATE SET
                    timestamp_s=excluded.timestamp_s,
                    open=excluded.open,
                    traffic_level=excluded.traffic_level,
                    risk_level=excluded.risk_level,
                    visibility=excluded.visibility,
                    cost_multiplier=excluded.cost_multiplier,
                    source_station_id=excluded.source_station_id
                """,
                [
                    (
                        record.road_id,
                        record.lane_id,
                        record.timestamp_s,
                        int(record.open),
                        record.traffic_level,
                        record.risk_level,
                        record.visibility,
                        record.cost_multiplier,
                        record.source_station_id,
                    )
                    for record in records
                ],
            )

    def latest_road_states(self) -> List[Dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT road_id, lane_id, timestamp_s, open,
                       traffic_level, risk_level, visibility,
                       cost_multiplier, source_station_id
                FROM road_state
                ORDER BY road_id, lane_id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def pending_tasks(self) -> List[Dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM tasks
                WHERE status = 'PENDING'
                ORDER BY priority DESC, release_time_s ASC, task_id ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]
