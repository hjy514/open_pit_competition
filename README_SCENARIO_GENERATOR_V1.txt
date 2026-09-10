ScenarioGenerator(seed) V1
==========================

目的
----
在不破坏固定 S01 / S02 / S07 基准场景的前提下，增加可复现的随机场景。

V1 随机内容
-----------
1. 场景模式：
   failure / closure / compound
2. 故障车辆：
   默认只从 truck_2 / truck_3 中选择
3. 故障时间与恢复时间
4. 封路时间与重开时间

V1 明确不随机
-------------
- CARLA 地图：仍为 0325_5
- CAT blueprint
- 正式标定路线：仍使用 12/78 -> 48
- Decision 调度算法
- VehicleBehavior
- Monitoring
- Storage
- 固定 S01/S02/S07 JSON

这样做的原因：
图上可达不等于 CAT 物理可稳定行驶，因此 V1 不随机未验证路线。

同一个 seed 可复现
-----------------
例如：
PYTHONPATH=src python scripts/generate_random_scenario.py --seed 1001 --mode mixed

默认输出：
runtime_data/generated_scenarios/random_seed_1001.json

再次使用相同 seed + mode，会得到相同随机结果。

可选模式
--------
--mode failure
--mode closure
--mode compound
--mode mixed

mixed 会在 failure / closure / compound 中按 seed 确定一种。

推荐先验证生成器，不跑 CARLA
---------------------------
PYTHONPATH=src pytest -q

然后生成几个样例：
PYTHONPATH=src python scripts/generate_random_scenario.py --seed 1001 --mode mixed
PYTHONPATH=src python scripts/generate_random_scenario.py --seed 1002 --mode mixed
PYTHONPATH=src python scripts/generate_random_scenario.py --seed 1003 --mode mixed

生成的 JSON 与现有 load_scenario() 兼容，可以直接作为：
--scenario runtime_data/generated_scenarios/random_seed_1001.json

注意
----
V1 的 compound 模式故意让“故障”和“封路”分阶段发生，而不是强制重叠，
这样更适合当前比赛展示和问题定位。后续如果需要压力测试，可以再加 overlap/stress 模式。
