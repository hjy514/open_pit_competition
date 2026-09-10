# -*- coding: utf-8 -*-
"""SQLite schema for Data Model V1."""

SCHEMA_VERSION = "1.0"

SCHEMA_SQL = r"""
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS fixed_stations (
    station_id TEXT PRIMARY KEY,
    station_type TEXT NOT NULL,
    x REAL NOT NULL,
    y REAL NOT NULL,
    z REAL NOT NULL,
    road_id INTEGER,
    lane_id INTEGER,
    monitor_radius_m REAL NOT NULL DEFAULT 80.0,
    camera_enabled INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS station_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_s REAL NOT NULL,
    station_id TEXT NOT NULL,
    vehicle_count INTEGER NOT NULL DEFAULT 0,
    avg_speed_kmh REAL NOT NULL DEFAULT 0.0,
    congestion_level REAL NOT NULL DEFAULT 0.0,
    road_risk REAL NOT NULL DEFAULT 0.0,
    visibility REAL NOT NULL DEFAULT 1.0,
    FOREIGN KEY(station_id) REFERENCES fixed_stations(station_id)
);

CREATE TABLE IF NOT EXISTS vehicle_telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_s REAL NOT NULL,
    vehicle_id TEXT NOT NULL,
    x REAL NOT NULL,
    y REAL NOT NULL,
    z REAL NOT NULL,
    speed_kmh REAL NOT NULL,
    road_id INTEGER,
    lane_id INTEGER,
    healthy INTEGER NOT NULL DEFAULT 1,
    available INTEGER NOT NULL DEFAULT 1,
    business_state TEXT NOT NULL DEFAULT 'IDLE',
    current_task_id TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    origin_spawn_index INTEGER NOT NULL,
    destination_spawn_index INTEGER NOT NULL,
    priority INTEGER NOT NULL DEFAULT 1,
    release_time_s REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'PENDING',
    assigned_vehicle_id TEXT,
    created_at_s REAL,
    started_at_s REAL,
    completed_at_s REAL
);

CREATE TABLE IF NOT EXISTS road_state (
    road_id INTEGER NOT NULL,
    lane_id INTEGER NOT NULL,
    timestamp_s REAL NOT NULL,
    open INTEGER NOT NULL DEFAULT 1,
    traffic_level REAL NOT NULL DEFAULT 0.0,
    risk_level REAL NOT NULL DEFAULT 0.0,
    visibility REAL NOT NULL DEFAULT 1.0,
    cost_multiplier REAL NOT NULL DEFAULT 1.0,
    source_station_id TEXT,
    PRIMARY KEY (road_id, lane_id)
);

CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    timestamp_s REAL NOT NULL,
    event_type TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    handled INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_s REAL NOT NULL,
    vehicle_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    empty_route_id TEXT,
    haul_route_id TEXT,
    score REAL NOT NULL DEFAULT 0.0,
    reason TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_station_readings_station_time
    ON station_readings(station_id, timestamp_s);
CREATE INDEX IF NOT EXISTS idx_vehicle_telemetry_vehicle_time
    ON vehicle_telemetry(vehicle_id, timestamp_s);
CREATE INDEX IF NOT EXISTS idx_tasks_status_release
    ON tasks(status, release_time_s);
CREATE INDEX IF NOT EXISTS idx_events_time
    ON events(timestamp_s);
CREATE INDEX IF NOT EXISTS idx_assignments_task_time
    ON assignments(task_id, timestamp_s);
"""
