Desktop Dynamic Map V1.5 - Visual Refinement
================================================

目的
----
V1.4 已解决“完整路网、路线、车辆必须使用同一 CARLA world 坐标”的核心问题。
V1.5 只做显示精修，不改变任何坐标、路线、业务和运行逻辑。

覆盖
----
open_pit_dispatch_app/widgets/map_widget.py

不修改
------
Dashboard API / service
Decision
VehicleBehavior
CarlaAdapter
Runtime
Closed Loop
Monitoring
Storage
Scenario / TaskGenerator
SQLite schema
S01 / S02 / S07
正式路线矩阵

主要变化
--------
1. 默认关闭地图上的车辆文字标签，避免多车聚集时一团文字。
2. 点击某辆 CAT 后，仅该车辆显示：
   truck_x | 业务状态 | km/h
   详细任务/Road/Lane 继续放在 tooltip / 右侧车辆面板。
3. 当前活动运输路线：
   - 加粗
   - 增加深色 halo
   - 增加方向箭头
4. 非活动路线：
   - 细一些
   - 虚线
5. 历史轨迹：
   - 透明度降低
   - 更细
6. 任务区：
   - L12 / L78 / D48 保留为小型业务锚点
7. 固定站：
   - 只显示 S1/S2/S3 小标记
   - 详细 Road/Lane/Camera 放 tooltip
8. 右上角新增“图层”菜单，可独立开关：
   - 完整路网
   - 规划路线
   - 车辆轨迹
   - 任务区域
   - 固定站点
   - 车辆文字标签
9. 保留：
   - 滚轮缩放
   - 中键拖动
   - 双击 / R 复位
   - + / - / 全图
   - 点击 CAT 选中

验收
----
重点看：
- 路网是否仍与彩色路线重合
- 多车聚集时地图是否明显更干净
- 活动路线方向是否一眼能看懂
- 图层开关是否顺手
