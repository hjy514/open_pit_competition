Decision V3 - Dynamic Replan Patch

Purpose:
- adds pure Decision-layer task lifecycle for vehicle failure/recovery
- releases the failed truck's assigned task
- lets an idle healthy CAT truck take over through the existing GreedyScheduler

Files added:
- src/open_pit_competition/decision/replanner.py
- scripts/demo_decision_v3_replan.py
- tests/test_replanner.py

File overwritten:
- src/open_pit_competition/decision/__init__.py

Files NOT touched:
- simulation/runtime.py
- simulation/carla_adapter.py
- simulation/vehicle_behavior.py
- decision/models.py
- decision/policy.py
- decision/route_planner.py
- decision/scheduler.py
- configs/decision_route_matrix.json
