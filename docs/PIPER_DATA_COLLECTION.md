# Piper Pi05 示教数据采集手册

> 当前阶段只建立相机训练数据流和短时试录，不控制机械臂。右侧上位机示教发送、共享 CAN
> 软件使能/失能仍处于暂停状态，不得因为录制数据而绕过安全限制。

## 1. 为什么不直接录制六路原始图像

2026-10-07 对六路原始图像进行了 zstd 文件压缩试录：有效录制 `6.59s`，文件大小
`417.3 MiB`，约为 `63 MiB/s`、`3.8 GiB/min`、`228 GiB/h`。本机虽有约 `851 GB`
可用空间，但该格式不适合采集大量示教回合。

因此工作区提供 `piper_dataset_streams`：

- 六路输入图像默认从 `30 Hz` 降为 `5 Hz`；
- 三路彩色图像编码为 JPEG，默认质量 `90`；
- 三路深度图像仅降频并保持原始 `Image`，由 rosbag zstd 做文件压缩；
- 保留每帧原始 ROS `header`，供后续按时间戳对齐；
- 不访问 SocketCAN，不使能、失能或控制机械臂。

## 2. 启动顺序

### 终端 06-相机

```bash
cd ~/piper_tjp
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch piper start_cameras.launch.py
```

至少等待 18 秒，确认六路原始图像话题存在。

### 终端 07-训练数据流

```bash
cd ~/piper_tjp
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 run piper piper_dataset_streams --ros-args \
  -p output_rate:=5.0 \
  -p jpeg_quality:=90
```

### 已验证的容量基线

2026-10-07 使用上述六路训练流完成 `10.51s` 试录：共 `305` 条消息，各话题
`48~52` 帧，压缩包为 `35.4 MiB`。折算约为 `3.37 MiB/s`、`202 MiB/min`、
`11.8 GiB/h`。这是当前正式示教采集前的相机容量基线；实际数据量会随场景纹理、
照明和录制的话题变化。

输出话题：

```text
/dataset/camera_gripper_left/color/image_jpeg
/dataset/camera_gripper_left/depth/image_raw
/dataset/camera_gripper_right/color/image_jpeg
/dataset/camera_gripper_right/depth/image_raw
/dataset/camera_third_view/color/image_jpeg
/dataset/camera_third_view/depth/image_raw
```

## 3. 当前验证边界

在正式采集机器人示教数据前，还必须补齐：

1. 主从夹爪开合命令的安全转发与真机验证；
2. 右侧上位机示教的安全恢复方案；
3. 三相机与机器人基座的外参标定；
4. 每个示教回合的开始、成功、失败和结束标记。

当前只能进行相机压缩流与短时 rosbag 试录，不能把它称为完整训练数据集。

## 4. 已准备的关节状态话题

`piper_teach_follow` 现在会在同一个时间戳发布两路六关节状态：

```text
/joint_states_teach_shared     # 主臂示教输入
/joint_states_follower_shared  # 从臂实际反馈
```

启动示教桥时，两个话题会自动出现；只有加入 `--send` 才会发送运动帧。后续正式采集必须把
这两路话题和六路相机话题一同录入 rosbag。若接收到官方 `0x2A8`（主臂为偏移后的 `0x2C8`）
反馈，消息会附加 `gripper`：其 `position` 为行程（m）、最后一个 `effort` 为扭矩（N·m）。
2026-10-07 已在左侧真机确认两路均出现 `gripper` 字段：主臂 `0.0177 m`、从臂
`0.0004 m`。当前仅接收和记录夹爪反馈，尚未实现或验证向从臂发送夹爪开合命令。
任务回合成功/失败标记仍待单独验证。

### 已验证的相机与关节共同试录

