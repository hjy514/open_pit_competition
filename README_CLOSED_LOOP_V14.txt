CLOSED LOOP V1.4 - CARLA 0.9.10 ROUTE EXECUTION COMPATIBILITY
================================================================

What the V1.3 six-CAT log proved
--------------------------------
The problem is no longer an arrival-radius problem.

All six selected routes were injected correctly and matrix/runtime route
distances matched exactly.  But several CATs stopped tens or hundreds of metres
before their endpoints.  The new diagnostic also showed remaining_wp="-" for
every CAT, which means the installed CARLA 0.9.10 LocalPlanner does not expose
the newer get_plan() API used by the V1.3 diagnostic.

V1.4 fixes three execution-layer compatibility issues without changing
VehicleBehavior itself.

1. CARLA 0.9.10/0.9.11 explicit global-plan compatibility
-----------------------------------------------------------
Before applying a Decision route, stale _waypoint_buffer content is cleared.
After set_global_plan(), old/new planner flags are set when available:
- _global_plan = True
- _stop_waypoint_creation = True

This prevents the old LocalPlanner from continuing/randomly extending a route
after an explicit Decision global plan.

2. Real route progress on old CARLA
-----------------------------------
Route status now supports both API families:
- newer: local_planner.get_plan()
- older: waypoints_queue / _waypoints_queue + _waypoint_buffer

The next S10 log should therefore show an integer remaining_wp instead of "-".

3. Cross-route false front-vehicle suppression
----------------------------------------------
VehicleBehavior is intentionally generous on curved mine roads and does not use
road_id/lane_id as hard global constraints.  In S10, six CATs are simultaneously
on different Decision routes that can run close to one another in 3D.

For two controlled CATs with different active Decision route IDs, CarlaAdapter
now gives VehicleBehavior the other CAT only when CARLA currently places both
on the same road_id + lane_id.  Same-route CAT following is unchanged.
Unrouted actors are unchanged.  BasicAgent still keeps its own immediate
route/lane hazard handling.

Files overwritten
-----------------
src/open_pit_competition/simulation/carla_adapter.py

Files added
-----------
tests/test_closed_loop_v14_carla0910_route.py
README_CLOSED_LOOP_V14.txt

NOT changed
-----------
VehicleBehavior
Runtime
ClosedLoopCoordinator
Decision
Monitoring
Storage
route matrices
six-CAT S10
S01/S02/S07

Install
-------
cd ~/矿山调度/open_pit_competition
unzip -o ~/下载/closed_loop_v14_carla0910_route_fix.zip -d .

Then:
PYTHONPATH=src python -m pytest -q

Real verification
-----------------
Run the same six-CAT S10 command.

Expected diagnostic improvement:
remaining_wp=<integer>

Expected lifecycle:
LOADING -> HAUL -> ARRIVAL -> UNLOADING -> COMPLETED
