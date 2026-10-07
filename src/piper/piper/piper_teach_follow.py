#!/usr/bin/env python3
"""Read a shifted teaching arm and optionally command its shared-bus follower.

The node is deliberately dry-run by default.  It never enables an arm and
never transmits unless ``--send`` is explicitly provided.  The receive side
uses a CAN filter for the teaching-input feedback IDs (0x2C5..0x2C7), so the
ordinary follower feedback (0x2A*) cannot be mistaken for the master.
"""

import argparse
import math
import sys
import threading
import time
from typing import Dict, Optional, Sequence

import can
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from sensor_msgs.msg import JointState


BASE_JOINT_ANGLE_IDS = {
    0x2A5: (1, 2),
    0x2A6: (3, 4),
    0x2A7: (5, 6),
}
JOINT_NAMES = ('joint1', 'joint2', 'joint3', 'joint4', 'joint5', 'joint6')
JOINT_FRAME_IDS = frozenset(BASE_JOINT_ANGLE_IDS)
GRIPPER_FEEDBACK_ID = 0x2A8
MOTION_CTRL_ID = 0x151
JOINT_CTRL_IDS = (0x155, 0x156, 0x157)
MOTION_CTRL_DATA = bytes((0x01, 0x01, 0x64, 0xAD, 0x00, 0x00, 0x00, 0x00))
RAD_PER_MILLI_DEG = 0.001 * math.pi / 180.0


def decode_joint_frame(can_id: int, data: Sequence[int], offset: int = 0x20) -> Dict[int, float]:
    """Decode one shifted teaching-input joint frame into radians."""
    joints = BASE_JOINT_ANGLE_IDS.get(can_id - offset)
    if joints is None or len(data) < 8:
        return {}
    return {
        joints[0]: int.from_bytes(bytes(data[0:4]), 'big', signed=True)
        * RAD_PER_MILLI_DEG,
        joints[1]: int.from_bytes(bytes(data[4:8]), 'big', signed=True)
        * RAD_PER_MILLI_DEG,
    }


def decode_gripper_frame(can_id: int, data: Sequence[int],
                         offset: int = 0x20) -> Optional[tuple[float, float, int]]:
    """Decode a shifted gripper frame into metres, N·m and its status code."""
    if can_id - offset != GRIPPER_FEEDBACK_ID or len(data) < 8:
        return None
    stroke_mm = int.from_bytes(bytes(data[0:4]), 'big', signed=True) * 0.001
    effort_nm = int.from_bytes(bytes(data[4:6]), 'big', signed=True) * 0.001
    return stroke_mm * 0.001, effort_nm, int(data[6])


def encode_joint_frame(joint_a: float, joint_b: float) -> bytes:
    """Encode two radian joint targets as signed 0.001-degree integers."""
    values = (
        int(round(joint_a / RAD_PER_MILLI_DEG)),
        int(round(joint_b / RAD_PER_MILLI_DEG)),
    )
    return b''.join(value.to_bytes(4, 'big', signed=True) for value in values)


def encode_gripper_frame(position_m: float, effort_nm: float) -> bytes:
    """Encode a 0x159 gripper command without changing its zero point."""
    stroke_raw = int(round(position_m * 1_000_000.0))
    effort_raw = int(round(effort_nm * 1_000.0))
    return (
        stroke_raw.to_bytes(4, 'big', signed=True)
        + effort_raw.to_bytes(2, 'big', signed=False)
        + bytes((0x01, 0x00))
    )