2026-10-07 已完成六路相机和两路关节状态的只读试录：有效时长 `11.56s`、总计 `1474`
条消息、压缩包 `36.3 MiB`。六路相机各有 `52~54` 帧（约 `5 Hz`）；
`/joint_states_teach_shared` 与 `/joint_states_follower_shared` 各有 `579` 帧（约 `50 Hz`）。
这证明相机、主臂六关节和从臂六关节可以共用 ROS 时间戳录入同一个 rosbag；夹爪与任务回合
标记尚待真机验证，因此仍不是正式训练数据集。

## 5. 夹爪跟随的安全开关（尚未真机验证）

示教桥已实现官方 `0x159` 格式的夹爪跟随编码，但默认关闭。单独加入 `--send` 只会发送六关节
运动帧，**不会**发送夹爪命令；只有同时加入 `--send-gripper`、`--gripper-max-travel-mm` 后才会在
四秒关节对齐结束后开始发送夹爪行程。该选项尚未获得真机验证，不能在未清空夹爪周围物体、未确认
从臂姿态安全时使用。

尤其要注意：`0x159` 发送在共享 `can_left`/`can_right` 总线上，当前尚未证明它能只影响从臂
夹爪。因此代码还要求显式写入 `--shared-can-gripper-risk-acknowledged`；这个参数只是防误触发，
不代表硬件风险已经消除。真机测试必须先由硬件负责人确认两台夹爪对 `0x159` 的实际行为。

未来的真机验证需要显式形如：

```bash
ros2 run piper piper_teach_follow --can-port can_left --send \
  --send-gripper --gripper-max-travel-mm <经确认的上限> \
  --gripper-effort-nm <经确认的扭矩> \
  --shared-can-gripper-risk-acknowledged
```

这里的占位参数不能猜填；在得到实际夹爪行程上限、同总线影响范围和操作者明确授权前，不执行此命令。

## 6. 回合标签工具

正式录制时，rosbag 启动后可在另一个终端发布一次标签。它只向 ROS 话题写入 JSON 文本，
不访问 CAN，不控制机械臂。一个回合必须自己选定并复用同一个 `episode_id`：

```bash
# 开始录制后立即标记回合开始
ros2 run piper piper_episode_marker start --episode-id banana-box-001

# 任务完成或失败时标记结果；note 可使用中文
ros2 run piper piper_episode_marker success --episode-id banana-box-001 --note '香蕉已放入纸盒'
ros2 run piper piper_episode_marker end --episode-id banana-box-001
```

录制命令必须加入 `/dataset/episode_marker`。离线整理时，只保留同时具备 `start`、`success` 和
`end` 的回合；失败回合不删除原始数据，但单独归档以供分析。

2026-10-07 已验证标签工具可发布并被 ROS 接收：`std_msgs/msg/String` 的 `data` 是包含
`episode_id`、`label`、`note` 与 `stamp_ns` 的 JSON 文本。

首次完整试录时三次标签理论应为 `9` 条，但 rosbag 只录到 `8` 条，原因是第一个标签发布时
rosbag 仍在发现新话题。标签工具现已改为先等待订阅者（最多 `5s`）再发送三次；若提示
“没有发现标签订阅者”，不得把该次标签当作已成功记录。

修复后使用独立 rosbag 复测，`start`、`success`、`end` 三个标签共应产生 `9` 条消息，
实际 `Count` 为 `9`，标签可靠性验证通过。

## 7. 完整只读格式验证结果

2026-10-07 已完成一次包含六路训练相机、主臂关节/夹爪反馈、从臂关节/夹爪反馈和回合标签的
完整试录：有效时长 `24.46s`、总计 `3174` 条消息、压缩包 `83.4 MiB`。相机各
`115~121` 帧，主/从状态各 `1224` 帧，回合标签 `8` 条。标签少一条的问题随后已通过“等待
订阅者”修复，并在独立复测中达到 `9/9`。

当前数据格式已具备正式示教采集所需的传感器、状态和标签结构；尚未完成的硬件前置项仍是右侧
上位机示教安全恢复，以及共享 CAN 下夹爪控制影响范围确认。
