# 三相机接入手册

## 当前硬件映射

| 用途 | 型号 | 序列号 | 计划 ROS 命名空间 |
| --- | --- | --- | --- |
| 左夹爪相机 | Orbbec Gemini 305 | `CV27561000MR` | `/camera_gripper_left` |
| 右夹爪相机 | Orbbec Gemini 305 | `CV275610002H` | `/camera_gripper_right` |
| 第三视角 | Intel RealSense D455 | `338122301303` | `/camera_third_view` |

完整映射保存在 [`config/camera_map.json`](../config/camera_map.json)。程序应使用序列号或
`/dev/v4l/by-id/` 稳定路径，不应使用会随插拔变化的 `/dev/video0`、`/dev/video6` 等编号。

## 当前状态

三台相机已经分别启动并验证通过：

- D455 彩色和深度均约 `30 Hz`；
- 左、右 Gemini 305 彩色和深度均约 `30 Hz`；
- 左夹爪相机通过 USB2.1 连接，固定使用 `640x480`；
- D455 的彩色图像为 `1280x720`，深度图像为 `848x480`。

2026-10-07 已再次完成三台相机一键并行运行验证，六路彩色/深度图像均约
`29~30 Hz`。启动文件使用独立 launch 参数作用域，避免 Orbbec 的同名参数污染
RealSense；同时按“左 Orbbec、右 Orbbec、D455”依次错峰启动，避免 USB 设备枚举竞争。

Orbbec 驱动的 USB `udev` 权限规则已安装到系统，位置为
`/etc/udev/rules.d/99-obsensor-libusb.rules`。

## 官方驱动选择

- 两台 Gemini 305 使用 Orbbec ROS 2 Wrapper 的 `v2-main` 分支和 `orbbec_camera`；官方支持
  ROS 2 Humble，Gemini 305 使用 `gemini_301_series.launch.py`。
- D455 使用官方 `realsense2_camera` ROS 2 Wrapper，启动入口为 `rs_launch.py`。

驱动安装属于 ROS/系统依赖变更；本机已经安装并验证。接入顺序是：先验证 D455，再验证
左、右夹爪相机，最后使用工作区的一键启动文件同时启动三台相机。

## 一键启动三台相机

先停止三个相机测试终端中正在运行的旧节点，然后在工作区终端运行：

```bash
cd ~/piper_tjp
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch piper start_cameras.launch.py
```

启动时间顺序：左夹爪相机 `T+0s`、右夹爪相机 `T+5s`、第三视角 D455 `T+10s`。
启动后至少等待 18 秒再检查话题。正常应出现以下六路图像：

```text
/camera_gripper_left/color/image_raw
/camera_gripper_left/depth/image_raw
/camera_gripper_right/color/image_raw
/camera_gripper_right/depth/image_raw
/camera_third_view/D455_1/color/image_raw
/camera_third_view/D455_1/depth/image_rect_raw
```

另开终端检查：

```bash
source /opt/ros/humble/setup.bash
ros2 topic list | grep -E 'camera_third_view|camera_gripper_left|camera_gripper_right'
```

## 安全边界

相机启动、停止和查看图像不会控制 Piper 机械臂。相机调试期间不要启动旧的
`piper_teleop` 或旧 ROS 主从控制节点；当前主从跟随继续由 Piper 固件直连完成。
