CLOSED LOOP V1.6 - STALL WATCHDOG + BOUNDED ROUTE RECOVERY
================================================================

Evidence from V1.5
------------------
V1.5 proved VehicleBehavior is not commanding the stalls:
behavior=cruise
reason=no active safety constraint

At the same time, remaining_wp stopped decreasing while the CAT was still far
from the route endpoint. That is a physical route-following stall.

V1.6 fix
--------
This patch adds a bounded execution-layer recovery mechanism.

Closed Loop triggers recovery only when ALL are true:
1. vehicle is travelling on the expected Decision route;
2. remaining waypoint count has not decreased for 8 seconds;
3. CAT speed <= 0.8 km/h;
4. VehicleBehavior state is CRUISE or RESUME;
5. it is not already inside the final route waypoint window;
6. per-leg recovery count is below 4.

Recovery action:
1. keep the same Decision assignment and same OD route;
2. find the CAT's nearest waypoint on that exact route;
3. choose a point about 18 m forward along that route;
4. require at least 12 m clearance to other controlled CATs;
5. relocate the CAT to the route waypoint with +0.5 m Z offset;
6. zero residual linear/angular motion;
7. rebuild and reattach the exact same Decision route.

This does NOT:
- change Decision
- change task assignment
- change Monitoring
- change VehicleBehavior
- change route matrix
- mark a task complete artificially

New log:
[CARLA RECOVERY] ...
[CLOSED_LOOP RECOVERY] ...

Files overwritten
-----------------
src/open_pit_competition/simulation/carla_adapter.py
src/open_pit_competition/simulation/runtime.py
src/open_pit_competition/closed_loop/coordinator.py
configs/closed_loop_v11_demo.json

Files added
-----------
tests/test_closed_loop_v16_stall_recovery.py
README_CLOSED_LOOP_V16.txt

Not changed
-----------
VehicleBehavior
Decision scheduler/replanner/models
Monitoring
Storage
decision_route_matrix.json
six-CAT S10 fleet/scenario
S01/S02/S07
