# 同总线直连主从操作手册

> 本文是当前实验机的主从臂入口。当前主从跟随由 Piper 固件在同一条 CAN 总线上直接完成，
> 不使用旧的 `piper_teleop` 主机软件桥接。

## 当前接口映射

| 组别 | 共用 CAN 接口 | USB 端口 |
| --- | --- | --- |
| 左侧主从臂 | `can_left` | `1-13:1.0` |
| 右侧主从臂 | `can_right` | `1-4:1.0` |

两条接口均已确认是 1 Mbps、`UP`、`ERROR-ACTIVE`。每条总线均能抓到两台 Piper 的基础反馈，
说明同侧两台臂共用该 CAN 总线。

工作区内当前架构的唯一映射记录是
[`config/direct_can_bus_map.json`](../config/direct_can_bus_map.json)。旧的
`config/pi05_can_map.json` 仅保留作四接口历史记录，不能用于本机。

接口命名或激活只由 `can_config.sh` / `can_muti_activate.sh` 完成；二者当前都记录为
`can_left`（USB `1-13:1.0`）和 `can_right`（USB `1-4:1.0`）。它们不负责主从角色配置。

## 使用方式

当前工作区已完成左右两侧主臂/从臂角色配置，并已分别通过实际跟随测试。固件直连模式下：

1. 不启动 `piper_teleop`，也不启动旧的双 CAN ROS 控制节点。
2. 按官方顺序先给从臂上电、再给主臂上电，等待数秒。
3. 主机不发实时位置指令；手动拖动已配置的主臂即为遥操作。
4. 需要观察通信时，仅运行只读监视工具。

官方 SDK 的直连模式中，主臂在同一总线上发送 `0x151`、`0x155`～`0x157`、`0x159` 控制帧，
从臂直接接收并跟随。参考：[官方双臂说明](https://github.com/agilexrobotics/piper_sdk/blob/master/asserts/double_piper.MD)。

## 左臂只读联动检查

首次使用、重新插拔 CAN 或怀疑没有跟随时，先在普通终端构建并运行：

```bash
cd ~/piper_tjp
source /opt/ros/humble/setup.bash
colcon build --symlink-install --packages-select piper
source install/setup.bash

ros2 run piper piper_direct_link_watch --can-port can_left --duration 15
```

该工具只调用 CAN 接收接口，不发送任何 CAN 帧。现场在确认主臂、工作空间清空且急停可达后，
小幅拖动主臂：

- 输出出现 `0x151`、`0x155`～`0x157`、`0x159`，表示检测到官方联动控制帧；
- 同时从臂跟随，表示左侧直连遥操作正常；
- 没有控制帧或从臂不动时，停止拖动，不要使用旧 `piper_teleop` 兜底。

右侧检查只需将接口改为 `can_right`。

## 当前验证结果

| 组别 | 主臂 | 从臂 | 配置结果 | 实际验证 |
| --- | --- | --- | --- | --- |
| 左侧 | `0xFA` | `0xFC` | 已完成 | 主臂拖动时从臂跟随，监听到 `0x151`、`0x155`～`0x157`、`0x159` |
| 右侧 | `0xFA` | `0xFC` | 已完成 | 主臂拖动时从臂跟随，监听到官方联动控制帧 |

角色配置已经保存在两组机械臂的控制器中。日常使用只需按“从臂先上电、主臂后上电”的顺序，
不需要重复发送 `0xFA` / `0xFC`。

## 如何判读“没有联动帧”

官方示例把主臂设为 `MasterSlaveConfig(0xFA, 0, 0, 0)`，从臂设为
`MasterSlaveConfig(0xFC, 0, 0, 0)`。其中三个 `0` 表示不使用 CAN ID 偏移，因此即使
主从角色已写入，基础反馈仍可能保持 `0x2A*`；不能仅因没有 `0x2B*` / `0x2C*` 就断定
角色未配置。

但在两台均已按“从臂先上电、主臂后上电”启动后，拖动主臂仍完全没有
`0x151`、`0x155`～`0x157`、`0x159`，表示**当前没有处于可用的固件直连输出状态**。
这可能是角色从未配置、配置未保存/未生效，或现场硬件状态不同；不能用旧 ROS 遥操作替代。

## 单臂上电时配置角色

`0x470` 配置帧不带单臂目标地址；两台共享总线的 Piper 同时上电时不能发送它。不过，只要
同侧两台臂可分别物理断电/上电，就不需要增加 USB-CAN 或改动现有 CAN 走线：仅让待配置的
那一台上电，另一台保持断电。

`piper_direct_role_config` 默认干跑，只打印将发送的官方帧；必须同时给出 `--apply` 与
`--single-powered-arm` 才会发送一次 `0x470`。因此先运行干跑核对输出，再执行实际写入。

左侧的顺序为：两台左臂断电 → 仅左主臂上电并写入 `master` → 左主臂断电 → 仅左从臂上电
并写入 `follower` → 两台断电 → 左从臂先上电、左主臂后上电 → 用本手册的只读监听工具验证。

主臂干跑示例：

```bash
ros2 run piper piper_direct_role_config --can-port can_left --role master
```

若输出确为 `0x470 [8] FA 00 00 00 00 00 00 00`，并已确认左从臂物理断电，实际写入使用：

```bash
ros2 run piper piper_direct_role_config \
  --can-port can_left --role master --apply --single-powered-arm
```

从臂相同，只将 `master` 改为 `follower`；其帧应为
`0x470 [8] FC 00 00 00 00 00 00 00`。若不确定哪台是主臂，或不能确定另一台已断电，停止在
干跑阶段并等待现场人员确认。

## 禁止事项

- 不要把旧的 `can_ml`、`can_fl`、`can_mr`、`can_fr` 当作当前接口名。
- 不要运行旧 `piper_teleop`、旧 ROS 双节点启动命令或旧四接口激活流程。
- 不要在两台臂已经共用 `can_left` 或 `can_right` 时发送 `MasterSlaveConfig`；该配置帧会被
  同一总线的两台臂共同接收。官方 SDK 的 `0x470` 报文没有单臂目标地址字段。

## 相机现状

三台相机已经接入并完成 ROS 话题与约 `30 Hz` 帧率验证：左夹爪
`CV27561000MR`、右夹爪 `CV275610002H`、第三视角 D455
`338122301303`。统一启动命令见
[`三相机接入手册`](CAMERA_SETUP.md) 和
[`Piper Pi05 操作与指令记录`](PIPER_PI05_OPERATION_RECORD.md)。
