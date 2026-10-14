# 固件直连的香蕉入盒演示采集

> 2026-10-14：目标是用 π0.5 学会香蕉入盒。左侧直连跟随、夹爪开合、动作和反馈话题已经
> 实际观察到；停止重复空载格式试录，以第一条完整人工演示同时验证采集链路。
> 电脑只记录，不发送 CAN 控制帧。当前只用左侧，右侧不做真实运动。

## 1. 本轮交付物

录一次完整的“靠近香蕉、夹住、搬运、放进空盒、松开”。保存三路 RGB、实际观测反馈、
固件动作目标、原始 CAN 和回合标签。用原始时间戳离线整理 JPEG、七维状态/动作及候选清单。
实体归属和夹爪零点仍待确认，因此本轮是候选演示，不自动标记为可训练数据。

本轮使用已验证过的 `5 Hz` 相机数据流，动作与反馈仍保留接收器的原始发布频率。
这是第一条候选演示的采集配置，后续模型节拍需另行固定；不插值制造额外视觉帧。
不用 LabelMe，不要求独立检测器。所有操作沿用学长已验证的左侧直连方式。

## 2. 终端安排

| 终端 | 操作 |
| --- | --- |
| 06-相机 | 继续运行 |
| 07-训练数据流 | 停掉原 `2 Hz` 节点，在同一个终端启动唯一 `5 Hz` 节点 |
| 12-直连数据只读 | 继续运行，记录动作和反馈；程序没有发送功能 |
| 08-入盒演示录包 | 复用已退出的录包终端，录制新回合 |
| 11-回合标签 | 复用标签终端，发布开始、结果、结束 |
| 02-只读检查 | 回合结束后做离线校验与候选数据整理 |

先把香蕉模型和空盒放在左从臂已知可达范围内，保持机械臂周围清空，急停可达。
不要为了采集跨过关节限位、强掰锁住的关节或临时重配置主从角色。

## 3. 更换图像采集频率

在终端 07 按 `Ctrl-C` 停止旧节点，再粘贴：

```bash
cd ~/piper_tjp
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 run piper piper_dataset_streams --ros-args -p output_rate:=5.0 -p jpeg_quality:=85 -p enable_depth:=false
```

保持运行，不在另一个终端重复启动。终端 06 与 12 不需要重启。
后续演示只转发 RGB；彩色输出使用 `RELIABLE / depth=30`，输入仍兼容相机的 best-effort。
同一路的编码与发布保持加锁，拒绝重复或倒退的源时间戳。这些软件改进尚未以新真实演示
确认对缺帧的改善程度，不据此宣称第三视角间隙根因已解决。

## 4. 录制第一条完整演示

在终端 08 执行。目录存在时不覆盖，换回合编号。

```bash
cd ~/piper_tjp
source /opt/ros/humble/setup.bash
source install/setup.bash
PIPER_DIRECT_EPISODE_DIR="data/2026-10-14/banana_into_box/scene-a05/banana-direct-a05-001"
if [ -e "$PIPER_DIRECT_EPISODE_DIR" ]; then
  echo "目录已存在，停止；不要覆盖"
else
  mkdir -p data/2026-10-14/banana_into_box/scene-a05
  ros2 bag record \
    --compression-mode file \
    --compression-format zstd \
    --max-cache-size 268435456 \
    -o "$PIPER_DIRECT_EPISODE_DIR" \
    /dataset/camera_gripper_left/color/image_jpeg \
    /dataset/camera_gripper_right/color/image_jpeg \
    /dataset/camera_third_view/color/image_jpeg \
    /dataset/can_left/feedback_observed \
    /dataset/can_left/action_target \
    /dataset/can_left/raw_can \
    /dataset/episode_marker
fi
```

看到 `Recording...` 后，在终端 11 发布开始：

```bash
cd ~/piper_tjp
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 run piper piper_episode_marker start --episode-id banana-direct-a05-001 --task banana_into_box --scene-id scene-a05 --attempt 1 --operator mips
```

现在人工操作左主臂，完成从臂抓取、搬运、放入、松开全过程。不要中途切换控制模式，
不用电脑节点辅助控制。香蕉完全在盒内、盒子未倾覆且静止至少 3 秒时，才标成功：

