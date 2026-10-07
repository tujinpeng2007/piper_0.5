#!/usr/bin/env python3
"""Create lower-rate compressed image streams for Piper data collection."""

import threading
import time
from functools import partial
from typing import Dict, Optional

import cv2
import numpy as np
import rclpy
from cv_bridge import CvBridge, CvBridgeError
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)
from sensor_msgs.msg import CompressedImage, Image


STREAMS = {
    'left_color': (
        '/camera_gripper_left/color/image_raw',
        '/dataset/camera_gripper_left/color/image_jpeg',
        'color',
    ),
    'left_depth': (
        '/camera_gripper_left/depth/image_raw',
        '/dataset/camera_gripper_left/depth/image_raw',
        'depth',
    ),
    'right_color': (
        '/camera_gripper_right/color/image_raw',
        '/dataset/camera_gripper_right/color/image_jpeg',
        'color',
    ),
    'right_depth': (
        '/camera_gripper_right/depth/image_raw',
        '/dataset/camera_gripper_right/depth/image_raw',
        'depth',
    ),
    'third_color': (
        '/camera_third_view/D455_1/color/image_raw',
        '/dataset/camera_third_view/color/image_jpeg',
        'color',
    ),
    'third_depth': (
        '/camera_third_view/D455_1/depth/image_rect_raw',
        '/dataset/camera_third_view/depth/image_raw',
        'depth',
    ),
}


def validate_options(output_rate: float, jpeg_quality: int) -> None:
    """Validate encoding options before subscriptions are created."""
    if output_rate <= 0:
        raise ValueError('output_rate must be positive')
    if not 1 <= jpeg_quality <= 100:
        raise ValueError('jpeg_quality must be in [1, 100]')


def next_emit_reference(last_time: Optional[float], now: float,
                        output_rate: float) -> Optional[float]:
    """Return the next phase reference, or None when this frame is too early."""
    if last_time is None:
        return now
    period = 1.0 / output_rate
    elapsed = now - last_time
    if elapsed + 1e-9 < period:
        return None
    periods = max(1, int((elapsed + 1e-9) / period))
    return last_time + periods * period


def encode_color_jpeg(image: np.ndarray, quality: int) -> bytes:
    """Encode a BGR image as JPEG."""
    success, encoded = cv2.imencode(
        '.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not success:
        raise ValueError('failed to encode JPEG image')
    return encoded.tobytes()


class PiperDatasetStreams(Node):
    """Throttle and compress six camera streams without controlling hardware."""

    def __init__(self) -> None:
        super().__init__('piper_dataset_streams')
        # Three colour JPEG encoders and three depth streams run stably at 5 Hz
        # on the experiment workstation.  Higher rates can be requested
        # explicitly, but are not the verified collection default.
        self.declare_parameter('output_rate', 5.0)
        self.declare_parameter('jpeg_quality', 90)

        self._output_rate = float(self.get_parameter('output_rate').value)
        self._jpeg_quality = int(self.get_parameter('jpeg_quality').value)
        validate_options(self._output_rate, self._jpeg_quality)

        self._bridge = CvBridge()
        self._last_emit: Dict[str, float] = {}
        self._schedule_lock = threading.Lock()
        self._stream_locks = {
            key: threading.Lock() for key in STREAMS
        }
        self._callback_group = ReentrantCallbackGroup()
        self._output_publishers = {}
        self._image_subscriptions = []
        camera_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=2,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
        )

        for key, (input_topic, output_topic, kind) in STREAMS.items():
            output_type = CompressedImage if kind == 'color' else Image
            self._output_publishers[key] = self.create_publisher(
                output_type, output_topic, camera_qos)
            self._image_subscriptions.append(self.create_subscription(
                Image,
                input_topic,
                partial(self._on_image, key, kind),
                camera_qos,
                callback_group=self._callback_group,
            ))

        self.get_logger().info(
            f'训练图像流：{self._output_rate:g} Hz，JPEG质量='
            f'{self._jpeg_quality}，深度图保持原始格式')
        self.get_logger().info(
            '本节点只读取并压缩图像，不访问 CAN，不发送机械臂控制命令')

    def _on_image(self, key: str, kind: str, message: Image) -> None:
        stream_lock = self._stream_locks[key]
        if not stream_lock.acquire(blocking=False):
            return
        try:
            now = time.monotonic()
            with self._schedule_lock:
                next_reference = next_emit_reference(
                    self._last_emit.get(key), now, self._output_rate)
                if next_reference is None:
                    return
                self._last_emit[key] = next_reference

            if kind == 'depth':
                self._output_publishers[key].publish(message)
                return

            image = self._bridge.imgmsg_to_cv2(
                message, desired_encoding='bgr8')
            payload = encode_color_jpeg(image, self._jpeg_quality)
        except (CvBridgeError, ValueError, cv2.error) as exc:
            self.get_logger().error(f'{key} 图像压缩失败：{exc}')
            return
        finally:
            stream_lock.release()

        output = CompressedImage()
        output.header = message.header
        output.format = 'jpeg; source_encoding=bgr8'
        output.data = payload
        self._output_publishers[key].publish(output)


def main(args=None) -> None:
    rclpy.init(args=args)
    node: Optional[PiperDatasetStreams] = None
    executor: Optional[MultiThreadedExecutor] = None
    try:
        node = PiperDatasetStreams()
        executor = MultiThreadedExecutor(num_threads=6)
        executor.add_node(node)
        executor.spin()
    except (KeyboardInterrupt, ValueError):
        pass
    finally:
        if executor is not None:
            executor.shutdown()
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
