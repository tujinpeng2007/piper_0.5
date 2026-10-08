# 项目交接与复工手册

> **架构更新（2026-10-06）：** 当前正在使用左侧“上位机示教模式”：左主臂进入物理示教模式，
> 工作区读取主臂 `0x2C*` 反馈，并由 `piper_teach_follow` 向左从臂发送标准运动帧。
> 左侧已完成真机跟随验证；右侧已完成读取与一次发送尝试，但因 CAN 掉线而暂停。固件同总线直连模式和旧 `piper_teleop`
> 均属于历史方案，暂不混用。

> **用途：** 本文是工作区 `~/piper_tjp` 的复工入口。恢复项目时先读本文，再读[操作与指令总表](PIPER_PI05_COMMAND_REFERENCE.md)、[CAN 映射](PI05_CAN_MAPPING.md)和[遥操作操作手册](PIPER_TELEOP.md)。本文记录的是本实验机上实际验证的状态。

## 当前阶段（2026-10-06）

- 左侧上位机示教链路已打通并完成真机跟随：
  `左主臂物理示教模式 -> can_left 的 0x2C5~0x2C7 -> piper_teach_follow -> 0x151/0x155~0x157 -> 左从臂`。
- 左从臂曾出现 j1、j6 未使能；历史上曾发送 `0x471` 广播后恢复，但右侧后来出现抖动和部分使能，因此禁止所有直接、手写或循环的 `0x471` 操作。全侧软件失能工具 `piper_shared_bus_disable` 已完成代码/干跑验证，待硬件负责人确认后才可真机执行。
- 2026-10-08 只读复工检查：两条 CAN 均为 `UP / ERROR-ACTIVE / 1000000`，两侧六关节反馈均为 `DISABLED`，未发现残留控制或相机进程。
- `piper_teach_follow --send --align-seconds 4` 已完成 4 秒五次最小 jerk 对齐并实际跟随。
- 跟随节点停止后不会自动失能；本次离开前必须先确认节点已停止，再按现场流程安全收尾。
- 右侧已完成只读示教反馈确认，并曾进入发送模式；发送期间发生 `can_right` 掉线，当前只允许做只读稳定性排查。
- 三相机一键启动已修复：左 Orbbec、右 Orbbec、D455 依次错峰启动，并使用独立 launch 参数作用域；六路图像同时运行约 `29~30 Hz`。
- 相机训练数据流已验证：六路统一 `5 Hz`，三路彩色 JPEG、三路深度原始图像；`10.51s` 的
  zstd 试录为 `35.4 MiB`。下一步是补齐示教关节、夹爪状态与回合标记，尚未开始正式示教采集。
- 六路相机与主/从臂六关节状态已完成同包只读试录：`11.56s`、`36.3 MiB`；相机约 `5 Hz`，
  主/从关节各约 `50 Hz`。下一项是验证夹爪 `0x2A8` 反馈格式和任务回合标记。
- 左侧夹爪反馈已验证：主臂偏移帧 `0x2C8`、从臂帧 `0x2A8` 已发布为两路 `JointState` 中的
  `gripper`（m）。夹爪控制转发代码已有多重显式保护，但共享 CAN 影响范围未确认，禁止真机发送。
- 完整只读数据格式已验证：六路相机、主从关节/夹爪反馈和 `/dataset/episode_marker` 可录入同一
  rosbag；标签等待订阅者后，三类标签复测为 `9/9`。仍不得把右侧示教和夹爪控制视为已验证。
- 香蕉入盒与叠盒数据集规范已定义；当前只可推进 A1 的场景编号、标签和人工预录，不能采集
  真机夹取或叠盒演示。详见 [数据集规范](PIPER_BANANA_BOX_DATASET_PLAN.md)。

当前上位机示教命令：

```bash
cd ~/piper_tjp
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 run piper piper_teach_follow \
  --can-port can_left \
  --topic /joint_states_teach_shared \
  --send \
  --align-seconds 4
```

启动后前 4 秒不要触碰左主臂；看到“进入主臂绝对跟随”后再小幅拖动。未确认安全前不要加
`--send`，不要启动旧 `piper_single_ctrl` 或 `piper_teleop`。

## 一分钟回忆：项目到了哪里

项目运行在 ROS 2 Humble，当前使用自己的 fork 的 `humble` 分支。左侧上位机示教已验证；右侧已读取到示教反馈，但正式发送受 CAN 掉线异常阻断，暂缓真机动作。

左侧已验证的流程是：先确认左从臂六关节全部使能，再启动 `piper_teach_follow --send`；节点启动后前 4 秒为五次最小 jerk 对齐，必须不碰主臂，看到“进入主臂绝对跟随”后再小幅拖动。

旧的四路 ROS 主从节点、`piper_teleop` 和固件同总线直连，均保留作历史记录，不要与当前上位机示教流程混用。

## 当前有效的硬件映射

| 组别 | 主从关系 | 共用 SocketCAN 接口 | USB 端口 |
| --- | --- | --- | --- |
| 左侧 | 左主臂 + 左从臂 | `can_left` | `1-13:1.0` |
| 右侧 | 右主臂 + 右从臂 | `can_right` | `1-4:1.0` |

当前每侧两台 Piper 共用一条 CAN 总线。旧的 `can_ml`、`can_fl`、`can_mr`、`can_fr` 四接口表
只属于历史分开接线阶段，不要用于当前上位机示教。电脑重启或重新插拔适配器后，先运行
`bash find_all_can_port.sh` 确认 `can_left`、`can_right`。

## 放假前安全收尾

当前上位机示教节点停止后不会自动失能。离开前按以下顺序操作：

1. 在跟随节点终端按 `Ctrl-C`，确认程序已经退出；
2. 确认没有运动控制进程：

