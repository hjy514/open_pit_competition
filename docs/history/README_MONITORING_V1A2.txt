MONITORING V1A.2 - FINAL STATION SITING
=======================================

Purpose
-------
Finalise 3 fixed monitoring-station locations using BOTH:
1) Decision-route coverage
2) CARLA physical spacing

The previous V1A candidate logic only used road IDs, so different road IDs could
still be physically close. V1A.2 fixes that before cameras/database integration.

Added files
-----------
scripts/finalize_monitoring_stations.py
scripts/preview_final_monitoring_stations.py
tests/test_monitoring_final_siting.py
README_MONITORING_V1A2.txt

Generated when you run it
-------------------------
configs/monitoring_stations.json

NOT touched
-----------
src/open_pit_competition/simulation/*
src/open_pit_competition/decision/*
src/open_pit_competition/storage/*
configs/decision_route_matrix.json
configs/haul_route_matrix.json
runtime_data/database/open_pit.db
frontend/*
dashboard/*

Selection rule
--------------
Station 1:
- strongest haul-route coverage

Station 2/3:
- at least 150 m from every already selected station
- maximise NEW haul-route coverage
- then maximise NEW total-route coverage
- then use original haul/total coverage as tie breakers

Run
---
1) Keep CARLA 0325_5 running.

2) Finalise stations:

PYTHONPATH=src python scripts/finalize_monitoring_stations.py \
  --matrix configs/decision_route_matrix.json \
  --count 3 \
  --min-distance-m 150

This creates:
configs/monitoring_stations.json

3) Test:

PYTHONPATH=src python -m pytest -q \
  tests/test_scheduler.py \
  tests/test_replanner.py \
  tests/test_storage_data_model.py \
  tests/test_monitoring_route_analysis.py \
  tests/test_monitoring_final_siting.py

Expected:
19 passed

4) Preview the FINAL 3 stations:

PYTHONPATH=src python scripts/preview_final_monitoring_stations.py \
  --stations configs/monitoring_stations.json \
  --focus-seconds 8

After final visual confirmation, Monitoring V1A is frozen.

Next:
Monitoring V1B
- permanent station entities/markers
- CARLA RGB cameras
- fixed-station vehicle count / average speed / congestion
- simulated road risk / visibility
- CAT mobile telemetry
- persist data into open_pit.db