def minimum_jerk(progress: float) -> float:
    """Return a zero-velocity/acceleration quintic interpolation factor."""
    x = max(0.0, min(1.0, progress))
    return 10.0 * x**3 - 15.0 * x**4 + 6.0 * x**5


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='共享 CAN 上位机示教桥；默认干跑，只读不发送。',
    )
    parser.add_argument('--can-port', required=True, help='SocketCAN 接口，例如 can_left')
    parser.add_argument('--feedback-offset', type=lambda value: int(value, 0), default=0x20,
                        help='示教主臂反馈偏移，默认 0x20（2Ax -> 2Cx）')
    parser.add_argument('--topic', default='/joint_states_teach_shared',
                        help='示教主臂 ROS 话题')
    parser.add_argument('--follower-topic', default='/joint_states_follower_shared',
                        help='从臂实际关节反馈 ROS 话题')
    parser.add_argument('--rate', type=float, default=50.0, help='ROS 发布/控制频率 Hz')
    parser.add_argument('--send', action='store_true',
                        help='明确允许发送 0x151、0x155~0x157；默认不发送')
    parser.add_argument('--send-gripper', action='store_true',
                        help='额外允许发送 0x159 夹爪跟随；必须同时提供行程上限')
    parser.add_argument('--gripper-max-travel-mm', type=float, default=None,
                        help='夹爪跟随的硬上限（mm）；仅 --send-gripper 时必填，范围 (0, 100]')
    parser.add_argument('--gripper-effort-nm', type=float, default=1.0,
                        help='夹爪跟随扭矩（N·m），仅 --send-gripper 时生效，默认 1.0')
    parser.add_argument('--shared-can-gripper-risk-acknowledged', action='store_true',
                        help='确认 0x159 可能影响同总线两台臂的夹爪；仅解除误触发保护')
    parser.add_argument('--align-seconds', type=float, default=4.0,
                        help='发送前从臂对齐到主臂的五次插值时长，默认 4 秒')
    return parser


