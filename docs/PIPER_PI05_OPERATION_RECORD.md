# Piper Pi05 操作与指令记录

> 当前实验机的复工和交接摘要。2026-10-14 用户报告学长已切回固件同总线直连模式。
> 当前已保留首条成功人工入盒候选演示，继续 π0.5 数据质量和格式适配；不再新增 LabelMe 标注。
> 上位机示教桥及旧 ROS `piper_teleop` 不启动，
> 不发送真实 CAN 控制帧，不推进右侧真实运动。此前示教验证结果保留为历史记录。

完整的终端命名、日常指令、全臂使能/失能、相机和 Git 操作见
[Piper Pi05 指令与操作总表](PIPER_PI05_COMMAND_REFERENCE.md)。

## 历史上位机示教与数据验证记录

- 2026-10-14 收尾：成功候选演示的 139 个样本已另存 v2，按缺失网格切为 17 段。
  图像节点已补充可靠 RGB 输出、可选关闭深度转发和源时间顺序保护；49 项相关测试通过，编译完成。
  用户尚未在终端 07 运行新版 RGB-only 命令，真实效果待下一条正常演示确认。相机、采集和控制相关
  进程只读检查无残留；机械臂电源状态未由该检查确认。本日尚未开始模型训练。
- 2026-10-14：用户转述学长要求使用 π0.5 训练。停止新增 LabelMe 标注，原检测器路线退出主线；
  现有图像和标注保留。下一项为训练实现确认、固件直连状态与动作目标只读核验、同步演示格式准备。
  详见[π0.5 微调路线](PIPER_PI05_TRAINING_PLAN.md)。本次未启动训练或发送 CAN 控制帧。
- 2026-10-14：小幅左侧直连操作的 30 秒只读监听确认关节和夹爪动作目标均存在，整段平均约
  `70 Hz`。新增无发送功能的直连数据接收器，30 项测试及编译通过；真实反馈与合成动作发布已检查。
  实际动作话题和反馈实体归属仍待核验；本次不是正式入盒演示，也未开始微调。
- 2026-10-14：用户随后实际收到了目标与反馈七维消息。停止重复空载试录，准备首条完整人工入盒演示。
  新增直连演示校验模式及离线候选数据整理器；导出状态/动作、三路 RGB 与源时间戳，保持
  `training_ready=false`，不把候选包误称为模型已可训练。本次未实际采集完整入盒演示。
- 2026-10-14：随后完成 `banana-direct-a05-002` 成功候选演示，七路完整、标签 `9/9`，
  `114.71s`、`85.2 MiB`，结构校验通过。抽查第三视角可见最终香蕉在盒内。已导出 139 个
  对齐样本；内部有 `1.235s` 数据间隙，严格质量检查未通过，尚未开始训练。原包和候选保留。
- 2026-10-14：用户报告学长改用固件直连；视觉数据链路继续沿用。尚未重新核验角色、反馈偏移
  或夹爪直连行为，不据此宣称自主入盒已可运行。A2 已有 4 张 LabelMe 标注，下一步补充独立摆放与光照。
- 2026-10-14：新增 `scene-a04` 盒外香蕉静态场景，录包 `48.52s`、`62.0 MiB`，六路相机
  约 `2 Hz`、标签 `9/9`，静态校验通过；第三视角已导出 6 张，第 3 张轮廓清晰，路线调整后不再要求人工标注。

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
  两路关节状态各约 `50 Hz`。该次历史试录尚未接入夹爪反馈与回合标签，后续已分别补齐格式验证。
- 左侧主/从臂夹爪 `0x2C8`/`0x2A8` 反馈已真机验证并写入两路 `JointState` 的 `gripper`
  字段；夹爪跟随编码已实现为多重显式开关，但共享 CAN 影响范围尚未确认，禁止真机发送。
- 完整只读数据包已验证：六路训练相机、两路主从关节/夹爪反馈及回合标签可共同录制；标签工具
  修复订阅发现竞争后，`start`/`success`/`end` 复测达到 `9/9` 条。
- 2026-10-08：新增 `piper_shared_bus_disable`，复用原版 SDK 的失能调用顺序；已完成单元测试、
  编译和无发送预演，未执行真机 `--apply`。复工只读检查确认左右两条总线均为六关节 `DISABLED`。
- 2026-10-08：已定义香蕉入盒阶段的数据集回合规范；回合标签新增任务、场景、尝试编号和操作者
  元数据。夹爪跟随尚未真机验证，因此当前只允许场景/标签准备与只读预录。
- 2026-10-08：完成 `banana-a01-001` 静态场景预录，六路相机约 `5 Hz`、标签 `9/9`；全程四台臂
  失能、未启动示教桥。该包只验证数据流程，不进入动作训练集。
- 2026-10-09：项目小目标调整为“识别香蕉和纸盒，并将一个香蕉放入纸盒”。新增离线图像导出器；
  从 `banana-a01-001` 的第三视角导出 `78` 张待标注 JPEG 和 COCO 标注骨架。抽查发现香蕉已在盒内，
  因而该包只用于识别流程，后续需补采香蕉在盒外与空盒静态场景。
- 2026-10-12：补录 `scene-a02` 空盒和 `scene-a03` 盒外香蕉，两包六路相机及 9 条标签均通过
  静态校验（`valid=true`）；各导出 6 张第三视角图。LabelMe 人工标注已保存并核查：盒内
  2 张、空盒 1 张、盒外香蕉 1 张。`data/` 被 Git 忽略；COCO 文件仍是空骨架，尚无训练好的
  识别模型。下次先扩充独立摆放和光照，再整理标注与离线评测。
- 2026-10-08：左主夹爪只读手动观测约为 `-1.4~55.3 mm`。左从夹爪收到一次 `0.5 mm`、`0.1 N·m`
  的 `0x159` 位置探测后，反馈由 `0x00` 变为 `0x40`（驱动使能），位置未见可分辨变化；随后一次
  官方 `0x02` 失能/清错使左从稳定回到 `0x00`。左主没有随从臂失能，且出现锁定、无法手动拖动；
  在静止并有支撑时物理断电重连后锁定消除。重连后的只读检查确认左侧六关节均 `DISABLED`、主从
  两把夹爪均 `0x00` 失能。该结果不构成夹爪开合或抓取功能验证，禁止重复发送位置探测。

历史左侧上位机示教复验命令（当前不执行）：

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

- 当前主线：用户报告已切回固件直连；项目小目标为“识别香蕉和纸盒并将香蕉放入盒内”。
  当前优先离线视觉识别；右侧仅允许进行 CAN/USB 和示教反馈的只读排查。
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

## 四、固件直连主从模式（当前由学长配置，本节参数为既往记录）

同侧两台 Piper 接在同一条 CAN 总线上，由固件直接完成跟随：主臂角色为 `0xFA`，
从臂角色为 `0xFC`，角色配置 CAN ID 为 `0x470`。主臂运行时发送 `0x151`、
`0x155`、`0x156`、`0x157`、`0x159`，从臂直接接收并跟随。

官方启动顺序：从臂先物理上电，等待几秒，再给主臂物理上电。[官方双臂说明](https://github.com/agilexrobotics/piper_sdk/blob/master/asserts/double_piper.MD)

日常不需要重复发送 `0xFA` / `0xFC`，也不需要启动 `piper_teleop`。

## 五、历史角色配置（当前 A2 不执行）

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
