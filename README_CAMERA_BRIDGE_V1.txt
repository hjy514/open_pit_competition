CAT Camera Bridge V1
====================

目标
----
给当前 PyQt 桌面调度平台接入真实 CARLA 多车画面。

本版新增的 CAT 摄像头只负责“展示”，不参与车辆行为、安全控制、
Decision、Closed Loop 或 Monitoring 判定。

数据链
----
truck_1 ... truck_6 (CARLA vehicle.cat.cat)
        |
        | role_name 查找
        v
scripts/camera_bridge.py   [openpit-agent / Python3.7 / CARLA0.9.10]
        |
        | sensor.camera.rgb
        v
runtime_data/monitoring/dashboard_cameras/
  truck_1_latest.png
  ...
  truck_6_latest.png
        |
        v
PyQt Camera Wall

固定站不新建摄像头，直接复用现有 Monitoring：
runtime_data/monitoring/cameras/
  station_road_01_latest.png
  station_road_02_latest.png
  station_road_03_latest.png

本次新增
--------
configs/dashboard_camera_bridge.json
scripts/camera_bridge.py
tests/test_camera_bridge_v1.py
README_CAMERA_BRIDGE_V1.txt

本次覆盖
--------
open_pit_dispatch_app/widgets/camera_wall.py
start_dispatch_app.sh

明确不修改
----------
Decision
VehicleBehavior
CarlaAdapter
Simulation Runtime
Closed Loop
Monitoring manager/fixed_station
Storage
SQLite schema
ScenarioGenerator / TaskGenerator
S01 / S02 / S07
正式路线矩阵
动态地图

安全边界
--------
Camera Bridge:
- 只查找 role_name=truck_1 ... truck_6 的车辆
- 只创建 sensor.camera.rgb
- 只 destroy 自己创建的 camera sensor
- 不调用 vehicle.apply_control
- 不设置 destination
- 不修改 route
- 不 destroy CAT actor
- 场景车辆消失后自动移除对应 camera
- 新 CAT 出现后自动挂载 camera

默认摄像头
----------
640 x 360
4 FPS
FOV 90
车辆跟随视角：
  x=-8.0
  y=0.0
  z=5.5
  pitch=-12

这是第一版通用 CAT 跟随视角。
如果真实运行后发现矿卡车斗遮挡或镜头高度不理想，只改
configs/dashboard_camera_bridge.json 的 transform，不改核心代码。

桌面视频墙
----------
- 6 路 CAT
- 3 路固定站
- LIVE/OFFLINE
- CAT：业务状态 / 速度 / 当前任务
- 固定站：Road/Lane / 车辆数 / Camera状态
- 250ms UI刷新
- 帧超过3秒未更新自动显示OFFLINE
- 双击任意画面打开大窗口

启动
----
保持 CARLA Server 运行：

  cd ~/矿山调度/open_pit_competition
  ./start_dispatch_app.sh

新 start_dispatch_app.sh 会：
1. 启动/复用 Dashboard API
2. 用 openpit-agent Python3.7 后台启动 Camera Bridge
3. 用 openpit-ui 启动 PyQt
4. 关闭桌面程序后，向本次启动的 Camera Bridge 发送 SIGINT
5. Camera Bridge 只销毁自己的 sensors

日志
----
runtime_data/logs/dashboard_camera_bridge.log

如果界面 CAT Camera 仍为 0/6，先看：

  tail -80 runtime_data/logs/dashboard_camera_bridge.log

测试
----
  PYTHONPATH=src pytest -q

新增测试不连接 CARLA，只验证配置、truck role 和输出路径。
真实 RGB 接入需要在 CARLA Server + 场景运行时验收。
