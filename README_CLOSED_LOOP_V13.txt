CLOSED LOOP V1.3 ROUTE-ENDPOINT ARRIVAL FIX
============================================

V1.2 log result
---------------
The six-CAT route handoff is correct: every selected haul route had identical
matrix/runtime GlobalRoutePlanner distance. But all six stayed TO_DUMP and
V1.2's BasicAgent.done() arrival fallback never triggered.

V1.3 fix
--------
CarlaAdapter now exposes:
- active route id
- remaining LocalPlanner waypoint count
- distance to the selected route's own final waypoint
- BasicAgent.done()

Closed Loop accepts physical arrival when:
- active route is the same Decision-selected route;
- distance to that route endpoint <= 12 m;
- remaining waypoints <= 8.

The original raw-spawn 10 m arrival rule remains.
The V1.2 bounded done() fallback also remains.

This avoids requiring a large CAT to hit CARLA's final planner point almost
exactly before business logic can enter UNLOADING.

New diagnostics
---------------
Every ~15 s:
[CLOSED_LOOP ROUTE] truck_X | route=... | speed=... | remaining_wp=... |
endpoint_gap=... | spawn_gap=... | done=...

Expected near endpoint:
[CLOSED_LOOP] ARRIVAL | ... | mode=route_endpoint | ...
[CLOSED_LOOP] UNLOADING
[CLOSED_LOOP] COMPLETED

Files overwritten
-----------------
src/open_pit_competition/simulation/carla_adapter.py
src/open_pit_competition/simulation/runtime.py
src/open_pit_competition/closed_loop/coordinator.py
configs/closed_loop_v11_demo.json

Files added
-----------
tests/test_closed_loop_v13_route_endpoint.py
README_CLOSED_LOOP_V13.txt

Not changed
-----------
VehicleBehavior
Decision scheduler/replanner/models
Monitoring
Storage
six-CAT S10 fleet/scenario
S01/S02/S07
decision_route_matrix.json
