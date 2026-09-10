CLOSED LOOP V1.5 - SINGLE SAFETY OWNER FIX
================================================

Evidence from V1.4 six-CAT run
------------------------------
V1.4 fixed route progress inspection. remaining_wp is now numeric and proves
the Decision route is actually consumed.

Examples:
- truck_1: 43 -> 30, then stalls
- truck_2: 87 -> 70, then stalls
- truck_3: 73 -> 65, then stalls
- truck_4: 135 -> 99, then stalls
- truck_5: 182 -> 162, then stalls
- truck_6: 173 -> 159, then stalls

All six slow to ~0 km/h while many route waypoints still remain.
Therefore this is NOT an arrival-radius problem and NOT a route-matrix problem.

Root execution conflict
-----------------------
CarlaAdapter.step_vehicle() first asks VehicleBehavior for the mine-truck safety
decision, but then called BasicAgent.run_step().

BasicAgent.run_step() has its own independent obstacle / vehicle / traffic-light
hazard checks and can emergency-brake before returning its control.

That creates two longitudinal safety owners:
1. project VehicleBehavior
2. CARLA BasicAgent hazard layer

On the custom mine map, multiple independent routes can pass close to one
another, so the second layer can stop a CAT even when VehicleBehavior considers
that vehicle unrelated.

V1.5 architecture
-----------------
VehicleBehavior:
  sole longitudinal safety owner

CARLA LocalPlanner:
  selected route + lateral steering + PID

CarlaAdapter:
  execution only

The adapter now calls LocalPlanner.run_step() directly after setting the speed
selected by VehicleBehavior. It no longer calls BasicAgent.run_step() during
normal driving.

VehicleBehavior's brake override remains authoritative, so:
- FOLLOW
- DECELERATE
- WAIT_FRONT
- YIELD
- ROAD_HOLD
- OBSTACLE_STOP
- EMERGENCY_STOP
- FAULT_STOP
are still preserved.

Diagnostics
-----------
[CLOSED_LOOP ROUTE] now also prints:
behavior=<state>
reason=<VehicleBehavior reason>

If a CAT stalls again, the log immediately tells whether VehicleBehavior asked
it to stop or whether the physical controller is failing to move.

Files overwritten
-----------------
src/open_pit_competition/simulation/carla_adapter.py
src/open_pit_competition/closed_loop/coordinator.py

Files added
-----------
tests/test_closed_loop_v15_single_safety_owner.py
README_CLOSED_LOOP_V15.txt

NOT changed
-----------
VehicleBehavior
Runtime
Decision
Monitoring
Storage
route matrices
six-CAT S10
S01/S02/S07
