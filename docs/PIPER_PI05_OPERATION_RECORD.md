# Piper Pi05 操作与指令记录

> 当前实验机的复工和交接摘要。当前有效架构是 Piper 固件同总线直连主从示教；旧的
> ROS `piper_teleop` 只属于历史实验，不要和当前直连模式混用。

## 一、当前状态

- 系统：Ubuntu 22.04、ROS 2 Humble。
- 工作区：`~/piper_tjp`，分支：`humble`。
- GitHub：`tujinpeng2007/piper_0.5`。
- 左、右两组主从臂均已完成实际跟随验证。
- 三台相机均已完成 ROS 话题和约 `30 Hz` 帧率验证。

## 二、硬件映射

| 组别 | 主臂 | 从臂 | 共用接口 | USB 端口 | 波特率 |
| --- | --- | --- | --- | --- | --- |
| 左侧 | 左主臂 | 左从臂 | `can_left` | `1-13:1.0` | `1000000` |
| 右侧 | 右主臂 | 右从臂 | `can_right` | `1-4:1.0` | `1000000` |

相机映射：

| 用途 | 型号 | 序列号 | ROS 命名空间 | 配置 |
| --- | --- | --- | --- | --- |
| 左夹爪 | Orbbec Gemini 305 | `CV27561000MR` | `/camera_gripper_left` | `640x480 @ 30 Hz` |
| 右夹爪 | Orbbec Gemini 305 | `CV275610002H` | `/camera_gripper_right` | `640x480 @ 30 Hz` |
| 第三视角 | Intel RealSense D455 | `338122301303` | `/camera_third_view/D455_1` | 彩色/深度约 `30 Hz` |

配置文件：[`config/camera_map.json`](../config/camera_map.json)。

## 三、CAN 检查

```bash
cd ~/piper_tjp
bash find_all_can_port.sh
ip -br link show | grep -E 'can|slcan'
```

预期 `can_left`、`can_right` 均为 `UP`。详细检查：

```bash
for c in can_left can_right; do echo "===== $c ====="; ip -details link show "$c" | grep -E "state|can state|bitrate"; done
```

预期包含 `state UP`、`can state ERROR-ACTIVE`、`bitrate 1000000`。

## 四、直连主从模式

同侧两台 Piper 接在同一条 CAN 总线上，由固件直接完成跟随：主臂角色为 `0xFA`，
从臂角色为 `0xFC`，角色配置 CAN ID 为 `0x470`。主臂运行时发送 `0x151`、
`0x155`、`0x156`、`0x157`、`0x159`，从臂直接接收并跟随。

官方启动顺序：从臂先物理上电，等待几秒，再给主臂物理上电。[官方双臂说明](https://github.com/agilexrobotics/piper_sdk/blob/master/asserts/double_piper.MD)

日常不需要重复发送 `0xFA` / `0xFC`，也不需要启动 `piper_teleop`。

## 五、角色配置（只在重新配置时使用）

`0x470` 没有单臂目标地址。同侧另一台 Piper 必须物理断电，旧 ROS 节点和
`piper_teleop` 必须停止；先干跑，确认唯一上电设备后才加 `--apply --single-powered-arm`。

左主臂：

```bash
source /opt/ros/humble/setup.bash; source ~/piper_tjp/install/setup.bash
ros2 run piper piper_direct_role_config --can-port can_left --role master --apply --single-powered-arm
```

左从臂：

```bash
ros2 run piper piper_direct_role_config --can-port can_left --role follower --apply --single-powered-arm
```

右侧把 `can_left` 换成 `can_right`。不确定硬件状态时不要加 `--apply`。

## 六、停止和失能

旧 ROS 控制节点模式才有 `/enable_srv_left`、`/enable_srv_right`。当前直连模式不启动
这些 ROS 节点，因此 ROS `enable_srv` 不是直连模式的失能方法。

当前工作区没有经过验证的“共享 CAN 上只失能其中一台臂”命令。安全收尾：松开主臂、确认停止，
按实验室流程关闭机械臂物理电源；有危险时优先使用现场急停。

所以不是理论上只能断电，但在当前共享 CAN 硬件下，物理断电或急停是最明确、最安全的办法。

官方 SDK 有 `DisableArm()`，对应 CAN ID `0x471`，可发送全关节失能命令；但共享 CAN 上主从
两台臂都会收到广播，当前没有验证过的单臂目标地址机制，不能盲发。`0x470` 是角色配置，不是
失能命令，不要为了失能重复发送 `0xFA` 或 `0xFC`。[官方接口说明](https://github.com/agilexrobotics/piper_sdk/blob/master/asserts/V2/INTERFACE_V2.MD)

## 七、只读检查直连联动

```bash
cd ~/piper_tjp; source /opt/ros/humble/setup.bash; source install/setup.bash
ros2 run piper piper_direct_link_watch --can-port can_left --duration 15
```

右侧把 `can_left` 换成 `can_right`。该工具只接收 CAN 帧，不发送内容。

## 八、三相机一键启动

Orbbec USB 权限规则：`/etc/udev/rules.d/99-obsensor-libusb.rules`。

```bash
cd ~/piper_tjp; source /opt/ros/humble/setup.bash; source install/setup.bash
ros2 launch piper start_cameras.launch.py
```

检查话题：

```bash
ros2 topic list | grep -E 'camera_third_view|camera_gripper_left|camera_gripper_right'
```

停止相机：在启动终端按 `Ctrl-C`。相机操作不会控制 Piper 机械臂。

## 九、复工和 Git

```bash
cd ~/piper_tjp
git status --short
git fetch origin
git pull --ff-only origin humble
source /opt/ros/humble/setup.bash
colcon build --symlink-install --packages-select piper_msgs piper
source install/setup.bash
```

保存自己确认过的改动：

```bash
git add <明确列出的文件>
git commit -m "说明本次已验证内容"
git push origin humble
```

`origin` 是自己的 fork，不会修改学长仓库；`apt` 安装的系统驱动也不会进入 Git。

## 十、已验证里程碑

- [x] 左右两条共享 CAN 总线、主从角色和实际跟随。
- [x] 左右两侧检测到官方直连控制帧。
- [x] D455、左 Gemini 305、右 Gemini 305 均约 `30 Hz`。
- [x] 三相机一键启动并发布预期话题。
