CLOSED LOOP V1 PATCH
====================

Purpose
-------
Connect the already-frozen Decision, Monitoring and Simulation layers into one
minimal executable mine-dispatch loop:

task -> WorldState -> GreedyScheduler -> Assignment -> CAT to loading
-> LOADING -> CAT to dump -> UNLOADING -> COMPLETED -> feedback -> next task

Vehicle failure is connected to DecisionReplanner:
assigned task -> release -> pending -> healthy CAT takeover.

Important architecture boundaries
---------------------------------
- Decision files are NOT modified.
- CarlaAdapter is NOT modified.
- VehicleBehavior is NOT modified.
- Monitoring files are NOT modified.
- Storage schema/models/database are NOT modified.
- Closed Loop calls Runtime execution methods; Decision never calls CARLA.
- Monitoring remains observation-only.
- SQLite remains persistence/history, not the live decision bus.

Files added
-----------
configs/closed_loop_v1.json
src/open_pit_competition/closed_loop/models.py
src/open_pit_competition/closed_loop/state_builder.py
src/open_pit_competition/closed_loop/coordinator.py
tests/test_closed_loop_v1.py

Files overwritten
-----------------
src/open_pit_competition/closed_loop/manager.py
src/open_pit_competition/closed_loop/metrics.py
src/open_pit_competition/closed_loop/evaluator.py
src/open_pit_competition/simulation/runtime.py

Not touched
-----------
src/open_pit_competition/decision/*
src/open_pit_competition/simulation/carla_adapter.py
src/open_pit_competition/simulation/vehicle_behavior.py
src/open_pit_competition/monitoring/*
src/open_pit_competition/storage/*
configs/decision_route_matrix.json
configs/haul_route_matrix.json
configs/monitoring_stations.json
configs/monitoring_camera_layout.json
runtime_data/database/open_pit.db

Closed Loop V1 behavior
-----------------------
Business states:
IDLE -> TO_LOADING -> LOADING -> TO_DUMP -> UNLOADING -> IDLE
FAULT is the failure path.

Task states:
PENDING -> ASSIGNED -> LOADING -> TO_DUMP -> UNLOADING -> COMPLETED

Loading service: 4 s after the CAT is actually stopped.
Unloading service: 3 s after the CAT is actually stopped.
Decision fallback interval: 5 s.
Observation/progress check: 0.5 s.
Task generation: seeded from reachable haul routes in decision_route_matrix.
Default: 8 tasks, seed 20260910.

Road closure note
-----------------
S07 still physically holds/resumes CATs through Runtime/VehicleBehavior.
Closed Loop V1 does NOT fake alternate rerouting because the current Decision
matrix contains one precomputed route per endpoint pair. True alternate-route
rerouting is a later optional extension.

Install
-------
cd ~/矿山调度/open_pit_competition
unzip -o ~/下载/closed_loop_v1_patch.zip -d .

Tests
-----
PYTHONPATH=src python -m pytest -q

Run first integration
---------------------
Start CARLA in the other terminal, then:

PYTHONPATH=src python -m open_pit_competition.simulation.runtime \
  --scenario configs/scenarios/s01_normal.json \
  --monitoring \
  --closed-loop \
  2>&1 | grep --line-buffered -v "WARNING: cannot parse georeference" \
  | tee "runtime_data/logs/closed_loop_v1_s01_$(date +%Y%m%d_%H%M%S).log"

What to look for
----------------
[CLOSED_LOOP] ASSIGN
[CLOSED_LOOP] LOADING
[CLOSED_LOOP] HAUL
[CLOSED_LOOP] UNLOADING
[CLOSED_LOOP] COMPLETED

During a 90 s S01 run, long mine routes may not complete all 8 tasks. That is
not itself a failure. The first integration check is that assignments cause
real CAT destination changes and lifecycle transitions appear when endpoints
are reached.

Result file
-----------
runtime_data/results/closed_loop_v1_summary.json
