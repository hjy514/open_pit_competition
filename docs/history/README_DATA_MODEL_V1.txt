DATA MODEL V1 - open_pit_competition
====================================

Purpose
-------
This patch establishes the data foundation for Monitoring V1 and Closed Loop V1.

Architecture rule
-----------------
Real-time CARLA control remains in memory.
Decision still consumes WorldState and does NOT query SQLite directly.
SQLite is used for persistent monitoring/history/task/road/event/assignment data,
later Dashboard queries, replay and evaluation.

Added files
-----------
configs/operating_areas.json
src/open_pit_competition/storage/models.py
src/open_pit_competition/storage/schema.py
src/open_pit_competition/storage/database.py
scripts/init_database.py
tests/test_storage_data_model.py
README_DATA_MODEL_V1.txt

Added or overwritten
--------------------
src/open_pit_competition/storage/__init__.py

Overwritten existing utilities
------------------------------
scripts/build_decision_route_matrix.py
scripts/build_haul_route_matrix.py

Those two utilities are only changed so that:
1) operating areas default to configs/operating_areas.json in THIS repository.
2) build_haul_route_matrix.py defaults to the known working packaged CARLA 0.9.10 root.

NOT touched
-----------
src/open_pit_competition/simulation/runtime.py
src/open_pit_competition/simulation/carla_adapter.py
src/open_pit_competition/simulation/vehicle_behavior.py
src/open_pit_competition/decision/models.py
src/open_pit_competition/decision/policy.py
src/open_pit_competition/decision/route_planner.py
src/open_pit_competition/decision/scheduler.py
src/open_pit_competition/decision/replanner.py
configs/decision_route_matrix.json
configs/haul_route_matrix.json

SQLite business tables
----------------------
fixed_stations
station_readings
vehicle_telemetry
tasks
road_state
events
assignments

Install
-------
cd ~/矿山调度/open_pit_competition
unzip -o ~/下载/data_model_v1_patch.zip -d .

Test
----
PYTHONPATH=src python -m pytest -q \
  tests/test_scheduler.py \
  tests/test_replanner.py \
  tests/test_storage_data_model.py

Expected:
12 passed

Initialize database
-------------------
PYTHONPATH=src python scripts/init_database.py \
  --db runtime_data/database/open_pit.db

Expected:
DATA MODEL V1 DATABASE INITIALIZED
tables : 7
status : OK

Important
---------
The operating-area profile preserves its original data-boundary notes:
loading/dump points are parameterized business anchors; they are not claimed
to be calibrated real mine loaders/dumps or verified multi-truck capacities.

Next phase
----------
Monitoring V1:
- analyze road_lane_sequence in decision_route_matrix.json
- rank route-covered road/lane segments
- select 2-3 monitoring-station candidates
- obtain exact CARLA transforms/camera headings
- collect fixed-station + mobile CAT telemetry
