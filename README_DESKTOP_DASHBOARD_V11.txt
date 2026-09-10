Desktop Dashboard V1.1 - 旧版桌面架构升级版
================================================

定位
----
这一版不再把“浏览器网页”作为比赛主界面。

确认旧仓库使用的是：
- PyQt6 独立桌面窗口
- QGraphicsView 动态地图
- 车辆状态面板
- 事件面板
- 独立 Human Dispatch / AI Agent 窗口
- 多路 Camera Wall
- HTTP API 作为后台数据源

V1.1 直接恢复“桌面调度中心”体验，并改接 open_pit_competition 当前真实数据。

新增
----
open_pit_dispatch_app/
  main.py
  api_client.py
  requirements.txt
  ui/main_window.py
  ui/theme.py
  ui/vehicle_labels.py
  widgets/map_widget.py
  widgets/vehicle_panel.py
  widgets/event_panel.py
  widgets/closed_loop_panel.py
  widgets/camera_wall.py
  windows/dispatch_window.py
  windows/data_window.py
  __init__.py 等

覆盖
----
start_dispatch_app.sh

不修改
------
Decision
VehicleBehavior
CarlaAdapter
Simulation Runtime
Closed Loop
Monitoring
Storage
ScenarioGenerator / TaskGenerator
SQLite schema
正式 S01/S02/S07
CARLA 路线矩阵
现有 frontend/ 浏览器文件（保留作调试/备选，不作为最终主界面）

桌面主界面
----------
旧版主布局继续保留：

顶部：
  露天矿无人运输智能调度平台
  决策调度中心
  运行/数据中心

场景控制：
  S01 / S02 / S07 / RANDOM
  Seed
  mixed / compound / failure / closure
  随机 Seed
  生成场景
  一键运行
  安全停止

中部左：
  动态态势地图
  全局与多车视角

中部右：
  CAT 车辆实时状态
  Decision 摘要
  异常事件提醒

底部：
  闭环运行与数据采集

动态地图
--------
保留旧版 QGraphicsView 思路，并改成当前正式数据：
- 0325_5
- 12->48 / 78->48 正式路线
- CAT 实时位置
- CAT 轨迹
- Loading 12 / 78
- Dump 48
- 固定站点
- 车辆状态颜色
- 车辆 tooltip
- 选中车辆
- 鼠标滚轮缩放
- 中键拖动平移
- 双击复位
- 窗口缩放时自适应

状态颜色：
- 绿色：正常运行
- 蓝色：LOADING / UNLOADING
- 黄色：非空闲低速等待
- 红色：FAULT
- 灰色：IDLE

异常联动
--------
故障/封路等事件：
- 主界面顶部红色提醒
- 事件面板提醒
- 系统 beep
- “进入决策调度中心”快捷入口

决策调度中心
------------
显示真实：
- task_id
- 12/78 -> 48
- priority
- release_time
- assigned CAT
- status
- Assignment
- route_id
- score / reason
- 当前异常

本版不让 PyQt 界面绕过 Decision 直接调用 CARLA。
如果以后要人工改派，必须单独通过 Closed Loop/Decision 的受控入口实现。

多车视角
--------
恢复旧版 6 CAT + 固定站视频墙布局。

注意：
当前 open_pit_competition SQLite 只有 camera_enabled，没有真实 RGB frame/stream。
因此 V1.1 不伪造视频，只显示真实车辆/站点状态覆盖层。

下一小步 Camera Bridge 才接：
- CAT camera
- 3 固定站 camera
- PNG/JPEG/QImage frame
- 低帧率视频墙 + 选中路高帧率视图

运行方式
--------
不要再手动打开浏览器。

1. 先启动 CARLA Server。
2. 然后在新仓库执行：

   cd ~/矿山调度/open_pit_competition
   ./start_dispatch_app.sh

start_dispatch_app.sh 会：
- 检查/自动启动当前 Dashboard API (8765)
- 后台 API 用 openpit-agent Python
- 桌面窗口优先用 ~/miniconda3/envs/openpit-ui/bin/python
- 直接弹出 PyQt6 调度中心
- 关闭桌面程序后，若 API 是本次自动启动的，会一并关闭

快捷键
------
Ctrl+D  决策调度中心
Ctrl+M  动态地图
Ctrl+V  多车视角
Ctrl+I  运行/数据中心
F11     主窗口全屏

PyQt 环境
---------
旧版 requirements 显示 PyQt6。
如果 ~/miniconda3/envs/openpit-ui 已存在，直接沿用。

如果启动时报 PyQt6 缺失，再处理 UI 环境；不要把 PyQt6 安装进 openpit-agent Python3.7 环境，
避免影响当前已经稳定的 CARLA 0.9.10 后端。
