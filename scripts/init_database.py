#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse

from open_pit_competition.storage import OpenPitDatabase


EXPECTED_TABLES = [
    "assignments",
    "events",
    "fixed_stations",
    "road_state",
    "station_readings",
    "tasks",
    "vehicle_telemetry",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db",
        default="runtime_data/database/open_pit.db",
        help="SQLite database path",
    )
    args = parser.parse_args()

    db = OpenPitDatabase(args.db)
    db.initialize()

    tables = db.table_names()

    print("========================================")
    print("DATA MODEL V1 DATABASE INITIALIZED")
    print("db     : {}".format(args.db))
    print("tables : {}".format(len(tables)))
    for name in tables:
        print("  - {}".format(name))

    missing = [name for name in EXPECTED_TABLES if name not in tables]
    if missing:
        print("missing: {}".format(", ".join(missing)))
        raise SystemExit(2)

    print("status : OK")
    print("========================================")


if __name__ == "__main__":
    main()
