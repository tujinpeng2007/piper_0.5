#!/usr/bin/env python3
"""Read joint feedback from a Piper teaching-input arm without transmitting."""

import threading
from typing import Dict, Optional

import can
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState


BASE_JOINT_ANGLE_IDS = {
    0x2A5: (1, 2),
    0x2A6: (3, 4),
    0x2A7: (5, 6),
}
JOINT_NAMES = ['joint1', 'joint2', 'joint3', 'joint4', 'joint5', 'joint6']
RAD_PER_MILLI_DEG = 0.001 * 3.141592653589793 / 180.0


def decode_teach_joint_frame(can_id: int, data: bytes,
                             feedback_offset: int = 0x20) -> Dict[int, float]:
    """Decode one shifted teaching-input joint frame into radians."""
    joints = BASE_JOINT_ANGLE_IDS.get(can_id - feedback_offset)
    if joints is None or len(data) < 8:
        return {}
    return {
        joints[0]: int.from_bytes(data[0:4], 'big', signed=True)
        * RAD_PER_MILLI_DEG,
        joints[1]: int.from_bytes(data[4:8], 'big', signed=True)
        * RAD_PER_MILLI_DEG,
    }


class PiperTeachReader(Node):
    """Publish teaching-input joint angles from a receive-only CAN socket."""

    def __init__(self) -> None:
        super().__init__('piper_teach_reader')
        self.declare_parameter('can_port', 'can_left')
        self.declare_parameter('feedback_offset', 0x20)
        self.declare_parameter('topic', '/joint_states_teach')
        self.declare_parameter('publish_rate', 50.0)

        port = str(self.get_parameter('can_port').value)
        offset = int(self.get_parameter('feedback_offset').value)
        topic = str(self.get_parameter('topic').value)
        rate = float(self.get_parameter('publish_rate').value)
        if rate <= 0:
            raise ValueError('publish_rate must be positive')

        self._offset = offset
        self._angles: Dict[int, float] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._bus = can.Bus(
            interface='socketcan', channel=port, receive_own_messages=False)
        self._bus.set_filters([
            {'can_id': can_id + offset, 'can_mask': 0x7FF, 'extended': False}
            for can_id in BASE_JOINT_ANGLE_IDS
        ])
        self._reader = threading.Thread(
            target=self._read_loop, name='piper_teach_can_reader', daemon=True)
        self._reader.start()
        self._publisher = self.create_publisher(JointState, topic, 10)
        self._timer = self.create_timer(1.0 / rate, self._publish)
        self.get_logger().info(
            f'只读示教反馈：CAN={port}，反馈偏移=0x{offset:02X}，话题={topic}')
        self.get_logger().info('本节点不会发送任何 CAN 帧，也不会使能或失能机械臂')

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            frame = self._bus.recv(timeout=0.2)
            if frame is None:
                continue
            decoded = decode_teach_joint_frame(
                frame.arbitration_id, bytes(frame.data), self._offset)
            if decoded:
                with self._lock:
                    self._angles.update(decoded)

    def _publish(self) -> None:
        with self._lock:
            if len(self._angles) < len(JOINT_NAMES):
                return
            positions = [self._angles[joint] for joint in range(1, 7)]
        message = JointState()
        message.header.stamp = self.get_clock().now().to_msg()
        message.name = list(JOINT_NAMES)
        message.position = positions
        self._publisher.publish(message)

    def destroy_node(self):
        self._stop.set()
        self._reader.join(timeout=1.0)
        self._bus.shutdown()
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node: Optional[PiperTeachReader] = None
    try:
        node = PiperTeachReader()
        rclpy.spin(node)
    except (KeyboardInterrupt, can.CanError, OSError, ValueError) as exc:
        if node is not None:
            node.get_logger().error(str(exc))
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
