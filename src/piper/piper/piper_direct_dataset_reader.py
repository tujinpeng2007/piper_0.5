"""Publish observed direct-link CAN targets and feedback without transmitting."""

import argparse
import json
import math
import time

import can


JOINT_NAMES = [f'joint{i}' for i in range(1, 7)] + ['gripper']
ANGLE_SCALE = math.pi / 180_000.0
COMMAND_IDS = (0x155, 0x156, 0x157, 0x159)
FEEDBACK_IDS = (0x2A5, 0x2A6, 0x2A7, 0x2A8)
EVENT_IDS = (0x151, 0x190, 0x471, 0x476)


class FrameSet:
    """Assemble seven positions only from a complete, recent frame set.

    These are observed CAN values, not proof of physical sender identity.
    A frame set does not establish atomicity of the firmware control cycle.
    """

    def __init__(self, ids, *, command=False, max_age=0.1, max_skew=0.05):
        if max_age <= 0 or max_skew <= 0:
            raise ValueError('新鲜度与帧间隔上限必须为正数')
        self.ids = tuple(ids)
        self.command = command
        self.max_age = max_age
        self.max_skew = max_skew
        self.latest = {}
        self.pending = set()

    def update(self, can_id, data, stamp_ns, received_at):
        if can_id not in self.ids or len(data) != 8:
            return None
        if stamp_ns <= 0 or not math.isfinite(received_at):
            return None
        self.latest[can_id] = (bytes(data), stamp_ns, received_at)
        self.pending.add(can_id)
        if set(self.ids) != self.pending:
            return None
        frames = [self.latest[key] for key in self.ids]
        times = [frame[2] for frame in frames]
        stamps = [frame[1] for frame in frames]
        if (received_at - min(times) > self.max_age
                or max(times) - min(times) > self.max_skew
                or (max(stamps) - min(stamps)) / 1e9 > self.max_skew):
            return None
        gripper = frames[-1][0]
        if self.command and (gripper[6] not in (1, 3) or gripper[7] != 0):
            # Disable/clear/zero-setting frames are events, not position actions.
            self.pending.clear()
            return None
        positions = []
        for data, _, _ in frames[:3]:
            positions.extend(
                int.from_bytes(data[start:start + 4], 'big', signed=True)
                * ANGLE_SCALE for start in (0, 4))
        positions.append(int.from_bytes(gripper[:4], 'big', signed=True) * 1e-6)
        self.pending.clear()
        return positions, max(stamps)


def receive_batch(bus, callback, limit=256):
    """Drain a bounded batch; bus.recv is the only CAN operation here."""
    for _ in range(limit):
        frame = bus.recv(timeout=0.0)
        if frame is None:
            break
        if frame.is_error_frame:
            raise can.CanOperationError('收到 CAN 错误帧，停止数据发布')
        if not frame.is_extended_id and not frame.is_remote_frame:
            callback(frame)


def _parser():
    parser = argparse.ArgumentParser(
        description='固件直连数据只读接收器；没有 CAN 发送或使能/失能功能。')
    parser.add_argument('--can-port', required=True)
    parser.add_argument('--feedback-offset', type=lambda s: int(s, 0),
                        choices=(0, 0x10, 0x20), default=0)
    parser.add_argument('--control-offset', type=lambda s: int(s, 0),
                        choices=(0, 0x10, 0x20), default=0)
    parser.add_argument('--duration', type=float, default=0,
                        help='监听秒数；0 为持续运行')
    return parser


