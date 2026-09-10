Random Task Layer V2
====================

目标
----
在 ScenarioGenerator(seed) V1 的事件随机基础上，再让 Closed Loop 的任务层随 seed
变化，从而避免每次运行都呈现完全一样的业务调度顺序。

随机内容
--------
- task priority：1 / 2 / 3
- task release_time_s：0 / 8 / 16 / 24 秒
- task_templates 列表顺序

安全约束
--------
- 物理路线不随机
- 仍然只有 12 -> 48 和 78 -> 48
- origin=12 至少一个任务在 0 秒释放
- origin=78 至少一个任务在 0 秒释放
- 不修改 Decision
- 不修改 VehicleBehavior
- 不修改 CarlaAdapter
- 不修改 Runtime
- 不修改 Monitoring / Storage
- 不修改固定 S01 / S02 / S07
- 不覆盖 configs/closed_loop_formal_s01.json

为什么先不随机路线
------------------
现阶段只有正式标定的 12/78 -> 48 路线适合直接用于展示。
随机未验证 OD 会重新引入 CAT 打转、卡住和超长绕路风险。

使用
----
先测试：

PYTHONPATH=src pytest -q

生成一个完整随机运行包：

PYTHONPATH=src python scripts/generate_random_run.py --seed 1002 --mode mixed

默认生成两个文件：

runtime_data/generated_scenarios/random_seed_1002.json
runtime_data/generated_closed_loop/random_seed_1002.json

同一个 seed + mode 会复现同一个场景事件和同一套任务属性。

脚本最后会打印对应的 CARLA Runtime 命令。
当前阶段先看生成结果，不要求立即跑 CARLA。
