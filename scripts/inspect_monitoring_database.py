#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Small read-only inspection utility for Monitoring V1B SQLite output."""

import argparse
import sqlite3
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db",
        default="runtime_data/database/open_pit.db",
    )
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit("database not found: {}".format(db_path))

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        station_count = conn.execute(
            "SELECT COUNT(*) AS n FROM station_readings"
        ).fetchone()["n"]
        telemetry_count = conn.execute(
            "SELECT COUNT(*) AS n FROM vehicle_telemetry"
        ).fetchone()["n"]

        print("=" * 78)
        print("MONITORING V1B DATABASE STATUS")
        print("db                : {}".format(db_path))
        print("station readings  : {}".format(station_count))
        print("vehicle telemetry : {}".format(telemetry_count))
        print("-" * 78)
        print("LATEST STATION READINGS")

        rows = conn.execute(
            """
            SELECT timestamp_s, station_id, vehicle_count,
                   avg_speed_kmh, congestion_level, road_risk, visibility
            FROM station_readings
            ORDER BY id DESC
            LIMIT ?
            """,
            (args.limit,),
        ).fetchall()

        for row in reversed(rows):
            print(
                "t={:6.1f}s | {:15s} | n={} | avg={:5.1f} km/h | "
                "cong={:.2f} | risk={:.2f} | vis={:.2f}".format(
                    row["timestamp_s"],
                    row["station_id"],
                    row["vehicle_count"],
                    row["avg_speed_kmh"],
                    row["congestion_level"],
                    row["road_risk"],
                    row["visibility"],
                )
            )

        print("-" * 78)
        print("LATEST VEHICLE TELEMETRY")
        rows = conn.execute(
            """
            SELECT timestamp_s, vehicle_id, speed_kmh, road_id, lane_id,
                   healthy, available, business_state, current_task_id
            FROM vehicle_telemetry
            ORDER BY id DESC
            LIMIT ?
            """,
            (args.limit,),
        ).fetchall()

        for row in reversed(rows):
            print(
                "t={:6.1f}s | {:8s} | {:5.1f} km/h | road={} lane={} | "
                "healthy={} available={} | state={} task={}".format(
                    row["timestamp_s"],
                    row["vehicle_id"],
                    row["speed_kmh"],
                    row["road_id"],
                    row["lane_id"],
                    bool(row["healthy"]),
                    bool(row["available"]),
                    row["business_state"],
                    row["current_task_id"],
                )
            )
        print("=" * 78)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
