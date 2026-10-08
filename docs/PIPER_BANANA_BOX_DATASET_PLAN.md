# Piper Pi05 香蕉入盒与叠盒数据集规范

> 本文定义最终任务的数据采集边界、回合结构和验收标准。它不授权任何机械臂运动。
> 当前只有左侧上位机六关节跟随经过真机验证；夹爪转发、右侧上位机发送和共享 CAN
> 软件失能均仍有待完成的硬件安全验证。

## 1. 目标与阶段

最终目标不是直接训练“叠盒子”，而是逐级建立可复现数据：

| 阶段 | 任务 | 是否可正式采集 | 通过条件 |
| --- | --- | --- | --- |
| A0 | 相机、主从关节、夹爪反馈与标签的只读试录 | 已完成 | 所有话题可录入同一 rosbag |
| A1 | 香蕉入盒的场景布置、标签和人工演示预录 | 可进行，只读 | 不发送夹爪或机械臂运动命令 |
| A2 | 左侧示教的“香蕉入盒”真机演示 | 暂不可开始 | 左夹爪跟随通过硬件安全验证 |
| B1 | 空纸盒抓取、搬运、放置 | 暂不可开始 | A2 稳定复现，且纸盒重量/尺寸已记录 |
| B2 | 两个纸盒叠放 | 暂不可开始 | B1 成功率与安全边界达标 |
| C | 训练、离线回放和受控自主执行 | 暂不可开始 | 数据质量、标定、评测协议完成 |

当前只推进 A1：先把任务命名、场景编号、成功/失败条件和 rosbag 格式固定。没有夹爪真机验证，
不能采集“机械臂自主抓取香蕉”的训练样本，也不能把人工摆放物体误标为机械臂成功。

### A1 已完成的静态场景预录（2026-10-08）

已录制 `banana-a01-001`：`scene-a01` 中放置香蕉模型和空纸盒，四台机械臂均保持失能，
没有发送运动或夹爪命令。该包时长 `77.33s`、大小 `258.7 MiB`；六路相机各有 `380~387`
帧（约 `5 Hz`），回合标签为 `9` 条。标签回放确认使用 `piper_pi05_episode_v1` schema。
离线完整性检查已输出 `"valid": true`，并写入 `episode_manifest.json`；该清单不进入 Git。

录制时未启动示教桥，因此两路关节状态没有发布，也未写入本包；这是预期行为。该包仅用于
相机视角、目录、任务元数据和标签流程的基线验证，不能用于动作策略训练。

## 2. 任务拆分

### `banana_into_box`

一个回合只尝试将一个香蕉模型放入一个纸盒。建议记录的阶段：

1. `start`：相机和状态话题稳定后，记录香蕉和纸盒的初始位置；
2. `note`：可选，写入 `phase=approach`、`phase=grasp`、`phase=transport`、`phase=place`；
3. `success`：香蕉完全在纸盒内，纸盒未倾覆，保持静止至少 3 秒；
4. `failure`：夹取失败、香蕉掉落、碰撞、盒子倾覆、超出工作区、人工急停或传感器异常；
5. `end`：无论成功或失败都必须写入。

### `box_stack`

一个回合只尝试将一个空纸盒放在另一个纸盒上方。成功定义为：上盒完全由下盒支撑、无明显滑落，
操作者松开后保持静止至少 3 秒。失败原因应放在 `note`，例如 `topple`、`misaligned`、`drop`、
`collision`、`operator_stop` 或 `sensor_fault`。

将“香蕉入盒”和“叠盒”分开采集。不要把两个动作连成一个过长回合；后续可以把短技能按阶段组合，
更容易定位失败和训练。

## 3. 场景与回合编号

场景编号描述静态布置；回合编号描述该场景下的一次尝试：

```text
任务名：banana_into_box 或 box_stack
场景号：scene-a01、scene-a02、...
回合 ID：banana-a01-001、banana-a01-002、...
```

同一回合的所有 `start`、`note`、`success`/`failure`、`end` 标签必须具有完全相同的：

