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


def encode_joint_frame(joint_a: float, joint_b: float) -> bytes:
    """Encode two radian joint targets as signed 0.001-degree integers."""
    values = (
        int(round(joint_a / RAD_PER_MILLI_DEG)),
        int(round(joint_b / RAD_PER_MILLI_DEG)),
    )
    return b''.join(value.to_bytes(4, 'big', signed=True) for value in values)


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
    parser.add_argument('--rate', type=float, default=50.0, help='ROS 发布/控制频率 Hz')
    parser.add_argument('--send', action='store_true',
                        help='明确允许发送 0x151、0x155~0x157；默认不发送')
    parser.add_argument('--align-seconds', type=float, default=4.0,
                        help='发送前从臂对齐到主臂的五次插值时长，默认 4 秒')
    return parser


class PiperTeachFollow(Node):
    """Receive the teaching arm and optionally send targets to the follower."""

    def __init__(self, *, can_port: str, feedback_offset: int, topic: str,
                 rate: float, send: bool, align_seconds: float,
                 bus_factory=can.Bus) -> None:
        super().__init__('piper_teach_follow')
        if rate <= 0:
            raise ValueError('rate 必须大于 0')
        if feedback_offset not in (0x10, 0x20):
            raise ValueError('feedback_offset 只能是 0x10 或 0x20')
        if align_seconds < 0:
            raise ValueError('align_seconds 不能小于 0')

        self._offset = feedback_offset
        self._send = send
        self._align_seconds = align_seconds
        self._master_angles: Dict[int, float] = {}
        self._follower_angles: Dict[int, float] = {}
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
        receive_ids.extend(JOINT_FRAME_IDS)
        self._bus.set_filters([
            {'can_id': can_id, 'can_mask': 0x7FF, 'extended': False}
            for can_id in sorted(set(receive_ids))
        ])
        self._publisher = self.create_publisher(JointState, topic, 10)
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
            with self._lock:
                if master:
                    self._master_angles.update(master)
                if follower:
                    self._follower_angles.update(follower)

    def _record_can_fault(self, exc: Exception) -> None:
        """Latch a CAN fault and fail closed instead of sending further motion."""
        if self._can_fault.is_set():
            return
        self._can_fault_reason = str(exc)
        self._can_fault.set()
        self.get_logger().error(
            f'CAN 通信故障，已停止发送运动帧：{self._can_fault_reason}')

    def _snapshots(self) -> tuple[Optional[list[float]], Optional[list[float]]]:
        with self._lock:
            master = None
            follower = None
            if len(self._master_angles) == len(JOINT_NAMES):
                master = [self._master_angles[joint] for joint in range(1, 7)]
            if len(self._follower_angles) == len(JOINT_NAMES):
                follower = [self._follower_angles[joint] for joint in range(1, 7)]
            return master, follower

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

    def _tick(self) -> None:
        if self._can_fault.is_set():
            return
        master, follower = self._snapshots()
        if master is None:
            return
        message = JointState()
        message.header.stamp = self.get_clock().now().to_msg()
        message.name = list(JOINT_NAMES)
        message.position = master
        self._publisher.publish(message)
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
            rate=args.rate,
            send=args.send,
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
