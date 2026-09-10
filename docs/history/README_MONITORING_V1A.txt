MONITORING V1A - ROUTE-DRIVEN STATION SELECTION
================================================

Purpose
-------
This patch does NOT yet create full fixed stations/cameras.
It first solves the placement problem correctly:

Decision routes
  -> road/lane coverage analysis
  -> 2-3 important transport-road candidates
  -> CARLA visual preview
  -> only then build fixed monitoring stations/cameras.

Why
---
A monitoring station must observe roads that the dispatch routes actually use.
It should not be placed at arbitrary spawn points.

Added files
-----------
scripts/analyze_monitoring_routes.py
scripts/preview_monitoring_stations.py
tests/test_monitoring_route_analysis.py
README_MONITORING_V1A.txt

Generated after you run it
--------------------------
configs/monitoring_station_candidates.json
configs/monitoring_stations_preview.json

NOT touched
-----------
simulation/*
decision/*
storage/*
configs/decision_route_matrix.json
configs/haul_route_matrix.json
runtime_data/database/open_pit.db
frontend/*
dashboard/*

Step 1 - Offline route analysis (NO CARLA required)
---------------------------------------------------
cd ~/矿山调度/open_pit_competition

PYTHONPATH=src python scripts/analyze_monitoring_routes.py \
  --matrix configs/decision_route_matrix.json \
  --count 3

Expected:
MONITORING V1A ROUTE COVERAGE COMPLETE
...
selected stations : 3

Step 2 - Test
-------------
PYTHONPATH=src python -m pytest -q \
  tests/test_scheduler.py \
  tests/test_replanner.py \
  tests/test_storage_data_model.py \
  tests/test_monitoring_route_analysis.py

Expected:
15 passed

Step 3 - CARLA visual preview
-----------------------------
First start the packaged CARLA server on map 0325_5.

Then:
PYTHONPATH=src python scripts/preview_monitoring_stations.py \
  --carla-root /home/xiaoa/carla/Dist/CARLA_Shipping_0.9.10-dirty/LinuxNoEditor \
  --candidates configs/monitoring_station_candidates.json

The CARLA window should show:
- station_road_01 / 02 / 03 labels
- orange station points
- green arrows showing road forward direction

This preview stage deliberately does NOT:
- spawn RGB camera sensors
- write station telemetry
- modify Runtime
- alter Decision
- affect CAT vehicle behavior

Next after visual confirmation
------------------------------
Monitoring V1B:
- make the chosen station transforms permanent
- attach CARLA RGB cameras
- collect vehicle_count / avg_speed / congestion
- generate simulated risk / visibility
- write fixed_stations, station_readings and vehicle_telemetry to open_pit.db
