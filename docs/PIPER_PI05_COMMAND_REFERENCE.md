# Piper Pi05 指令与操作总表

> 本文是当前实验机的日常操作手册。当前有效主线是“上位机示教桥”；旧的
> piper_teleop、四路独立 ROS 节点和固件直连主从模式只用于历史追溯，不要混用。
>
> 文档更新时间：2026-10-07。涉及真实机械臂的命令，执行前都要确认工作空间无人、急停可达、
> 机械臂周围没有可能被夹住的物体。

## 1. 当前硬件和接口

| 组别 | 主臂 | 从臂 | 共用 CAN | USB 端口 | 波特率 |
| --- | --- | --- | --- | --- | --- |
| 左侧 | 左主臂 | 左从臂 | can_left | 1-13:1.0 | 1000000 |
| 右侧 | 右主臂 | 右从臂 | can_right | 1-4:1.0 | 1000000 |

每条 CAN 总线上挂有同侧两台 Piper。因此，发送到 can_left 的广播命令会同时影响左主臂和
左从臂；发送到 can_right 的广播命令会同时影响右主臂和右从臂。当前没有经过验证的“只
控制同侧其中一台”的广播命令。

三台相机：

| 用途 | 设备 | 序列号 | ROS 命名空间 |
| --- | --- | --- | --- |
| 左夹爪 | Orbbec Gemini 305 | CV27561000MR | /camera_gripper_left |
| 右夹爪 | Orbbec Gemini 305 | CV275610002H | /camera_gripper_right |
| 第三视角 | Intel RealSense D455 | 338122301303 | /camera_third_view/D455_1 |

## 2. 终端命名约定

| 终端 | 用途 | 是否发送硬件命令 |
| --- | --- | --- |
| 01-复工与状态 | 同步、编译、检查进程和 CAN | 默认不发送 |
| 02-只读检查 | 检查使能状态、话题和帧率 | 不发送 |
| 03-全臂控制 | 发送全总线使能/失能命令 | 会改变硬件状态 |
| 04-左示教桥 | 左侧上位机示教 | 加 --send 后会发送运动帧 |
| 05-右示教桥 | 右侧上位机示教，尚未完成验证 | 加 --send 后会发送运动帧 |
| 06-相机 | 启动三台相机 | 不控制机械臂 |

每个 ROS 终端开始前执行：

    cd ~/piper_tjp
    source /opt/ros/humble/setup.bash
    source install/setup.bash

## 3. 每天复工流程

### 终端 01-复工与状态

先看是否有未提交改动：

    cd ~/piper_tjp
    git status -sb

如果输出中只有下面这一行，说明工作区干净：

    ## humble...origin/humble

如果出现 M、A、?? 等未提交改动，先不要执行 git pull，先保存输出并判断这些改动是否需要保留。

工作区干净时执行：

    git pull --ff-only origin humble
    source /opt/ros/humble/setup.bash
    colcon build --symlink-install --packages-select piper_msgs piper
    source install/setup.bash

确认没有旧控制进程：

    ps -ef | grep -E 'piper_(single_ctrl|teleop|teach_follow)' | grep -v grep || echo "没有控制进程"

当前主线不要启动 piper_teleop。

## 4. CAN 接口检查和恢复

### 终端 01-复工与状态

    bash find_all_can_port.sh
    ip -br link show | grep -E 'can_left|can_right'

详细检查：

    for c in can_left can_right; do
      echo "===== $c ====="
      ip -details link show "$c" | grep -E 'state|can state|bitrate'
    done

正常预期：接口为 UP，CAN 状态为 ERROR-ACTIVE，波特率为 1000000。

如果接口存在但为 DOWN，先确认没有控制进程，再执行对应接口的恢复命令。例如右侧：

    sudo ip link set can_right down
    sudo ip link set can_right type can bitrate 1000000
    sudo ip link set can_right up
    ip -details link show can_right | grep -E 'state|can state|bitrate'

如果接口完全不存在，检查 USB-CAN 转接器和 USB 线，不要开始遥操。

