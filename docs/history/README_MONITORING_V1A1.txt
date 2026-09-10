MONITORING V1A.1 PREVIEW VISIBILITY FIX

Purpose:
Fix the problem where route candidates resolve correctly but are not visible in
the CARLA window because the spectator camera is somewhere else and the old
debug markers were too small.

Overwritten:
- scripts/preview_monitoring_stations.py

Not touched:
- Simulation
- Decision
- Storage/database
- route matrices
- monitoring route analysis
- Runtime/CARLA vehicle behavior

New preview behavior:
- automatically moves the CARLA spectator to station_road_01, 02, 03
- holds each view for 6 seconds by default
- draws a 10 m orange vertical mast
- draws a large red/orange station point
- draws a long green road-direction arrow
- draws the station label above the road

Run:
PYTHONPATH=src python scripts/preview_monitoring_stations.py \
  --carla-root /home/xiaoa/carla/Dist/CARLA_Shipping_0.9.10-dirty/LinuxNoEditor \
  --candidates configs/monitoring_station_candidates.json \
  --focus-seconds 8
