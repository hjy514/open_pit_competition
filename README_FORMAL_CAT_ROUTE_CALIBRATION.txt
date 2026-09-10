S01 / S02 / S07 正式 Closed Loop CAT 路线标定 V1
===================================================

目的
----
解决正式 S02 中出现的“大 CAT 打转、路线交叉、碰撞风险”问题。

根因不是 Decision 调度逻辑，而是原 Closed Loop 配置允许 Decision 使用
大量仅由 GlobalRoutePlanner 判定“图上可达”、但未做大型 CAT 物理标定的
装载/卸载组合，导致 3~6 km 的长空驶路线互相交叉。

本包把正式 S01/S02/S07 的业务候选路线收紧为：
- loading: 12, 78
- dump: 48
- haul: 12->48, 78->48

这与正式 fleet.json 的生成位置一致，因此初始任务为空驶距离为 0，
车辆直接进入 LOADING -> HAUL，不再先跑 3~6 km 的未标定空驶路线。

覆盖文件
--------
无。

新增文件
--------
configs/operating_areas_formal_calibrated.json
configs/closed_loop_formal_s01.json
configs/closed_loop_formal_s02.json
configs/closed_loop_formal_s07.json
scripts/build_formal_cat_route_matrix.py
README_FORMAL_CAT_ROUTE_CALIBRATION.txt

脚本运行后新增
--------------
configs/decision_route_matrix_formal_calibrated.json

不修改
------
Decision
VehicleBehavior
CarlaAdapter
Runtime
Monitoring
Storage
S01/S02/S07 场景 JSON
fleet.json
原 decision_route_matrix.json
原 operating_areas.json
原 closed_loop_v11_demo.json

先运行
------
PYTHONPATH=src python scripts/build_formal_cat_route_matrix.py

S02 再运行
----------
PYTHONPATH=src python -m open_pit_competition.simulation.runtime \
  --scenario configs/scenarios/s02_vehicle_failure.json \
  --fleet configs/fleet.json \
  --monitoring \
  --closed-loop \
  --closed-loop-config configs/closed_loop_formal_s02.json
