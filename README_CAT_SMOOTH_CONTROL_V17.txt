CAT Smooth Control V1.7
=======================

目的：
- 限制 CAT 转向瞬时跳变
- 限制普通 throttle / brake 突变
- 抑制 14 km/h 目标速度时冲到 16~17 km/h 的明显超调

运行补丁脚本后只修改：
src/open_pit_competition/simulation/carla_adapter.py

自动备份：
src/open_pit_competition/simulation/carla_adapter.py.before_v17_cat_smooth

不修改：
Decision
VehicleBehavior
Monitoring
Storage
S01/S02/S07
fleet.json
路线矩阵
Closed Loop 任务/分配逻辑

安全原则：
VehicleBehavior 的 brake_override 仍立即执行，不做平滑削弱。

安装：
cd ~/矿山调度/open_pit_competition
python scripts/patch_cat_smooth_control_v17.py

然后：
PYTHONPATH=src pytest -q
