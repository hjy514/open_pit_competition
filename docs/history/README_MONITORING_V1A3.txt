MONITORING V1A.3 - ROADSIDE VISIBILITY INSPECTION
==================================================

Purpose
-------
Before permanent cameras are created, inspect whether terrain, slopes, rock
walls, buildings or other roadside objects block the observation view.

This stage DOES NOT re-plan routes or move the final road anchors.

For each final station:
- LEFT temporary RGB camera
- RIGHT temporary RGB camera
- OVERHEAD temporary RGB camera

The three views let us choose the safest and clearest permanent camera
transform for Monitoring V1B.

Files added
-----------
scripts/inspect_monitoring_visibility.py
README_MONITORING_V1A3.txt

Files overwritten
-----------------
None.

Files NOT touched
-----------------
src/open_pit_competition/simulation/*
src/open_pit_competition/decision/*
src/open_pit_competition/storage/*
configs/monitoring_stations.json
configs/decision_route_matrix.json
runtime_data/database/open_pit.db

Physical-safety rule
--------------------
The inspection script spawns ONLY sensor.camera.rgb actors temporarily.
It does NOT create:
- poles
- cabinets
- static meshes
- vehicles
- collision props

Every temporary RGB camera is destroyed immediately after its image is saved.

Run
---
Keep CARLA 0325_5 running:

cd ~/矿山调度/open_pit_competition

PYTHONPATH=src python scripts/inspect_monitoring_visibility.py \
  --stations configs/monitoring_stations.json \
  --lateral-offset-m 8

Output
------
runtime_data/monitoring_preview/
  station_road_01_left.png
  station_road_01_right.png
  station_road_01_overhead.png
  station_road_02_left.png
  station_road_02_right.png
  station_road_02_overhead.png
  station_road_03_left.png
  station_road_03_right.png
  station_road_03_overhead.png
  visibility_candidates.json
  monitoring_visibility_preview.zip

Next
----
Upload:
runtime_data/monitoring_preview/monitoring_visibility_preview.zip

Then choose one permanent camera transform per station:
- left
- right
- overhead

Monitoring V1B will use those transforms and still will not create a
collision obstacle on the haul road.
