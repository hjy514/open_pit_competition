MONITORING V1B.1 - OBSERVATION SEMANTICS FIX
=============================================

Why this patch exists
---------------------
During S01, the station camera image visibly contained CAT trucks while the
station reading still reported n=0.

That is not a CARLA-control failure. V1B used an exact road_id/lane_id filter
for station vehicle_count. In an open-pit mine, one fixed camera can physically
see nearby traffic that belongs to another CARLA road/lane ID.

V1B.1 separates TWO meanings:

1. Station observation area
   - all controlled CAT trucks physically near the station anchor
   - 3D radius <= monitor_radius_m
   - vertical difference <= 20 m by default
   - used for station_readings / dashboard / camera-status observation

2. Monitored road/lane
   - exact road_id + lane_id subset of nearby vehicles
   - used for RoadState traffic_level / later Decision route cost

This prevents nearby mine roads from contaminating Decision while making
station readings match what a monitoring station can actually observe.

Files overwritten
-----------------
src/open_pit_competition/monitoring/models.py
src/open_pit_competition/monitoring/fixed_station.py
src/open_pit_competition/monitoring/manager.py
tests/test_monitoring_v1b.py
configs/monitoring_camera_layout.json

Files NOT touched
-----------------
src/open_pit_competition/simulation/runtime.py
src/open_pit_competition/simulation/carla_adapter.py
src/open_pit_competition/simulation/vehicle_behavior.py
src/open_pit_competition/decision/*
src/open_pit_competition/storage/*
runtime_data/database/open_pit.db
configs/monitoring_stations.json
configs/decision_route_matrix.json

Vehicle-safety guarantee
------------------------
No new physical CARLA actor is introduced. Cameras remain sensor.camera.rgb
only. No apply_control(), destination change, behavior change, or collision
object is added.

Camera refinement
-----------------
The two overhead stations keep their approved transforms but use a wider
100-degree FOV. station_road_02 remains 90 degrees.

Expected live status
--------------------
S03:obs2 road0 v4.8 c0.58

Meaning:
obs2  = 2 CAT trucks physically inside the station observation area
road0 = none of those two is on this station's exact monitored road/lane
v4.8  = average speed of observed nearby CAT trucks
c0.58 = observation-area congestion indicator

RoadState still uses road0 / exact-road congestion, not obs2.

Run tests
---------
PYTHONPATH=src python -m pytest -q \
  tests/test_scheduler.py \
  tests/test_replanner.py \
  tests/test_storage_data_model.py \
  tests/test_monitoring_route_analysis.py \
  tests/test_monitoring_final_siting.py \
  tests/test_monitoring_v1b.py

Expected after replacing the prior 5 V1B tests with 6 V1B.1 tests:
25 passed

Run S01 with a clean log
------------------------
PYTHONPATH=src python -m open_pit_competition.simulation.runtime \
  --scenario configs/scenarios/s01_normal.json \
  --monitoring \
  2>&1 | grep --line-buffered -v "WARNING: cannot parse georeference" \
  | tee "runtime_data/logs/monitoring_v1b1_s01_$(date +%Y%m%d_%H%M%S).log"
