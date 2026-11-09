# Piper 直连演示动作时间覆盖审计

2026-11-09：该审计只读取已有压缩 rosbag 与 v2 候选，不访问 CAN、不发布 ROS 消息，
不改写原始数据，不导出 LeRobot 或训练样本。压缩包复制到临时目录再解压，结束自动清理临时目录；
需要足够的临时磁盘空间。
首次核查前使用的 ROS 直接解压方式在三个源包目录生成或刷新了同名 `.db3` 解压副本；
相应 `.db3.zstd` 原包仍在。当前没有删除这些副本；后来新版工具的解压已改用临时目录。

## 为什么要单独检查时间轴

此前 v2 候选把图像和动作统一放在 5Hz 网格；每个网格点缺失都会把候选切段，因此三条成功
演示的“50 个连续 v2 样本窗口”均为 0。这个结论适用于现有单频候选，不等于只能重新演示。
π0.5 的输入包含当前图像、状态和一个动作序列；动作序列的 50 步覆盖多长时间，取决于动作
数据的采样节拍。[官方模型配置](https://github.com/Physical-Intelligence/openpi/blob/main/src/openpi/models/pi0_config.py)
默认 `action_horizon=50`；[官方 LeRobot 加载器](https://github.com/Physical-Intelligence/openpi/blob/main/src/openpi/training/data_loader.py)
以数据集 FPS 生成动作序列时间偏移。

这里固定候选中的一张观测图片及对应状态为起点，只检查未来 50 个动作采样时刻是否有足够新鲜的
真实动作观测。图像不必在每个动作时刻都有新帧；不过官方标准 LeRobot 加载器不会自动支持本审计
的双频数据组织，正式方案需要固定版本后设计、实现和测试。

## 审计条件

- 使用原包 `start` 到 `success` / `failure` 范围，观测起点来自既有 v2 候选；下表统计成功父回合。
- 分别假设动作节拍 `5 / 10 / 20 / 50Hz`、长度 50；实际控制节拍尚未确定，这不是调参承诺。
- 每个采样时刻只取该时刻或之前的最近目标，目标年龄不大于 `100ms`；不得越过结果标签或目标记录末尾。
- 如果窗口与超过 `100ms` 的动作源间隔重叠，则丢弃整个窗口；不使用未来目标或反馈补动作。
- 允许多个采样时刻引用同一个 100ms 内的目标，并单独统计；这是有界历史取样假设，不证明固件
  在间隔中保持目标，也不代表真实执行时可照此发送。实体归属、夹爪零点及控制行为仍待确认。
- 统计的是候选起点的时间覆盖，不是完整独立演示数量，不把片段单独标为成功，也不表示模型可训练。

## 对三条成功演示的只读结果

| 演示 | 已有观测起点 | 假设 5Hz | 假设 10Hz | 假设 20Hz | 假设 50Hz |
| --- | ---: | ---: | ---: | ---: | ---: |
| `banana-direct-a05-002` | 139 | 0 | 13 | 49 | 83 |
| `banana-direct-a06-001` | 137 | 11 | 65 | 95 | 115 |
| `banana-direct-a06-002` | 140 | 0 | 25 | 61 | 96 |

例如最新回合在假设 20Hz 时，50 步覆盖 `2.45s`，61 个起点满足上述时间规则，窗口内历史目标
最老约 `56.2ms`，全部窗口合计 3 次重复引用目标。此结果不是“61 条完整成功演示”，也不是
可直接训练或驱动机械臂的数据；例如 50Hz 审计重复引用目标更多，不能按窗口数直接选定频率。

下一步应固定机器人命令执行周期、源反馈实体和夹爪映射，设计对齐策略并对数据加载器做离线测试；
保持源时间戳和目标年龄可追溯。然后再基于固定 openpi/LeRobot 版本组织训练集与独立场景评估集。

## 复现命令

在 SSH 的 **02-离线检查**终端执行，只读，不发送 CAN 帧：

```bash
cd ~/piper_tjp
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 run piper piper_dataset_timing_audit \
  data/2026-10-26/banana_into_box/scene-a06/banana-direct-a06-002 \
  data/2026-10-26/banana_into_box/scene-a06/banana-direct-a06-002-candidate-v2
```

工具检查清单和 rosbag 来源是否相符、回合标签和话题是否完整，并打印各节拍下的覆盖/排除原因。
输出 `audit_only=true`、`training_ready=false`；无论覆盖数量多少，都不会标记为训练就绪。

## 单个输入的离线格式预览

2026-11-09 新增 `piper_dataset_sample_preview`，只在内存组合一个图像、状态和动作窗口，
检查维度与相机映射，并输出原始观测和动作源时间戳。它与覆盖审计共用窗口选择规则，
拒绝跨结果标签、超出动作尾部、过期或横跨超过 100ms 源间隔的窗口；不写样本文件。

例如以下 `20Hz` 仅为假设，不是机械臂设置或最终训练节拍：

```bash
cd ~/piper_tjp
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 run piper piper_dataset_sample_preview \
  data/2026-10-26/banana_into_box/scene-a06/banana-direct-a06-002 \
  data/2026-10-26/banana_into_box/scene-a06/banana-direct-a06-002-candidate-v2 \
  --action-fps 20
```

真实包的首次预览得到候选索引 10：三张 RGB，状态形状 `7`、动作形状 `50×7`；目标最老
`55.69ms`，有 1 次复用同一近期目标。预览不证明固件持续保持该目标，不将样本标为可训练；
不同节拍和数据目录必须重新核对，正式推理和运动控制仍需独立设计与验收。

2026-11-09 后续新增 `DiagnosticEpisode` 离线逐条加载器及 `--check-all` 模式。每个窗口检查：
候选 JPEG 与其时间戳对应的原包 JPEG 逐字节一致、候选状态与原包该时刻反馈一致、图像与状态
未使用未来或过期数据、动作时间不跨越长目标间隔，且输出的源时间戳可追溯。它使用三个实际
回合，在假设 20Hz 条件下逐条读取了 `49 / 95 / 61` 个时间覆盖窗口，共 `205` 个重叠窗口；
三回合分别复用近期目标 `13 / 4 / 3` 次。没有导出训练集或对机械臂发送命令。

可将上面的单条预览命令末尾改为 `--action-fps 20 --check-all`，检查该回合全部覆盖窗口。
该检查只证明被检查窗口与录包一致，不证明录包的反馈实体、目标保持语义或夹爪执行映射正确。
不同回合的相同场景不得拆分到训练与验证集。

## 训练环境的 Python 边界

2026-11-09 本机 ROS 2 Humble 使用系统 Python 3.10；当日查看的官方 openpi `main` 的
[`pyproject.toml`](https://github.com/Physical-Intelligence/openpi/blob/main/pyproject.toml) 要求
Python `>=3.11`。当前逐条加载器依赖 ROS 2 Python 消息与 `rosbag2_py`，不能假定它可直接运行在
独立 openpi 环境。后续应先固定官方源码版本，在 ROS 3.10 环境导出带完整源时间戳的中间文件，
再由独立训练环境读取并进行 LeRobot / openpi 对接；保持中间文件为诊断用途，直到真实动作语义和
数据质量通过验收。不得修改系统 Python 来适配 openpi。

## 跨环境诊断副本（不是训练集）

已为 `a06-002` 在 ROS 环境中生成 v2 诊断副本，位于
`data/2026-10-26/banana_into_box/scene-a06/banana-direct-a06-002-diagnostic-portable-20hz-v2/`。
其中有 61 个**重叠窗口**、183 张 JPEG，以及状态、动作、场景和逐项源时间戳；总计约 9.2MiB。
数组与每张图片附带 SHA-256 校验值，清单强制 `diagnostic_only=true`、`training_ready=false`。
目录已被 Git 忽略。原包及候选没有覆盖；首版 v1 诊断副本也保留，当前读取器使用带数组校验的 v2。

在临时 Python `3.11.17` 虚拟环境中，仅安装 NumPy `1.26.4` 和 Pillow `13.0.0` 后，独立读取器
`piper.piper_diagnostic_portable` 已逐条检查 v2 全部 61 窗口，并确认未导入 `rclpy` 或
`rosbag2_py`。临时环境位于 `/tmp`，可能随重启消失；它不是 openpi 训练环境，未安装模型依赖。
导出器拒绝覆盖已存在的目录；若写入中途中断，会保留不完整目录，必须另选新目录，不能当作合格数据。

读取器检查字段、图像和数组校验值、时间网格及 100ms 新鲜度，并保留相机和动作源时间戳。
校验值用于发现副本意外变化，不能证明真实反馈实体归属或固件保持语义。动作频率 `20Hz` 仍仅为
试验假设；未进行 LeRobot 转换、openpi 联调、训练或真机控制。
