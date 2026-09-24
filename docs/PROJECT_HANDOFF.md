# 项目交接与复工手册

> **用途：** 本文是工作区 `~/piper_tjp` 的复工入口。恢复项目时先读本文，再读 [CAN 映射](PI05_CAN_MAPPING.md) 和[遥操作操作手册](PIPER_TELEOP.md)。本文记录的是 2026-09-24 在本实验机上实际验证的状态。

## 一分钟回忆：项目到了哪里

项目运行在 ROS 2 Humble，当前使用自己的 fork 的 `humble` 分支。四台 Piper 的主从遥操作已完成实际验证：左、右两组均能跟随，并在会话结束后自动回到 follower 的启动姿态。

已验证的默认组合：

| 项目 | 当前值 |
| --- | --- |
| 对齐、回位曲线 | 五次最小 jerk |
| 控制频率 | 50 Hz |
| 滤波 | 一阶低通，`tau=0.02 s` |
| 死区 | `0.4 deg` |
| 死区速度门限 | `1.0 deg/s` |
| 平滑级带宽 | `15 rad/s` |
| 通常遥操时长 | `30 s` |

这套组合在左臂真机上表现为静止基本不抖、小幅操作延迟基本不可感知；右臂也已完成“跟随 → 自动回位”验证。

**操作纪律：** 前 4 秒是对齐阶段，必须不碰 master。等终端打印“进入绝对跟随”后，先小幅、低速拖动。对齐中移动 master 会触发重新对齐，表现得像“没有跟上”，不是通信故障。

## 当前唯一有效的硬件映射

| 物理角色 | SocketCAN 接口 | USB 端口 |
| --- | --- | --- |
| 左主臂 | `can_ml` | `1-11:1.0` |
| 左从臂 | `can_fl` | `1-13:1.0` |
| 右主臂 | `can_mr` | `1-4:1.0` |
| 右从臂 | `can_fr` | `1-2:1.0` |

这个关系已通过逐臂拖动与关节角度监视确认。权威配置是 `config/pi05_can_map.json`；`can_muti_activate.sh`、双从臂 launch 默认值与遥操显示也已同步。

**不要**按 `can0`、`can1` 等 Linux 枚举顺序推断角色。电脑重启、换 USB 插口或重新插拔适配器后，必须先做下面的硬件检查。

## 放假前安全收尾

确保 follower 已回位、没有遥操程序运行后，在任一已 source 的终端执行：

```bash
ros2 service call /enable_srv_left piper_msgs/srv/Enable "{enable_request: false}"
ros2 service call /enable_srv_right piper_msgs/srv/Enable "{enable_request: false}"
```

节点还在运行时，确认两台 follower 都已失能：

```bash
ros2 topic echo /arm_enable_status_left --once
ros2 topic echo /arm_enable_status_right --once
```

两边必须为 `all_enabled: false`、`state: 1`。再依次在所有节点终端按 `Ctrl-C`，包括左主臂、左从臂、右主臂、右从臂节点。**不要**在遥操或自动回位进行时直接关闭终端。

```bash
ps -ef | grep -E 'piper_(single_ctrl|teleop)' | grep -v grep || echo "没有 Piper 控制进程"
```

确认机械臂有稳定支撑、工作空间已清空、急停可达后，按实验室批准的流程关闭机械臂电源与主机。节点退出不等价于失能，所以要先失能、确认，再退出节点。

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

预期能看到四路 `can_ml`、`can_fl`、`can_mr`、`can_fr`，状态均为 `UP`。某路存在但为 `DOWN` 时，必须先停掉所有 ROS 控制节点，再重新拉起；例如右主臂：

```bash
sudo ip link set can_mr down
sudo ip link set can_mr type can bitrate 1000000
sudo ip link set can_mr up
ip -details link show can_mr | grep -E 'state|can state|bitrate'
```

预期是 `state UP`、`can state ERROR-ACTIVE`、`bitrate 1000000`。若 `can_mr` 完全不存在，优先检查右主臂的 USB `1-4` 连接。它曾发生过一次短暂 USB 错误 `-71`；重插后恢复。接口缺失或反复掉线时，不要开始遥操。

## 最快的左臂复验

每个“节点”使用一个独立终端；节点运行期间不要在该终端继续输入命令。

### 终端 1：左主臂节点

```bash
cd ~/piper_tjp
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch piper start_single_piper.launch.py \
  can_port:=can_ml auto_enable:=false gripper_exist:=false
```