```bash
ros2 run piper piper_episode_marker success --episode-id banana-direct-a05-001 --task banana_into_box --scene-id scene-a05 --attempt 1 --operator mips --note "左侧固件直连人工演示，香蕉已入盒并松开，稳定3秒"
ros2 run piper piper_episode_marker end --episode-id banana-direct-a05-001 --task banana_into_box --scene-id scene-a05 --attempt 1 --operator mips
```

若失败，只发以下失败和结束两条，不发成功；如实写明原因，保留原包：

```bash
ros2 run piper piper_episode_marker failure --episode-id banana-direct-a05-001 --task banana_into_box --scene-id scene-a05 --attempt 1 --operator mips --note "本次未完成入盒，具体原因另记"
ros2 run piper piper_episode_marker end --episode-id banana-direct-a05-001 --task banana_into_box --scene-id scene-a05 --attempt 1 --operator mips
```

然后在终端 08 按 `Ctrl-C`，等 `Recording stopped`。成功/失败以真实结果为准，
不能把人工直接把香蕉摆进盒子算成机械臂成功。

## 5. 离线检查与转换

工具均不访问 CAN。在终端 02 执行：

```bash
cd ~/piper_tjp
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 bag info data/2026-10-14/banana_into_box/scene-a05/banana-direct-a05-001
ros2 run piper piper_dataset_validate data/2026-10-14/banana_into_box/scene-a05/banana-direct-a05-001 --mode direct_demonstration --write-manifest
ros2 run piper piper_direct_dataset_prepare data/2026-10-14/banana_into_box/scene-a05/banana-direct-a05-001 data/2026-10-14/banana_into_box/scene-a05/banana-direct-a05-001-candidate --fps 5
```

`direct_demonstration` 检查七路话题与 `start`、结果、`end` 各三条标签。
`valid=true` 只表示这一级结构检查通过。整理器进一步检查七维名称/单位约定、时间戳严格递增、
动作/反馈原始 ID 齐全；裁取开始至结果标签的时间段，避免把结束后的收尾动作混入成功演示。

输出目录必须不存在，包含：

```text
images/left_wrist/          # 对齐后的原始 JPEG
images/right_wrist/
images/third_view/
aligned_candidate.npz      # N×7 状态/动作、图像路径、源时间、网格时间和连续片段 ID
candidate_manifest.json    # 质量统计、丢弃原因和待确认项
```

以第三视角源时间为对齐点，各路只取此前最近样本；图像最大年龄 `250 ms`，状态/动作
最大年龄 `100 ms`。不取未来状态、不插值、不用反馈伪造动作，保留负夹爪行程。
样本少于 10、有效帧率低于请求值的 80% 或内部出现较大时间间隙时，`format_valid=false`。
失败回合可导出供排障，不作为默认成功模仿数据。处理失败的候选目录保留，不自动删除原始资料。

当前 `training_ready=false` 始终保留：这只是可检查的中间格式，尚未直接导入 LeRobot 或 openpi。
确认反馈实体、夹爪零点与训练/执行动作映射后，再固定模型适配和数据版本。

新版 `piper_pi05_candidate_v2` 在任何一个采样网格缺失处切段，不把整包直接压成等间隔序列。
清单列出连续片段与不同动作序列长度的完整窗口数量；训练取序列时必须保持在同一段内，
不跨空档、不补末尾。片段只继承原回合结果用于追溯，不将每个片段都标为完整任务成功。

首条保留演示 `banana-direct-a05-002` 的 v2 输出另存在
`banana-direct-a05-002-candidate-v2/`，原包和旧候选均未覆盖。139 个样本分成 17 段；
序列长 10 有 48 个完整窗口，长 50 为 0。openpi 的默认序列长度为 50，当前不足以按该默认
直接训练，不为使数据通过而擅自更改模型长度或放宽缺帧标准。下一条完整演示沿用新的 RGB 采集参数。

## 6. 收尾与续接

本轮只录一条演示，先离线看质量，不要求重复做空载格式检查。明确发现缺帧、掉线或
标记错误时，才针对问题处理。代码和文档进 Git；原包、图像、NPZ 在 `data/` 中本地保存。
下一步先阅读本文件及 `PIPER_PI05_TRAINING_PLAN.md`，以真实已完成的演示和离线报告继续。