```bash
ps -ef | grep -E 'piper_(single_ctrl|teleop|teach_follow)' | grep -v grep || echo "没有 Piper 控制进程"
```

3. 全侧软件失能工具尚待真机验证；在硬件负责人明确确认前，不能执行其 `--apply`，也不能发送任何手写 `0x471`；
4. 确认机械臂停止、工作区清空、急停可达后，按实验室流程关闭对应机械臂物理电源，再关闭主机。

如遇异常运动，优先使用现场急停。不要在运动过程中拔 CAN 线或关闭终端。

## 回来后的硬件复工检查

### 1. 人工检查

- 四台机械臂周围无人、无工具和松散物体；急停可达。
- 电源、CAN 转接器和 USB 线没有松动。
- 初次复工先做单侧、小幅遥操；master 始终失能，靠人手拖动。

### 2. 更新和构建自己的工作区

```bash
cd ~/piper_tjp
git status --short
git fetch origin
git pull --ff-only origin humble

source /opt/ros/humble/setup.bash
colcon build --symlink-install --packages-select piper_msgs piper
source install/setup.bash
```

`git status --short` 若有输出，先不要 `pull`，先判断未提交改动。这里的 `origin` 是自己的 GitHub fork；拉取 `origin/humble` 不会改动学长的工作区。

### 3. 检查 CAN

```bash
cd ~/piper_tjp
bash find_all_can_port.sh
ip -br link show | grep -E 'can|slcan'
```

预期能看到 `can_left`、`can_right`，状态均为 `UP`。某路存在但为 `DOWN` 时，必须先停掉所有控制节点，再重新拉起；例如 `can_right`：

```bash
sudo ip link set can_right down
sudo ip link set can_right type can bitrate 1000000
sudo ip link set can_right up
ip -details link show can_right | grep -E 'state|can state|bitrate'
```

预期是 `state UP`、`can state ERROR-ACTIVE`、`bitrate 1000000`。若 `can_right` 完全不存在，优先检查右侧 CAN 转接器的 USB 连接。接口缺失或反复掉线时，不要开始遥操。

## 最快的左臂复验

前提：左主臂进入物理示教模式，左从臂已上电并确认六关节全部使能；右侧暂时断电。

### 终端 1：左臂上位机示教桥

```bash
cd ~/piper_tjp
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 run piper piper_teach_follow \
  --can-port can_left \
  --topic /joint_states_teach_shared \
  --send \
  --align-seconds 4
```

4 秒对齐期间不要触碰主臂；进入跟随后再小幅拖动。停止时按 `Ctrl-C`。

### 终端 2：左从臂只读使能检查

```bash
cd ~/piper_tjp
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 run piper piper_enable_check --port can_left --duration 3
```

该检查只读，不发送 CAN。共享总线上的 `0x471` 是广播帧，未得到明确确认前不要再次发送。

## 右臂复验要点（暂缓）

右侧已确认能读取右主臂示教反馈，但首次发送时 `can_right` 掉线。当前不要启动右侧发送节点，
也不要使用旧的右侧 `piper_teleop`；优先进行 CAN/USB 稳定性只读排查。

## 快速故障判断

| 现象 | 优先检查 | 不要做什么 |
| --- | --- | --- |
| follower 不动 | 左从臂六关节是否全部使能；是否等待 4 秒对齐完成 | 启动旧节点或重复发送广播使能帧 |
| 从臂部分使能 | 运行 `piper_enable_check --port can_left --duration 3` | 直接发送运动帧 |
| 对齐不断重启 | 等 4 秒对齐完成后再移动 master | 对齐中持续拖动 master |
| `can_right` 不存在或 DOWN | 停节点，检查右侧 USB-CAN，必要时重新拉起链路 | 节点运行时重配 CAN |
| 想确认实体映射 | 全部失能后运行 `ros2 run piper piper_joint_watch`，逐台拖动 | 靠接口名猜左右 |
| 想紧急停止 | 立即使用现场急停 | 回位途中拔线或关终端 |

## Git 续接与记录

完整的终端命名、状态检查、全臂使能/失能、上位机示教、相机和文档更新规则见
[Piper Pi05 指令与操作总表](PIPER_PI05_COMMAND_REFERENCE.md)。

每次实验开始和结束都执行：

```bash
cd ~/piper_tjp
git status --short
git log --oneline -3
```

验证通过的改动，明确列出文件再提交：

```bash
git add <明确列出的文件>
git commit -m "中文说明本次已验证内容"
git push origin humble
```

不要因为“同步”直接点 GitHub 的 **Sync fork**。需要吸收学长或上游更新时，先 `git fetch` 和比较差异，再决定是否合并。

## 当前里程碑

- [x] 自己的 fork 的 `humble` 已可独立提交。
- [x] 四台 Piper 的共享 CAN 映射已确认：左 `can_left`、右 `can_right`。
- [x] 三台相机 ROS 话题与约 30 Hz 帧率已验证。
- [x] 三相机一键启动的参数隔离、错峰顺序与六路同时运行已验证。
- [x] 六路相机训练数据流与压缩容量基线已验证（约 `5 Hz`、`11.8 GiB/h`）。
- [x] 相机、主从关节/夹爪反馈及回合标签的完整只读 rosbag 格式已验证。
- [x] 香蕉入盒与叠盒的数据集回合规范、场景划分和元数据标签格式已定义。
- [x] 左侧上位机示教读取、4 秒五次插值对齐和真机跟随已验证。
- [x] 左侧示教桥代码已提交并推送。
- [ ] 右侧上位机示教读取已确认；真机发送因 CAN 掉线暂停。
- [ ] 共享 CAN 下单臂精确使能/失能流程待官方协议或硬件人员确认；全侧受控失能工具待真机验证。