## 5. 四台臂状态检查

### 终端 02-只读检查

    ros2 run piper piper_enable_check --port can_left --duration 3
    ros2 run piper piper_enable_check --port can_right --duration 3

该工具是只读检查，不发送使能、失能或运动帧。

预期完全使能：

    j1=on j2=on j3=on j4=on j5=on j6=on
    verdict : ENABLED

预期完全失能：

    j1=off j2=off j3=off j4=off j5=off j6=off
    verdict : DISABLED

出现 PARTIAL、UNKNOWN、Network is down 或缺少关节反馈时，不要发送运动帧。

共享 CAN 下，同一总线上的两台臂使用相同反馈 ID；这个工具主要用于确认总线上的新鲜状态，
不能单独证明同侧具体是哪台臂上报了该状态。

## 6. 使能和失能：当前暂停直接 CAN 操作

当前共享 CAN 架构下，0x471 是广播配置帧，同侧两台臂会同时收到。更重要的是，本次右侧
真机测试中，直接重复发送 0x471 后出现了右主臂抖动和 PARTIAL（仅 j2 仍使能）。因此，
以下直接 cansend 命令当前全部暂停，不能照抄执行：

    cansend can_left 471#...
    cansend can_right 471#...

即使 cansend 返回 0，也只代表 Linux 接口接受了帧，不代表 Piper 已完成操作。当前不能把
单帧或重复发送 0x471 当作安全的全臂使能/失能方案，也不能用它单独控制同侧一台臂。

当前安全收尾方式：

1. 停止所有控制节点；
2. 让机械臂保持在有支撑的安全姿态；
3. 使用 piper_enable_check 只读确认状态；
4. 如需真正解除保持力，按实验室流程关闭对应物理电源，或由有经验的硬件人员确认官方
   失能流程后再操作。

只读检查命令：

    ros2 run piper piper_enable_check --port can_left --duration 3
    ros2 run piper piper_enable_check --port can_right --duration 3

出现 PARTIAL、UNKNOWN 或 Network is down 时，立即停止运动测试，不要继续发送 0x471。

## 7. 左侧上位机示教

当前已验证左侧链路：

    左主臂物理示教模式
      -> can_left 的 0x2C5~0x2C7
      -> piper_teach_follow
      -> 0x151、0x155~0x157
      -> 左从臂

前提：左主臂已经通过实体按钮进入示教模式；左从臂已上电并确认六关节使能；右侧暂时不做
任何运动测试。

### 终端 04-左示教桥：先干跑

不加 --send 时只读 CAN，不发送运动帧：

    ros2 run piper piper_teach_follow \
      --can-port can_left \
      --topic /joint_states_teach_left \
      --align-seconds 4

确认能读到主臂反馈后，按 Ctrl-C 停止。

### 终端 04-左示教桥：正式跟随

    ros2 run piper piper_teach_follow \
      --can-port can_left \
      --topic /joint_states_teach_left \
      --send \
      --align-seconds 4

前 4 秒是五次最小 jerk 对齐，绝对不要触碰主臂。看到“从臂对齐完成，进入主臂绝对跟随”
后，才小幅拖动主臂。

停止时只在示教桥终端按 Ctrl-C，然后检查：

    ps -ef | grep -E 'piper_(single_ctrl|teleop|teach_follow)' | grep -v grep || echo "没有控制进程"

示教桥退出不会自动失能；离开前使用终端 03-全臂控制的失能命令并复检。

如果 CAN 接收或发送发生异常，示教桥会记录 CAN 故障并停止继续发送运动帧；此时不要重启
发送模式或重复发 CAN 命令，应先按安全收尾流程处理并检查 USB-CAN 稳定性。

## 8. 右侧上位机示教（尚未完成验证）

右侧不能直接假定已经验证。确认右主臂进入实体示教模式、右从臂已安全使能、can_right 为
UP 后，先在终端 05-右示教桥做干跑：

    ros2 run piper piper_teach_follow \
      --can-port can_right \
      --topic /joint_states_teach_right \
      --align-seconds 4

