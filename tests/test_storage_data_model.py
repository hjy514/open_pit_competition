# -*- coding: utf-8 -*-

import sqlite3

from open_pit_competition.storage import (
    AssignmentRecord,
    EventRecord,
    FixedStationRecord,
    OpenPitDatabase,
    RoadStateRecord,
    StationReadingRecord,
    TaskRecord,
    VehicleTelemetryRecord,
)


EXPECTED_TABLES = {
    "fixed_stations",
    "station_readings",
    "vehicle_telemetry",
    "tasks",
    "road_state",
    "events",
    "assignments",
}


def make_db(tmp_path):
    db = OpenPitDatabase(tmp_path / "open_pit_test.db")
    db.initialize()
    return db


def test_initialize_creates_seven_business_tables(tmp_path):
    db = make_db(tmp_path)
    assert set(db.table_names()) == EXPECTED_TABLES


def test_fixed_station_and_reading(tmp_path):
    db = make_db(tmp_path)
    db.upsert_fixed_station(
        FixedStationRecord(
            station_id="station_road_01",
            station_type="road",
            x=1.0,
            y=2.0,
            z=3.0,
            road_id=21,
            lane_id=-1,
            camera_enabled=True,
        )
    )
    db.insert_station_reading(
        StationReadingRecord(
            timestamp_s=10.0,
            station_id="station_road_01",
            vehicle_count=2,
            avg_speed_kmh=8.5,
            congestion_level=0.4,
            road_risk=0.2,
            visibility=0.9,
        )
    )

    with db.connect() as conn:
        station = conn.execute(
            "SELECT * FROM fixed_stations WHERE station_id=?",
            ("station_road_01",),
        ).fetchone()
        reading = conn.execute(
            "SELECT * FROM station_readings WHERE station_id=?",
            ("station_road_01",),
        ).fetchone()

    assert station["camera_enabled"] == 1
    assert reading["vehicle_count"] == 2


def test_vehicle_telemetry_insert(tmp_path):
    db = make_db(tmp_path)
    db.insert_vehicle_telemetry(
        VehicleTelemetryRecord(
            timestamp_s=12.5,
            vehicle_id="truck_3",
            x=10.0,
            y=20.0,
            z=1.0,
            speed_kmh=11.7,
            road_id=21,
            lane_id=-1,
            healthy=True,
            available=False,
            business_state="TO_DUMP",
            current_task_id="task_005",
        )
    )

    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM vehicle_telemetry WHERE vehicle_id='truck_3'"
        ).fetchone()

    assert row["speed_kmh"] == 11.7
    assert row["business_state"] == "TO_DUMP"
    assert row["current_task_id"] == "task_005"


def test_task_and_road_state_upsert(tmp_path):
    db = make_db(tmp_path)
    db.upsert_task(
        TaskRecord(
            task_id="task_001",
            origin_spawn_index=18,
            destination_spawn_index=34,
            priority=3,
            status="PENDING",
        )
    )
    db.upsert_task(
        TaskRecord(
            task_id="task_001",
            origin_spawn_index=18,
            destination_spawn_index=34,
            priority=3,
            status="ASSIGNED",
            assigned_vehicle_id="truck_4",
        )
    )

    db.upsert_road_state(
        RoadStateRecord(
            timestamp_s=20.0,
            road_id=21,
            lane_id=-1,
            open=True,
            traffic_level=0.2,
            risk_level=0.1,
            cost_multiplier=1.0,
        )
    )
    db.upsert_road_state(
        RoadStateRecord(
            timestamp_s=21.0,
            road_id=21,
            lane_id=-1,
            open=False,
            traffic_level=0.8,
            risk_level=0.9,
            cost_multiplier=99.0,
            source_station_id="station_road_01",
        )
    )

    with db.connect() as conn:
        task = conn.execute(
            "SELECT * FROM tasks WHERE task_id='task_001'"
        ).fetchone()
    roads = db.latest_road_states()

    assert task["status"] == "ASSIGNED"
    assert task["assigned_vehicle_id"] == "truck_4"
    assert len(roads) == 1
    assert roads[0]["open"] == 0
    assert roads[0]["source_station_id"] == "station_road_01"


def test_event_and_assignment_insert(tmp_path):
    db = make_db(tmp_path)
    db.insert_event(
        EventRecord(
            event_id="EV001",
            timestamp_s=40.0,
            event_type="VEHICLE_FAILURE",
            target_type="vehicle",
            target_id="truck_4",
            payload_json='{"task_id":"task_001"}',
        )
    )
    db.insert_assignment(
        AssignmentRecord(
            timestamp_s=40.2,
            vehicle_id="truck_5",
            task_id="task_001",
            empty_route_id="empty_to_loading_78_to_18",
            haul_route_id="haul_to_dump_18_to_34",
            score=1084.0,
            reason="replan_after_vehicle_failure",
        )
    )

    with db.connect() as conn:
        event = conn.execute("SELECT * FROM events WHERE event_id='EV001'").fetchone()
        assignment = conn.execute(
            "SELECT * FROM assignments WHERE task_id='task_001'"
        ).fetchone()

    assert event["event_type"] == "VEHICLE_FAILURE"
    assert assignment["vehicle_id"] == "truck_5"
    assert assignment["reason"] == "replan_after_vehicle_failure"