class PiperTeachFollow(Node):
    """Receive the teaching arm and optionally send targets to the follower."""

    def __init__(self, *, can_port: str, feedback_offset: int, topic: str,
                 follower_topic: str, rate: float, send: bool, send_gripper: bool,
                 gripper_max_travel_mm: Optional[float], gripper_effort_nm: float,
                 shared_can_gripper_risk_acknowledged: bool,
                 align_seconds: float,
                 bus_factory=can.Bus) -> None:
        super().__init__('piper_teach_follow')
        if rate <= 0:
            raise ValueError('rate 必须大于 0')
        if feedback_offset not in (0x10, 0x20):
            raise ValueError('feedback_offset 只能是 0x10 或 0x20')
        if align_seconds < 0:
            raise ValueError('align_seconds 不能小于 0')
        if send_gripper and not send:
            raise ValueError('--send-gripper 必须与 --send 一起使用')
        if send_gripper and gripper_max_travel_mm is None:
            raise ValueError('--send-gripper 时必须明确提供 --gripper-max-travel-mm')
        if send_gripper and not shared_can_gripper_risk_acknowledged:
            raise ValueError(
                '--send-gripper 前必须确认共享 CAN 风险；当前未验证 0x159 是否只影响从臂夹爪')
        if gripper_max_travel_mm is not None and not 0 < gripper_max_travel_mm <= 100:
            raise ValueError('gripper_max_travel_mm 必须在 (0, 100] 范围内')
        if not 0 < gripper_effort_nm <= 5:
            raise ValueError('gripper_effort_nm 必须在 (0, 5] 范围内')

        self._offset = feedback_offset
        self._send = send
        self._send_gripper = send_gripper
        self._gripper_max_travel_m = (
            gripper_max_travel_mm * 0.001
            if gripper_max_travel_mm is not None else None
        )
        self._gripper_effort_nm = gripper_effort_nm
        self._align_seconds = align_seconds
        self._master_angles: Dict[int, float] = {}
        self._follower_angles: Dict[int, float] = {}
        self._master_gripper: Optional[tuple[float, float, int]] = None
        self._follower_gripper: Optional[tuple[float, float, int]] = None
        self._align_start: Optional[float] = None
        self._align_home: Optional[list[float]] = None
        self._align_target: Optional[list[float]] = None
        self._reported_waiting = False
        self._reported_following = False
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._can_fault = threading.Event()
        self._can_fault_reason: Optional[str] = None
        self._bus = bus_factory(
            channel=can_port, interface='socketcan', receive_own_messages=False)
        receive_ids = [can_id + feedback_offset for can_id in JOINT_FRAME_IDS]
        receive_ids.append(GRIPPER_FEEDBACK_ID + feedback_offset)
        receive_ids.extend(JOINT_FRAME_IDS)
        receive_ids.append(GRIPPER_FEEDBACK_ID)
        self._bus.set_filters([
            {'can_id': can_id, 'can_mask': 0x7FF, 'extended': False}
            for can_id in sorted(set(receive_ids))
        ])
        self._master_publisher = self.create_publisher(JointState, topic, 10)
        self._follower_publisher = self.create_publisher(
            JointState, follower_topic, 10)
        self._timer = self.create_timer(1.0 / rate, self._tick)
        self._reader = threading.Thread(
            target=self._read_loop, name='piper_teach_follow_can_reader', daemon=True)
        self._reader.start()
        mode = '发送模式' if send else '干跑只读模式'
        self.get_logger().info(
            f'共享 CAN 示教桥：CAN={can_port}，主臂反馈偏移=0x{feedback_offset:02X}，{mode}')
        if send:
            self.get_logger().warn(
                f'已允许发送从臂运动帧；先用 {align_seconds:g}s 五次插值对齐，'
                '本节点不会发送 0x471 使能帧，请先确认从臂已安全使能')
            if send_gripper:
                self.get_logger().warn(
                    '已允许夹爪跟随：只会在关节对齐完成后发送 0x159；'
                    f'行程上限 {gripper_max_travel_mm:g} mm，扭矩 {gripper_effort_nm:g} N·m')
        else:
            self.get_logger().info('不会发送任何 CAN 帧，也不会使能、失能或移动机械臂')

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            try:
                message = self._bus.recv(timeout=0.2)
            except (can.CanError, OSError) as exc:
                self._record_can_fault(exc)
                return
            if message is None or message.is_error_frame:
                continue
            master = decode_joint_frame(
                message.arbitration_id, message.data, self._offset)
            follower = decode_joint_frame(
                message.arbitration_id, message.data, 0)
            master_gripper = decode_gripper_frame(
                message.arbitration_id, message.data, self._offset)
            follower_gripper = decode_gripper_frame(
                message.arbitration_id, message.data, 0)
            with self._lock:
                if master:
                    self._master_angles.update(master)
                if follower:
                    self._follower_angles.update(follower)
                if master_gripper is not None:
                    self._master_gripper = master_gripper
                if follower_gripper is not None:
                    self._follower_gripper = follower_gripper

    def _record_can_fault(self, exc: Exception) -> None:
        """Latch a CAN fault and fail closed instead of sending further motion."""
        if self._can_fault.is_set():
            return
        self._can_fault_reason = str(exc)
        self._can_fault.set()
        self.get_logger().error(
            f'CAN 通信故障，已停止发送运动帧：{self._can_fault_reason}')

    def _snapshots(self) -> tuple[
            Optional[list[float]], Optional[list[float]],
            Optional[tuple[float, float, int]], Optional[tuple[float, float, int]]]:
        with self._lock:
            master = None
            follower = None
            if len(self._master_angles) == len(JOINT_NAMES):
                master = [self._master_angles[joint] for joint in range(1, 7)]
            if len(self._follower_angles) == len(JOINT_NAMES):
                follower = [self._follower_angles[joint] for joint in range(1, 7)]
            return master, follower, self._master_gripper, self._follower_gripper

    @staticmethod
    def _joint_state(positions: list[float], gripper: Optional[tuple[float, float, int]],
                     stamp) -> JointState:
        """Build six-joint feedback and append gripper travel when available."""
        message = JointState()
        message.header.stamp = stamp
        message.name = list(JOINT_NAMES)
        message.position = list(positions)
        if gripper is not None:
            message.name.append('gripper')
            message.position.append(gripper[0])
            message.effort = [0.0] * len(JOINT_NAMES) + [gripper[1]]
        return message

    def _send_targets(self, positions: list[float]) -> None:
        if self._can_fault.is_set():
            return
        try:
            self._bus.send(can.Message(
                arbitration_id=MOTION_CTRL_ID,
                data=MOTION_CTRL_DATA,
                is_extended_id=False,
            ))
            for can_id, first, second in (
                (JOINT_CTRL_IDS[0], 0, 1),
                (JOINT_CTRL_IDS[1], 2, 3),
                (JOINT_CTRL_IDS[2], 4, 5),
            ):
                self._bus.send(can.Message(
                    arbitration_id=can_id,
                    data=encode_joint_frame(positions[first], positions[second]),
                    is_extended_id=False,
                ))
        except (can.CanError, OSError) as exc:
            self._record_can_fault(exc)

    def _send_gripper_target(self, position_m: float) -> None:
        """Send one bounded gripper command after joint alignment is complete."""
        if self._can_fault.is_set() or self._gripper_max_travel_m is None:
            return
        target = max(0.0, min(position_m, self._gripper_max_travel_m))
        try:
            self._bus.send(can.Message(
                arbitration_id=0x159,
                data=encode_gripper_frame(target, self._gripper_effort_nm),
                is_extended_id=False,
            ))
        except (can.CanError, OSError) as exc:
            self._record_can_fault(exc)

    def _tick(self) -> None:
        if self._can_fault.is_set():
            return
        master, follower, master_gripper, follower_gripper = self._snapshots()
        if master is None:
            return
        message = self._joint_state(
            master, master_gripper, self.get_clock().now().to_msg())
        self._master_publisher.publish(message)
        if follower is not None:
            follower_message = self._joint_state(
                follower, follower_gripper, message.header.stamp)
            self._follower_publisher.publish(follower_message)
        if not self._send:
            return
        if follower is None:
            if not self._reported_waiting:
                self.get_logger().warn('等待从臂 0x2A5~0x2A7 反馈，暂不发送运动帧')
                self._reported_waiting = True
            return
        now = time.monotonic()
        if self._align_start is None:
            self._align_start = now
            self._align_home = follower
            self._align_target = master
            self.get_logger().info(
                f'开始从臂安全对齐：{self._align_seconds:g}s 五次最小 jerk；请勿触碰主臂')
        if self._align_home is not None and self._align_target is not None:
            progress = (now - self._align_start) / self._align_seconds if self._align_seconds else 1.0
            if progress < 1.0:
                factor = minimum_jerk(progress)
                target = [
                    start + factor * (goal - start)
                    for start, goal in zip(self._align_home, self._align_target)
                ]
            else:
                target = master
                if not self._reported_following:
                    self.get_logger().info('从臂对齐完成，进入主臂绝对跟随')
                    self._reported_following = True
            self._send_targets(target)
            if progress >= 1.0 and self._send_gripper and master_gripper is not None:
                self._send_gripper_target(master_gripper[0])

    def destroy_node(self):
        self._stop.set()
        self._reader.join(timeout=1.0)
        self._bus.shutdown()
        return super().destroy_node()


def main(argv=None, bus_factory=can.Bus) -> int:
    args = _parser().parse_args(argv)
    rclpy.init(args=argv)
    node: Optional[PiperTeachFollow] = None
    try:
        node = PiperTeachFollow(
            can_port=args.can_port,
            feedback_offset=args.feedback_offset,
            topic=args.topic,
            follower_topic=args.follower_topic,
            rate=args.rate,
            send=args.send,
            send_gripper=args.send_gripper,
            gripper_max_travel_mm=args.gripper_max_travel_mm,
            gripper_effort_nm=args.gripper_effort_nm,
            shared_can_gripper_risk_acknowledged=args.shared_can_gripper_risk_acknowledged,
            align_seconds=args.align_seconds,
            bus_factory=bus_factory,
        )
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        # Ctrl-C is the normal way to stop a hardware test.
        pass
    except (can.CanError, OSError, ValueError) as exc:
        if node is not None and rclpy.ok():
            node.get_logger().error(str(exc))
        return 1
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
