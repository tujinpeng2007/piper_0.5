#!/usr/bin/env python3
"""Publish one dataset episode marker without accessing CAN hardware."""

import argparse
import json
import time
import uuid
from typing import Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


VALID_LABELS = ('start', 'end', 'success', 'failure', 'reset', 'note')
DEFAULT_TOPIC = '/dataset/episode_marker'


def build_marker(episode_id: str, label: str, note: str, stamp_ns: int) -> str:
    """Return a portable JSON marker payload for rosbag and offline tooling."""
    if label not in VALID_LABELS:
        raise ValueError(f'未知标签：{label}')
    if not episode_id:
        raise ValueError('episode_id 不能为空')
    return json.dumps({
        'episode_id': episode_id,
        'label': label,
        'note': note,
        'stamp_ns': stamp_ns,
    }, ensure_ascii=False, separators=(',', ':'))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='发布一次数据集回合标签；不访问 CAN，不控制机械臂。')
    parser.add_argument('label', choices=VALID_LABELS,
                        help='start、end、success、failure、reset 或 note')
    parser.add_argument('--episode-id', default=None,
                        help='同一回合使用同一个 ID；省略时自动生成')
    parser.add_argument('--note', default='', help='可选中文备注，例如“香蕉已入盒”')
    parser.add_argument('--topic', default=DEFAULT_TOPIC, help='标签话题')
    return parser


class EpisodeMarkerPublisher(Node):
    """Publish a marker a few times so an active rosbag reliably receives it."""

    def __init__(self, topic: str, payload: str) -> None:
        super().__init__('piper_episode_marker')
        self._publisher = self.create_publisher(String, topic, 10)
        self._message = String(data=payload)

    def wait_for_subscriber(self, timeout_sec: float = 5.0) -> bool:
        """Wait until rosbag or another observer has matched the publisher."""
        deadline = time.monotonic() + timeout_sec
        while rclpy.ok() and time.monotonic() < deadline:
            if self._publisher.get_subscription_count() > 0:
                return True
            rclpy.spin_once(self, timeout_sec=0.1)
        return self._publisher.get_subscription_count() > 0

    def publish_reliably(self) -> None:
        if not self.wait_for_subscriber():
            self.get_logger().warn(
                '5 秒内没有发现标签订阅者；仍会发布，但可能没有被 rosbag 记录')
        for _ in range(3):
            self._publisher.publish(self._message)
            time.sleep(0.2)


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    episode_id = args.episode_id or f'episode-{uuid.uuid4().hex[:12]}'
    rclpy.init(args=argv)
    node: Optional[EpisodeMarkerPublisher] = None
    try:
        stamp_ns = time.time_ns()
        payload = build_marker(episode_id, args.label, args.note, stamp_ns)
        node = EpisodeMarkerPublisher(args.topic, payload)
        node.publish_reliably()
        node.get_logger().info(f'已发布回合标签：{payload}')
        return 0
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    raise SystemExit(main())
