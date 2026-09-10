MONITORING V1B - FIXED STATIONS + CAT TELEMETRY
===============================================

Purpose
-------
Turn the approved V1A.3 monitoring layout into an observation-only CARLA
monitoring subsystem.

Core safety rule
----------------
Monitoring must never change CAT mine-truck motion.

This implementation:
- NEVER calls apply_control()
- NEVER changes a vehicle destination
- NEVER changes VehicleBehavior / BehaviorContext
- NEVER spawns poles, cabinets, static meshes or other collision props
- spawns ONLY sensor.camera.rgb actors for fixed cameras
- treats camera/database failure as non-fatal; vehicle runtime continues

Observed data
-------------
Fixed stations (1 Hz):
- vehicle_count
- avg_speed_kmh
- congestion_level
- road_risk
- visibility
- camera status / latest RGB frame

CAT mobile telemetry (2 Hz):
- x / y / z
- speed_kmh
- road_id / lane_id
- healthy / available
- business_state
- current_task_id

Source semantics
----------------
vehicle_count / avg_speed / CAT position / speed / road / lane / health:
    CARLA ground truth

road_risk / visibility:
    simulated baseline in V1B, explicitly labelled in monitoring models/logs
    and ready to be replaced by Scenario/Closed Loop data later.

Camera layout
-------------
Uses the already approved configs/monitoring_camera_layout.json:
- station_road_01: overhead
- station_road_02: right
- station_road_03: overhead

RGB frames are overwritten in place under:
runtime_data/monitoring/cameras/
    station_road_01_latest.png
    station_road_02_latest.png
    station_road_03_latest.png

Added files
-----------
src/open_pit_competition/monitoring/__init__.py
src/open_pit_competition/monitoring/models.py
src/open_pit_competition/monitoring/fixed_station.py
src/open_pit_competition/monitoring/mobile_collector.py
src/open_pit_competition/monitoring/manager.py
scripts/inspect_monitoring_database.py
tests/test_monitoring_v1b.py
README_MONITORING_V1B.txt

Overwritten files
-----------------
src/open_pit_competition/simulation/runtime.py
    Minimal optional hook only:
    - --monitoring enables MonitoringManager
    - collection occurs after normal vehicle control step
    - monitoring failure is fail-open
    - camera sensors are destroyed before vehicle cleanup

src/open_pit_competition/storage/database.py
    Existing API unchanged.
    Adds batch insert/upsert helpers so SQLite monitoring writes use fewer
    connections/transactions and interfere as little as possible with CARLA
    control timing.

Not touched
-----------
src/open_pit_competition/simulation/carla_adapter.py
src/open_pit_competition/simulation/vehicle_behavior.py
src/open_pit_competition/decision/*
configs/monitoring_stations.json
configs/monitoring_camera_layout.json
configs/decision_route_matrix.json
configs/haul_route_matrix.json
storage/models.py
storage/schema.py
frontend/*
dashboard/*

Install
-------
cd ~/矿山调度/open_pit_competition
unzip -o ~/下载/monitoring_v1b_patch.zip -d .

Tests
-----
PYTHONPATH=src python -m pytest -q \
  tests/test_scheduler.py \
  tests/test_replanner.py \
  tests/test_storage_data_model.py \
  tests/test_monitoring_route_analysis.py \
  tests/test_monitoring_final_siting.py \
  tests/test_monitoring_v1b.py

Expected total after the previous 19 tests:
24 passed

CARLA smoke run
---------------
Keep CARLA 0325_5 running, then run the SAME baseline scenario with the
additional --monitoring flag:

PYTHONPATH=src python -m open_pit_competition.simulation.runtime \
  --scenario configs/scenarios/s01_normal.json \
  --monitoring

Expected monitoring startup includes lines similar to:
[MONITORING] camera station_road_01 ...
[MONITORING] camera station_road_02 ...
[MONITORING] camera station_road_03 ...
[MONITORING] started | stations=3 | cameras=3/3 | telemetry=2.0Hz | station=1.0Hz

Every ~5 s Runtime prints a compact station state line, e.g.:
[MONITORING] S01:n1 v12.3 c0.18 | S02:n0 v0.0 c0.00 | S03:n0 v0.0 c0.00

Inspect stored data
-------------------
PYTHONPATH=src python scripts/inspect_monitoring_database.py \
  --db runtime_data/database/open_pit.db

Camera files
------------
ls -lh runtime_data/monitoring/cameras/

Data-only fallback
------------------
If you ever need to prove that data collection works independently of RGB
rendering, run:

PYTHONPATH=src python -m open_pit_competition.simulation.runtime \
  --scenario configs/scenarios/s01_normal.json \
  --monitoring \
  --monitoring-no-cameras

This still collects station and CAT telemetry and still cannot affect vehicle
control.
