import sqlite3
from pathlib import Path

from open_pit_competition.dashboard.service import DashboardService


SCHEMA = """
CREATE TABLE fixed_stations (
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
CREATE TABLE station_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_s REAL NOT NULL,
    station_id TEXT NOT NULL,
    vehicle_count INTEGER NOT NULL DEFAULT 0,
    avg_speed_kmh REAL NOT NULL DEFAULT 0.0,
    congestion_level REAL NOT NULL DEFAULT 0.0,
    road_risk REAL NOT NULL DEFAULT 0.0,
    visibility REAL NOT NULL DEFAULT 1.0
);
CREATE TABLE vehicle_telemetry (
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
CREATE TABLE tasks (
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
CREATE TABLE road_state (
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
CREATE TABLE events (
    event_id TEXT PRIMARY KEY,
    timestamp_s REAL NOT NULL,
    event_type TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    handled INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_s REAL NOT NULL,
    vehicle_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    empty_route_id TEXT,
    haul_route_id TEXT,
    score REAL NOT NULL DEFAULT 0.0,
    reason TEXT NOT NULL DEFAULT ''
);
"""


def build_db(path: Path):
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT INTO fixed_stations VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("station_road_01", "road", 10.0, 20.0, 5.0, 18, 2, 80.0, 1, 1),
    )
    conn.execute(
        """
        INSERT INTO station_readings
        (timestamp_s,station_id,vehicle_count,avg_speed_kmh,congestion_level,road_risk,visibility)
        VALUES (?,?,?,?,?,?,?)
        """,
        (12.0, "station_road_01", 2, 9.5, 0.4, 0.1, 0.9),
    )
    conn.execute(
        """
        INSERT INTO vehicle_telemetry
        (timestamp_s,vehicle_id,x,y,z,speed_kmh,road_id,lane_id,healthy,available,business_state,current_task_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (12.0, "truck_1", 1.0, 2.0, 0.0, 10.2, 4, -1, 1, 1, "TO_DUMP", "task_1"),
    )
    conn.execute(
        """
        INSERT INTO tasks
        (task_id,origin_spawn_index,destination_spawn_index,priority,release_time_s,status,assigned_vehicle_id)
        VALUES (?,?,?,?,?,?,?)
        """,
        ("task_1", 12, 48, 3, 0.0, "ASSIGNED", "truck_1"),
    )
    conn.execute(
        "INSERT INTO road_state VALUES (?,?,?,?,?,?,?,?,?)",
        (4, -1, 12.0, 1, 0.2, 0.0, 1.0, 1.0, "station_road_01"),
    )
    conn.execute(
        "INSERT INTO events VALUES (?,?,?,?,?,?,?)",
        ("evt_1", 12.0, "vehicle_recovery", "vehicle", "truck_1", "{}", 0),
    )
    conn.execute(
        """
        INSERT INTO assignments
        (timestamp_s,vehicle_id,task_id,haul_route_id,score,reason)
        VALUES (?,?,?,?,?,?)
        """,
        (12.0, "truck_1", "task_1", "haul_to_dump_12_to_48", 39.6, "greedy"),
    )
    conn.commit()
    conn.close()


def test_snapshot_reads_live_tables(tmp_path):
    db = tmp_path / "open_pit.db"
    build_db(db)

    service = DashboardService(project_root=tmp_path, database_path=db)
    snapshot = service.snapshot({"running": True, "scenario_id": "TEST"})

    assert snapshot["run"]["scenario_id"] == "TEST"
    assert snapshot["metrics"]["online_cat"] == 1
    assert snapshot["vehicles"][0]["vehicle_id"] == "truck_1"
    assert snapshot["stations"][0]["camera_enabled"] is True
    assert snapshot["tasks"][0]["task_id"] == "task_1"
    assert snapshot["assignments"][0]["haul_route_id"] == "haul_to_dump_12_to_48"


def test_boundary_detects_timestamp_reset(tmp_path):
    db = tmp_path / "open_pit.db"
    build_db(db)

    conn = sqlite3.connect(str(db))
    for ts in (20.0, 25.0, 30.0, 1.0, 2.0, 3.0):
        conn.execute(
            """
            INSERT INTO vehicle_telemetry
            (timestamp_s,vehicle_id,x,y,z,speed_kmh,healthy,available,business_state)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (ts, "truck_2", ts, 0.0, 0.0, 5.0, 1, 1, "TO_DUMP"),
        )
    conn.commit()
    conn.row_factory = sqlite3.Row

    boundary = DashboardService._current_run_boundary(
        conn, "vehicle_telemetry", "id", "timestamp_s"
    )
    first_current = conn.execute(
        "SELECT timestamp_s FROM vehicle_telemetry WHERE id = ?",
        (boundary,),
    ).fetchone()[0]
    conn.close()

    assert first_current == 1.0
