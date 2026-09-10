MONITORING V1A.3 CAMERA LAYOUT - APPROVED

Purpose
-------
Freeze one camera transform for each final monitoring road anchor after visual
review of left/right/overhead CARLA frames.

Approved placements
-------------------
station_road_01 -> overhead
station_road_02 -> right
station_road_03 -> overhead

Added
-----
configs/monitoring_camera_layout.json
README_MONITORING_V1A3_LAYOUT.txt

Overwritten
-----------
None.

Not touched
-----------
configs/monitoring_stations.json
simulation/*
decision/*
storage/*
runtime_data/database/open_pit.db
VehicleBehavior
Runtime

Safety rule
-----------
The layout uses sensor.camera.rgb only. No pole, cabinet, static mesh or other
collision object is required on the haul road.
