CLOSED LOOP V1.1 ROUTE EXECUTION FIX
====================================

Root cause found from the real V1 run
-------------------------------------
The V1 run assigned tasks correctly.  But the current Decision matrix shows:

12 -> loading 53 : 3466.1 m, ETA 891.3 s
78 -> loading 53 : 3557.5 m, ETA 914.8 s
78 -> loading 52 : 4202.7 m, ETA 1080.7 s

S01 lasts only 90 s.  Therefore no LOADING before scenario end is expected for
those assignments.  The open-pit spiral/switchback road can also look like a
truck is circling while it is actually following a long route.

V1.1 therefore fixes both execution certainty and test design.

What changed
------------
1. Exact route handoff:
   Closed Loop passes route_id/from/to/expected distance to Runtime.
   CarlaAdapter rebuilds the same OD trace with CARLA GlobalRoutePlanner using
   the matrix sampling resolution, verifies route distance, trims passed prefix
   waypoints, and injects it into LocalPlanner.set_global_plan().

2. Route-start protection:
   if a CAT is too far from the selected route start, the command is rejected
   instead of forcing a large turn-back.  A small waypoint look-ahead avoids
   steering back toward an already-passed point.

3. Zero-length empty route:
   a CAT already parked at its chosen loading point enters LOADING directly.

4. Better logs:
   ASSIGN now prints empty/haul distance and ETA.  If empty ETA exceeds the
   remaining scenario time, Closed Loop prints a warning.

5. Dedicated short physical demo:
   S01/S02/S07 are untouched.  A new S10 demo stages four CATs at existing
   loading points and uses four known short haul routes so the full lifecycle
   can be seen within a few minutes.

Files added
-----------
configs/fleet_closed_loop_demo.json
configs/scenarios/s10_closed_loop_demo.json
configs/closed_loop_v11_demo.json
tests/test_closed_loop_v11_route_execution.py
README_CLOSED_LOOP_V11.txt

Files overwritten
-----------------
src/open_pit_competition/simulation/carla_adapter.py
src/open_pit_competition/simulation/runtime.py
src/open_pit_competition/decision/route_planner.py
src/open_pit_competition/closed_loop/coordinator.py

Not changed
-----------
src/open_pit_competition/simulation/vehicle_behavior.py
src/open_pit_competition/decision/models.py
src/open_pit_competition/decision/scheduler.py
src/open_pit_competition/decision/replanner.py
src/open_pit_competition/monitoring/*
src/open_pit_competition/storage/*
configs/decision_route_matrix.json
configs/operating_areas.json
configs/scenarios/s01_normal.json
configs/scenarios/s02_vehicle_failure.json
configs/scenarios/s07_road_closure.json

Install
-------
cd ~/矿山调度/open_pit_competition
unzip -o ~/下载/closed_loop_v11_route_execution_fix.zip -d .

Test
----
PYTHONPATH=src python -m pytest -q

First real CARLA V1.1 run
-------------------------
PYTHONPATH=src python -m open_pit_competition.simulation.runtime \
  --scenario configs/scenarios/s10_closed_loop_demo.json \
  --fleet configs/fleet_closed_loop_demo.json \
  --monitoring \
  --closed-loop \
  --closed-loop-config configs/closed_loop_v11_demo.json \
  2>&1 | grep --line-buffered -v "WARNING: cannot parse georeference" \
  | tee "runtime_data/logs/closed_loop_v11_demo_$(date +%Y%m%d_%H%M%S).log"

Expected key lines
------------------
[CLOSED_LOOP] LOADING
[CARLA] route set ... matrix=... runtime=...
[CLOSED_LOOP] HAUL
[CLOSED_LOOP] UNLOADING
[CLOSED_LOOP] COMPLETED
