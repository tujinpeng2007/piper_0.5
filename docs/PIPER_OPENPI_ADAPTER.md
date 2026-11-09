# Piper 到 openpi 的输入适配约定

> 2026-10-26：已实现纯离线 `piper.piper_openpi_inputs.PiperInputs`，只依赖 NumPy。
> 不加载模型、不启动 ROS、不访问 CAN、不提供动作执行接口。当前是输入格式准备，
> **不是已完成 LeRobot 转换、训练环境安装或 openpi 端到端联调**。

## 1. 字段与单位

数据在进入适配层之前，需要由数据加载器重组为以下字段：

| 输入字段 | 输出字段 | 约定 |
| --- | --- | --- |
| `images.third_view` | `image.base_0_rgb` | D455 第三视角 RGB |
| `images.left_wrist` | `image.left_wrist_0_rgb` | 左夹爪 RGB |
| `images.right_wrist` | `image.right_wrist_0_rgb` | 右夹爪 RGB；仅用相机不意味着右臂运动 |
| `state` | `state` | 七维：`joint1` 至 `joint6` 为 rad，`gripper` 为 m |
| `actions`（训练时） | `actions` | `H×7` 绝对位置目标，默认 `H=50` |
| `prompt` | `prompt` | 非空任务文本，当前为“把香蕉放入纸盒” |

三路相机必须明确齐全；缺少相机时报错，不用黑图掩盖采集缺失。全部使用真实图像，因此
`image_mask` 对应三路均为真。图像支持 `uint8` 的 RGB 或 `[0, 1]` 浮点 RGB，支持 HWC/CHW；
输出统一为 HWC `uint8`。形状同时可能解释为 HWC/CHW 时优先 HWC。
使用 OpenCV 解码 JPEG 后，调用方必须先将 BGR 转为 RGB，适配层不猜测颜色顺序。

保留七维原始单位和符号，不套用 ALOHA 的关节翻转或夹爪换算，不裁掉负行程，不复制状态为动作，
不转换为相对动作。负行程目前只是原始观测，不能作为已经验证的安全执行目标。
数据归一化、图像缩放、任务分词和模型维度填充留给后续固定版本的 openpi 管线处理。

## 2. 代码使用边界

适配类采用官方 `DataTransformFn` 的可调用对象接口，不导入 openpi，因此可先在 ROS 工作区
测试格式。后续需要在独立训练环境中安装 Piper 模块或明确其导入路径，并注册数据配置。

```python
from piper.piper_openpi_inputs import PiperInputs

# sample 由离线加载器提供，必须符合上表；这不是 ROS 消息或 CAN 命令。
model_input = PiperInputs(action_horizon=50)(sample)
```

没有 `actions` 时只转换观测，不生成动作。训练时必须由加载器先用候选的 `segment_id` 和
`grid_timestamp_ns` 选择同一连续段内的完整窗口，然后才交给适配层；仅凭图像/数组无法识别时间缺口。
不得通过跨段取样、重复尾帧、缩短序列或把不连续片段称为成功回合来绕过质量检查。
真实执行的动作限位、速度限制、失联保护和控制权切换均未在本模块实现。

## 3. 本次验证与剩余工作

- 23 项单元测试通过，覆盖相机映射、RGB 通道、七维绝对值和负夹爪值保留、非法输入拒绝，
  以及观测模式不伪造动作。
- 从 `banana-direct-a05-002-candidate-v2` 实际读取首个样本并转换：第三视角为
  `720×1280×3`，两路夹爪各为 `480×640×3`，状态为七维。未改写原包及候选。
- 139 个候选、17 段、默认 50 步完整窗口为 0 的结论不变，`training_ready=false` 不变。
- 未安装 openpi/LeRobot、下载权重或启动训练；未声称通过模型加载器/训练集成测试。

接下来用新版 RGB-only 图像流记录正常人工入盒任务，比较真实数据缺口；同时继续确认反馈实体
归属、夹爪零点与执行映射。之后固定 openpi 提交及其依赖，完成 LeRobot 导出、连续窗口加载、
按场景划分和归一化统计，再进行模型输入及训练联调。当前不发送 CAN 控制帧。

## 4. 官方接口参考

2026-10-26 对照以下官方源码；链接指向可变化的 `main`，正式训练环境仍需固定提交版本：

- [DataTransformFn、归一化、图像缩放](https://github.com/Physical-Intelligence/openpi/blob/main/src/openpi/transforms.py)。
- [自定义输入参考：LiberoInputs](https://github.com/Physical-Intelligence/openpi/blob/main/src/openpi/policies/libero_policy.py)。
- [多相机参考：AlohaInputs](https://github.com/Physical-Intelligence/openpi/blob/main/src/openpi/policies/aloha_policy.py)。
- [LeRobot 格式转换参考](https://github.com/Physical-Intelligence/openpi/blob/main/examples/aloha_real/convert_aloha_data_to_lerobot.py)。

只参考字段结构，不复用其他机器人的单位换算、动作维度或统计量。