def _create_node(port, feedback_offset, control_offset):
    # Lazy imports let pure decoding tests run without starting ROS.
    from rclpy.node import Node
    from sensor_msgs.msg import JointState
    from std_msgs.msg import String

    class DirectDatasetReader(Node):
        def __init__(self):
            super().__init__(f'piper_direct_dataset_reader_{port}')
            if self.get_parameter('use_sim_time').value:
                raise ValueError('CAN 时间戳为系统时间，不支持 use_sim_time')
            self.bus = None
            prefix = f'/dataset/{port}'
            self.raw_pub = self.create_publisher(String, prefix + '/raw_can', 1000)
            self.feedback_pub = self.create_publisher(
                JointState, prefix + '/feedback_observed', 100)
            self.target_pub = self.create_publisher(
                JointState, prefix + '/action_target', 100)
            self.feedback = FrameSet([i + feedback_offset for i in FEEDBACK_IDS])
            self.target = FrameSet([i + control_offset for i in COMMAND_IDS], command=True)
            self.observed_ids = set(self.feedback.ids + self.target.ids)
            self.observed_ids.update(i + control_offset for i in EVENT_IDS[:2])
            self.observed_ids.update(EVENT_IDS[2:])
            try:
                self.bus = can.Bus(interface='socketcan', channel=port,
                                   receive_own_messages=False)
                self.bus.set_filters([
                    {'can_id': i, 'can_mask': 0x7FF, 'extended': False}
                    for i in sorted(self.observed_ids)])
                self.create_timer(0.002, self.poll)
            except Exception:
                if self.bus is not None:
                    self.bus.shutdown()
                super().destroy_node()
                raise
            self.get_logger().info(f'只读接收 {port}；不会发送任何 CAN 帧')
            self.get_logger().warn(
                '反馈实体归属未确认；本节点输出仅为观测值，不能直接作为已验收训练数据')
            self.get_logger().info(f'输出话题：{prefix}/raw_can、feedback_observed、action_target')

        def poll(self):
            receive_batch(self.bus, self.on_frame)

        def on_frame(self, frame):
            if frame.arbitration_id not in self.observed_ids:
                return
            received_ns = time.time_ns()
            mono = time.monotonic()
            timestamp_valid = math.isfinite(frame.timestamp) and frame.timestamp > 0
            stamp_ns = int(frame.timestamp * 1e9) if timestamp_valid else received_ns
            payload = {
                'schema_version': 'piper_direct_can_v1',
                'can_port': port,
                'can_id': frame.arbitration_id,
                'data_hex': bytes(frame.data).hex(),
                'dlc': frame.dlc,
                'stamp_ns': stamp_ns,
                'received_ns': received_ns,
                'timestamp_source': 'socketcan' if timestamp_valid else 'host_receive',
                'entity_verified': False,
            }
            raw = String()
            raw.data = json.dumps(payload, separators=(',', ':'))
            self.raw_pub.publish(raw)
            if abs(received_ns - stamp_ns) > 100_000_000:
                # Keep late raw frames for diagnosis, never publish them as fresh state.
                self.feedback.pending.clear()
                self.target.pending.clear()
                return
            for tracker, publisher, kind in (
                    (self.feedback, self.feedback_pub, 'feedback_unverified'),
                    (self.target, self.target_pub, 'target_unverified')):
                sample = tracker.update(
                    frame.arbitration_id, frame.data, stamp_ns, mono)
                if sample is None:
                    continue
                positions, sample_ns = sample
                message = JointState()
                message.header.stamp.sec = sample_ns // 1_000_000_000
                message.header.stamp.nanosec = sample_ns % 1_000_000_000
                message.header.frame_id = f'{port}:{kind}'
                message.name = list(JOINT_NAMES)
                message.position = positions
                publisher.publish(message)

        def destroy_node(self):
            if self.bus is not None:
                self.bus.shutdown()
                self.bus = None
            return super().destroy_node()

    return DirectDatasetReader()


def main(argv=None):
    import rclpy
    from rclpy.executors import ExternalShutdownException

    args = _parser().parse_args(argv)
    if not math.isfinite(args.duration) or args.duration < 0:
        raise SystemExit('--duration 必须是有限非负数')
    rclpy.init(args=[])
    node = None
    result = 0
    try:
        node = _create_node(args.can_port, args.feedback_offset, args.control_offset)
        deadline = time.monotonic() + args.duration if args.duration else math.inf
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    except (can.CanError, OSError, ValueError) as exc:
        print(f'ERROR: 只读直连接收停止：{exc}')
        result = 1
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return result


if __name__ == '__main__':
    raise SystemExit(main())