确认右主臂拖动时话题有变化后，停止干跑，再正式测试：

    ros2 run piper piper_teach_follow \
      --can-port can_right \
      --topic /joint_states_teach_right \
      --send \
      --align-seconds 4

右侧第一次正式测试只做小幅动作；验证完成后，必须把本文和交接文档的“右侧尚未验证”
状态更新为实际结果。

## 9. 三台相机

### 终端 06-相机

    test -f /etc/udev/rules.d/99-obsensor-libusb.rules && echo "Orbbec udev 规则已存在"
    ros2 launch piper start_cameras.launch.py

检查话题：

    ros2 topic list | grep -E 'camera_third_view|camera_gripper_left|camera_gripper_right'

检查图像频率：

    ros2 topic hz /camera_gripper_left/color/image_raw
    ros2 topic hz /camera_gripper_right/color/image_raw
    ros2 topic hz /camera_third_view/D455_1/color/image_raw

预期约 30 Hz。停止相机时在终端 06-相机按 Ctrl-C；相机节点不控制机械臂。

## 10. 旧方案：只作历史参考

以下命令不要和当前上位机示教桥同时运行：

- ros2 run piper piper_teleop
- ros2 run piper piper_single_ctrl
- 四路独立 can_ml/can_fl/can_mr/can_fr 主从节点
- 固件 0x470 的 0xFA/0xFC 角色配置

旧 ROS 服务 /enable_srv_left、/enable_srv_right 只有在相应旧 ROS 控制节点运行时才存在。
当前共享 CAN 上位机示教流程使用 cansend 0x471，不要混用旧服务。

## 11. 安全收尾和离开实验室

1. 在示教或控制终端按 Ctrl-C。
2. 确认没有控制进程：

       ps -ef | grep -E 'piper_(single_ctrl|teleop|teach_follow)' | grep -v grep || echo "没有控制进程"

3. 在终端 03-全臂控制发送两条 FF01 失能帧。
4. 用 piper_enable_check 检查两条总线均为 DISABLED。
5. 确认机械臂停止、工作区清空、急停可达。
6. 按实验室流程关闭物理电源，再关闭电脑。

不要在机械臂运动时拔 CAN 线、拔 USB 线或直接关闭终端。异常运动时先按现场急停。

## 12. Git 保存和上传

### 终端 01-复工与状态

    cd ~/piper_tjp
    git status --short
    git diff --check
    git diff --stat

只添加自己确认过的文件：

    git add docs/PIPER_PI05_COMMAND_REFERENCE.md
    git commit -m "docs: 汇总 Piper Pi05 操作指令"
    git push origin humble

确认上传：

    git fetch origin
    git status -sb
    git log --oneline -1
    git log --oneline origin/humble -1

origin 是用户自己的 fork，不会修改学长的 GitHub 仓库或工作区。上传前确认 VS Code/Git
使用的是用户自己的 GitHub 账号。

## 13. 什么时候必须更新本文

出现以下任一情况，就要更新本文，并同时检查 docs/PROJECT_HANDOFF.md：

- CAN 接口名、USB 端口或波特率改变；
- 主从硬件接线改变；
- 角色配置、反馈 ID、控制 ID 或帧格式改变；
- 使能/失能命令经过新的真机验证；
- 右侧上位机示教首次验证完成；
- 滤波器、插值、对齐时间或安全门禁改变；
- 相机序列号、ROS 命名空间、启动方式或帧率改变；
- 新增、删除或重命名 ROS 节点、话题、服务或可执行程序；
- 发生异常并找到新的处理方法；
- 任何命令在实际硬件上的行为与本文预期不一致。

本次已记录的异常：右侧上位机示教发送过程中 can_right 曾掉线；恢复后直接重复发送 0x471
出现右主臂抖动和 PARTIAL。右侧上位机示教和共享 CAN 软件失能流程均暂不视为完成验证。

更新后应重新编译、做最小验证，并提交上传。未经真机验证的命令只能放在“待验证”小节，
不能写进“当前有效流程”。
