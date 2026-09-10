CLOSED LOOP V1.2 ARRIVAL / COMPLETION FIX
=========================================

Finding from the six-CAT S10 log
--------------------------------
V1.1 successfully aligned the Decision-selected OD route with CARLA:
for all six CATs, matrix distance == runtime GlobalRoutePlanner distance.

All six CATs entered LOADING, then all six entered TO_DUMP.

However none entered UNLOADING before 180 s, including the 98.8 m route.
The current business arrival test only accepts:
    distance(current CAT position, raw destination spawn transform)
        <= arrival_radius_m

On a custom CARLA map, GlobalRoutePlanner / LocalPlanner finishes at its road
waypoint projection.  That endpoint can be somewhat offset from the raw spawn
transform.  As a result a CAT can finish the physical CARLA route and stop,
while Closed Loop still says TO_DUMP.

V1.2 fix
--------
Arrival now has two valid signals:

1. normal geometric arrival:
   endpoint gap <= arrival_radius_m

2. CARLA route completion:
   BasicAgent.done() == True
   AND endpoint gap <= route_complete_acceptance_radius_m (default 35 m)

The second rule is bounded; route completion from far away does NOT complete
the business task.

New diagnostic:
[CLOSED_LOOP] ARRIVAL | truck_X | target=... | mode=route_done | endpoint_gap=...

Files overwritten
-----------------
src/open_pit_competition/simulation/runtime.py
src/open_pit_competition/closed_loop/coordinator.py
configs/closed_loop_v11_demo.json

File added
----------
tests/test_closed_loop_v12_arrival.py
README_CLOSED_LOOP_V12.txt

Not changed
-----------
CarlaAdapter route implementation
VehicleBehavior
Decision scheduler/replanner/models
Monitoring
Storage
S01/S02/S07
six-CAT S10 fleet/scenario
decision_route_matrix.json

Install
-------
cd ~/矿山调度/open_pit_competition
unzip -o ~/下载/closed_loop_v12_arrival_fix.zip -d .

Then:
PYTHONPATH=src python -m pytest -q

Real CARLA verification
-----------------------
Use the same six-CAT S10 command as V1.1.
Expected transition:
LOADING -> HAUL -> ARRIVAL -> UNLOADING -> COMPLETED