- `episode_id`
- `task`
- `scene_id`
- `attempt`
- `operator`

训练/验证/测试集必须按 **scene_id** 划分，不能随机拆散同一布置下的连续图像帧，否则会造成数据泄漏。
初期建议 `scene-a01` 至 `scene-a08` 作为训练布置，`scene-a09` 作为验证布置，保留后续未见布置作为测试。

## 4. rosbag 数据内容

每个正式回合录制以下话题：

```text
/dataset/camera_gripper_left/color/image_jpeg
/dataset/camera_gripper_left/depth/image_raw
/dataset/camera_gripper_right/color/image_jpeg
/dataset/camera_gripper_right/depth/image_raw
/dataset/camera_third_view/color/image_jpeg
/dataset/camera_third_view/depth/image_raw
/joint_states_teach_shared
/joint_states_follower_shared
/dataset/episode_marker
```

相机为约 `5 Hz`，主臂/从臂状态为约 `50 Hz`。保留原始 `header.stamp`，离线转换时按时间戳对齐，
不以消息到达顺序对齐。

每次录制结束后执行：

```bash
ros2 bag info <回合目录>
```

完整示教回合的验收要求：八路观测话题均存在；`/dataset/episode_marker` 至少有 `start`、结果标签和 `end` 各三条
（工具为可靠投递而重复发布三次）。缺少标签或任何相机话题的回合只能作为排障材料，不能进入训练集。
纯静态 A1 预录是例外：它只要求六路相机和 `start`、`note`、`end` 的九条标签，明确标注为
静态预录，不进入动作训练集。

## 5. 标签命令模板

标签工具只写 ROS 文本话题，不访问 CAN。以下命令示例不控制任何机械臂：

```bash
# 录包成功启动后，在另一个终端标记回合开始
ros2 run piper piper_episode_marker start \
  --episode-id banana-a01-001 \
  --task banana_into_box \
  --scene-id scene-a01 \
  --attempt 1 \
  --operator mips

# 成功时
ros2 run piper piper_episode_marker success \
  --episode-id banana-a01-001 \
  --task banana_into_box \
  --scene-id scene-a01 \
  --attempt 1 \
  --operator mips \
  --note '香蕉完全在盒内，保持静止3秒'

# 然后始终结束回合
ros2 run piper piper_episode_marker end \
  --episode-id banana-a01-001 \
  --task banana_into_box \
  --scene-id scene-a01 \
  --attempt 1 \
  --operator mips
```

失败回合把第二条换成 `failure` 并如实记录原因；不要删除失败数据。

## 6. 正式真机采集前的安全门

以下全部完成前，不得启动 `piper_teach_follow --send` 采集香蕉或纸盒操作：

1. 左侧从臂、物体和人员均处于安全姿态，急停可达；
2. 左夹爪的真实行程上限、力矩、共享 CAN 影响范围由硬件负责人确认；
3. 夹爪只做空载、小行程、单侧验证，并记录结果；
4. 右侧继续保持不做真实运动；
5. 相机、训练数据流和 rosbag 先完成一次不运动的完整格式检查；
6. 本文、`PIPER_DATA_COLLECTION.md` 和交接手册的安全状态均更新。

## 7. 容量与保存

当前六路训练流基线约为 `11.8 GiB/h`。预计 1 分钟回合约 `202 MiB`；100 个回合约为 `20 GiB`
（未包含额外日志和保留空间）。数据目录不进入 Git；Git 只保存代码、标注工具、协议文档和可复现命令。

当前机器尚无单独挂载的数据盘，可将正式数据放在工作区的被 Git 忽略目录：

```text
~/piper_tjp/data/2026-10-08/banana_into_box/scene-a01/banana-a01-001/
```

根目录 `.gitignore` 已排除整个 `data/`，因此 rosbag 不会出现在 `git status`，也不能被误提交。
首次正式采集前仍应记录可用容量和备份位置；当前系统盘可用空间约为 `851 GiB`。
