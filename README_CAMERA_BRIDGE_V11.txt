CAT Camera Bridge V1.1 - Old Project Adaptive Chase View
=========================================================

原因
----
V1 使用固定相机：
  x=-8.0m, z=5.5m, pitch=-12deg

对 CAT 大型矿卡来说太近，画面主要被车尾占据。

旧版 open_pit_agent_demo 的真实实现
----------------------------------
旧版不是使用固定 -8m 参数，而是根据车辆真实 bounding_box 自适应：

  half_length = actor.bounding_box.extent.x
  half_height = actor.bounding_box.extent.z

  follow_distance =
      max(20.0, half_length * 2.0 + 8.0)

  camera_height =
      max(10.0, half_height + 7.0)

  local x = -follow_distance
  local y = 0
  local z = camera_height
  pitch   = -16deg
  yaw     = 0deg
  roll    = 0deg

摄像头仍 attach_to CAT，所以会跟随车辆转向和行驶。

V1.1 修改
---------
覆盖：
  configs/dashboard_camera_bridge.json
  scripts/camera_bridge.py
  tests/test_camera_bridge_v1.py

新增：
  README_CAMERA_BRIDGE_V11.txt

不修改：
  open_pit_dispatch_app/widgets/camera_wall.py
  start_dispatch_app.sh
  Decision
  VehicleBehavior
  CarlaAdapter
  Runtime
  Closed Loop
  Monitoring
  Storage
  地图
  场景

效果
----
相机相对 V1 会显著：
- 更远
- 更高
- 俯视角更合理
- 车身在画面里变小
- 前方道路占比增加

而且对于不同尺寸车辆会自动适配，不再写死同一个 x/z。

日志
----
启动后：
  tail -f runtime_data/logs/dashboard_camera_bridge.log

会看到类似：
  [CAMERA BRIDGE] attached truck_1 ... | chase x=-24.0 z=11.5 pitch=-16.0

实际数值由 vehicle.cat.cat 的真实 bounding_box 决定。

安装
----
  cd ~/矿山调度/open_pit_competition
  unzip -o ~/下载/camera_bridge_v11_old_project_view.zip -d .
  PYTHONPATH=src pytest -q

然后关闭当前桌面程序并重新：
  ./start_dispatch_app.sh

不需要重新做完整 S01/S02/S07 验证。
只需启动一个场景，看 1~2 辆 CAT 的相机视角即可。
