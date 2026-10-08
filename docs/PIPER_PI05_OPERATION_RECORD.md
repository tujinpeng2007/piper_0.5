# Piper Pi05 操作与指令记录

> 当前实验机的复工和交接摘要。当前已验证左侧上位机示教模式；右侧读取已确认、真机发送暂停。旧的
> ROS `piper_teleop` 和固件同总线直连模式均属于历史方案，不能与当前上位机示教桥混用。

完整的终端命名、日常指令、全臂使能/失能、相机和 Git 操作见
[Piper Pi05 指令与操作总表](PIPER_PI05_COMMAND_REFERENCE.md)。

## 当前上位机示教状态（2026-10-06）

- 左主臂已进入物理示教模式，示教反馈为 `0x2C5`~`0x2C7`。
- 左从臂在 `can_left` 上已确认六关节全部使能。
- 工作区新增 `piper_teach_reader` 和 `piper_teach_follow`；后者默认干跑，只有加入
  `--send` 才发送 `0x151`、`0x155`~`0x157`。
- 左侧已实际完成“4 秒五次最小 jerk 对齐 + 主臂绝对跟随”。
- 右侧已确认能读取主臂示教反馈；首次发送时 `can_right` 掉线，因此右侧真机发送暂停。
- 右侧首次上位机示教发送期间 `can_right` 掉线；恢复接口后直接重复发送 `0x471` 出现右主臂抖动和部分使能。右侧示教及共享 CAN 软件失能流程暂停验证。
- 三相机一键启动已修复参数作用域冲突和并发枚举竞争；六路彩色/深度图像同时运行均约 `29~30 Hz`。
- 三相机训练数据流已验证：三路彩色 JPEG、三路深度原始图像统一 `5 Hz`，`10.51s` 六路
  rosbag zstd 试录为 `35.4 MiB`；详见 [示教数据采集手册](PIPER_DATA_COLLECTION.md)。
- 六路相机与主/从臂六关节状态已经完成共同只读试录：`11.56s`、`36.3 MiB`；相机约 `5 Hz`，
  两路关节状态各约 `50 Hz`。当前仍未接入夹爪反馈与回合标签。
- 左侧主/从臂夹爪 `0x2C8`/`0x2A8` 反馈已真机验证并写入两路 `JointState` 的 `gripper`
  字段；夹爪跟随编码已实现为多重显式开关，但共享 CAN 影响范围尚未确认，禁止真机发送。
- 完整只读数据包已验证：六路训练相机、两路主从关节/夹爪反馈及回合标签可共同录制；标签工具
  修复订阅发现竞争后，`start`/`success`/`end` 复测达到 `9/9` 条。
- 2026-10-08：新增 `piper_shared_bus_disable`，复用原版 SDK 的失能调用顺序；已完成单元测试、
  编译和无发送预演，未执行真机 `--apply`。复工只读检查确认左右两条总线均为六关节 `DISABLED`。
- 2026-10-08：已定义香蕉入盒、叠盒的数据集回合规范；回合标签新增任务、场景、尝试编号和操作者
  元数据。夹爪跟随尚未真机验证，因此当前只允许场景/标签准备与只读预录。

左侧复验命令：

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

启动后前 4 秒不要触碰左主臂。停止节点不会自动失能；离开前先确认节点停止，再按现场流程
安全关闭机械臂。共享 CAN 上的 `0x471` 是广播帧，不能把旧的单臂 ROS 服务命令直接套用到当前架构。

## 一、当前状态

- 当前主线：左侧上位机示教桥已验证；右侧仅允许进行 CAN/USB 和示教反馈的只读排查。
- 系统：Ubuntu 22.04、ROS 2 Humble。
- 工作区：`~/piper_tjp`，分支：`humble`。
- GitHub：`tujinpeng2007/piper_0.5`。
- 左侧已完成上位机示教实际跟随验证；右侧仅完成历史固件直连跟随，尚未完成上位机示教真机发送验证。
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

## 四、历史：固件直连主从模式

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

当前工作区没有经过验证的“共享 CAN 上只失能其中一台臂”命令。官方 SDK 有 `DisableArm()`，
原版 `piper_single_ctrl` 的失能服务会调用它。当前工作区将这个官方调用封装为
`piper_shared_bus_disable`：默认预演，实际执行需要显式确认机械臂有支撑和理解共享总线广播范围，
每侧只执行一次并自动只读复检。该工具目前只完成代码、单元测试和无发送预演；尚待硬件负责人
确认当前共享 CAN 接线下的真机行为。

因此，不是理论上只能断电；在工具经硬件负责人确认并完成真机验证后，可用它让同侧两台臂软件
失能。此前，物理断电或急停仍是唯一已验证的收尾方式。直接 `cansend 0x471`、循环发送或试图
用它单独控制同侧一台臂仍然禁止。`0x470` 是角色配置，不是失能命令，不要为了失能重复发送
`0xFA` 或 `0xFC`。[官方接口说明](https://github.com/agilexrobotics/piper_sdk/blob/master/asserts/V2/INTERFACE_V2.MD)

## 七、历史：只读检查固件直连联动

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

- [x] 左侧上位机示教读取、4 秒五次插值对齐和实际跟随。
- [x] 左右两条共享 CAN 总线及历史固件直连角色已记录。
- [ ] 右侧上位机示教读取已确认；真机发送因 CAN 掉线暂停。
- [x] D455、左 Gemini 305、右 Gemini 305 均约 `30 Hz`。
- [x] 三相机一键启动并发布预期话题。
- [x] 三相机参数隔离、错峰启动及六路同时约 `29~30 Hz` 已验证。
