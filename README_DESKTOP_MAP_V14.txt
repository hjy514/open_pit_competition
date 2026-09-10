Desktop Dynamic Map V1.4 - CARLA World Same-Source Map
=======================================================

为什么改回这一版
----------------
旧版地图显示正确的核心不是 XODR 手工转换，而是 roads / routes / vehicles
全部来自同一个 Runtime/CARLA 世界坐标，再用同一个 world_to_scene 投影。

V1.3 直接解析 XODR，导致灰色 OpenDRIVE reference geometry 与 CARLA
route / telemetry 使用了两个来源。V1.4 完全取消这种叠加方式。

V1.4 数据链
-----------
CARLA 0325_5
  |- map.generate_waypoints(2m) -> 完整 lane centerline 路网
  |- GlobalRoutePlanner          -> 12->48 / 78->48 正式路线
  |- spawn_points               -> L12 / L78 / D48
  `- Runtime SQLite telemetry   -> CAT / trajectory / station

所有 X/Y 都是 CARLA world coordinates。
不翻 Y，不解析 XODR，不做人工坐标对齐。

本次覆盖
--------
src/open_pit_competition/dashboard/service.py
open_pit_dispatch_app/widgets/map_widget.py
start_dispatch_app.sh

新增
----
tests/test_dashboard_map_v14.py
README_DESKTOP_MAP_V14.txt

不修改
------
Decision
VehicleBehavior
CarlaAdapter
Simulation Runtime
Closed Loop
Monitoring
Storage
Scenario / TaskGenerator
SQLite schema
S01/S02/S07
正式路线矩阵

路网生成
--------
CARLA generate_waypoints(2.0m) 后按：
road_id + section_id + lane_id
分组，并按 waypoint.s 排序成 lane polyline。

若同组相邻点间隔超过 8m，会切成两段，避免错误跨接。
若 generate_waypoints 极端情况下没有数据，才用 get_topology() 粗粒度兜底。

这与旧版“road_segments 与车辆 route/position 同源”的原则一致，但当前新项目
不需要改 RuntimeState。

地图视觉
--------
- 完整 CARLA lane centerline 灰色路网
- 正式运输路线彩色覆盖
- CAT 轨迹
- L12 / L78 / D48
- S1 / S2 / S3
- CAT 方向箭头 / 速度
- 封闭 road/lane 红色
- 无右侧大图例
- 无 80m 大监控圆

操作
----
滚轮缩放
中键拖动
双击 / R 复位
+ / - / 全图
点击 CAT 选中

解决“补丁装了但界面没变”
------------------------
之前 start_dispatch_app.sh 会直接复用 8765 上任何能响应 /api/health 的进程，
所以代码更新后可能仍在使用旧 API 内存。

V1.4 health 增加：
api_version = dashboard-map-v14

启动脚本只复用版本完全一致的 API。
如果 8765 是旧进程，不杀它，而是在 8766-8769 中寻找空端口启动当前 API，
然后把桌面 UI 自动连接到该端口。

验收
----
地图左上角应看到：
0325_5 | CARLA_WORLD | 路网线:... | 点:... | CAT:...

只要 source=CARLA_WORLD 且 路网线/点 > 0，
灰色路网、彩色路线、CAT 都处于同一个 CARLA 世界坐标系。