### 终端 2：左从臂节点

```bash
cd ~/piper_tjp
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 run piper piper_single_ctrl \
  --ros-args \
  -r __node:=piper_left_ctrl_node \
  -p can_port:=can_fl \
  -p auto_enable:=false \
  -p gripper_exist:=false \
  -p gripper_val_mutiple:=1 \
  -r pos_cmd:=/pos_cmd_left \
  -r joint_ctrl_single:=/joint_ctrl_cmd_left \
  -r enable_flag:=/enable_flag_left \
  -r enable_srv:=/enable_srv_left \
  -r joint_states_single:=/joint_states_left \
  -r joint_states_feedback:=/joint_left \
  -r joint_ctrl:=/joint_states_ctrl_left \
  -r arm_status:=/arm_status_left \
  -r arm_enable_status:=/arm_enable_status_left \
  -r end_pose:=/end_pose_left \
  -r end_pose_stamped:=/end_pose_stamped_left
```

### 终端 3：使能左从臂并确认

```bash
cd ~/piper_tjp
source /opt/ros/humble/setup.bash
source install/setup.bash

ros2 topic echo /arm_enable_status --once
ros2 topic echo /arm_enable_status_left --once
ros2 service call /enable_srv_left piper_msgs/srv/Enable "{enable_request: true}"
ros2 topic echo /arm_enable_status_left --once
```

确认主臂为 `can_ml` 且 `all_enabled: false`；从臂为 `can_fl`，使能后 `all_enabled: true`。

### 终端 4：左臂实际遥操

```bash
cd ~/piper_tjp
source /opt/ros/humble/setup.bash
source install/setup.bash

ros2 run piper piper_teleop \
  --side left \
  --master-topic /joint_states_single \
  --duration 30 \
  --enable
```

结束、或第一次 `Ctrl-C` 后都会自动回位；回位期间第二次 `Ctrl-C` 才是立即停止。回位完成后立即失能：

```bash
ros2 service call /enable_srv_left piper_msgs/srv/Enable "{enable_request: false}"
```

## 右臂复验要点

右臂已验证的节点和话题：

| 角色 | 节点 | 关键话题 / 服务 |
| --- | --- | --- |
| 右主臂 | `/piper_master_right_ctrl_node` | `/joint_states_master_right` |
| 右从臂 | `/piper_right_ctrl_node` | `/joint_ctrl_cmd_right`、`/enable_srv_right` |

实际遥操命令：

```bash
ros2 run piper piper_teleop \
  --side right \
  --master-topic /joint_states_master_right \
  --duration 30 \
  --enable
```

开始前先让右从臂 `can_fr` 使能，右主臂 `can_mr` 保持失能。推荐先去掉 `--enable` 干跑，确认输出是：

```text
follower 目标话题：/joint_ctrl_cmd_right（follower_right (can_fr)）
master 角度话题  ：/joint_states_master_right
```

结束后：

```bash
ros2 service call /enable_srv_right piper_msgs/srv/Enable "{enable_request: false}"
```

## 快速故障判断

| 现象 | 优先检查 | 不要做什么 |
| --- | --- | --- |
| follower 不动 | 对应 `/arm_enable_status_*` 是否为 `all_enabled: true`；遥操命令是否带 `--enable` | 未确认接口就反复换 CAN 名称 |
| “拒绝：整臂未确认使能” | 只使能对应 follower，再读状态 | 使能 master |
| 对齐不断重启 | 等 4 秒对齐完成后再移动 master | 对齐中持续拖动 master |
| `can_mr` 不存在或 DOWN | 停节点，检查 USB `1-4`，必要时重新拉起链路 | 节点运行时重配 CAN |
| 想确认实体映射 | 全部失能后运行 `ros2 run piper piper_joint_watch`，逐台拖动 | 靠接口名猜左右 |
| 想紧急停止 | 第一次 `Ctrl-C` 等回位；回位中第二次才立即停 | 回位途中拔线或关终端 |

## Git 续接与记录

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
- [x] 四臂 CAN 映射已经确认并固定。
- [x] 左臂遥操已完成防抖、低延迟参数的真机验证。
- [x] 左、右两组实际遥操均通过，且自动回位正常。
- [ ] 后续优化应一次只改一个参数，并在相同动作条件下记录抖动、延迟和回位轨迹。

