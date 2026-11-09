#!/usr/bin/env python3
"""Create lower-rate compressed image streams for Piper data collection."""

import threading
import time
import math
from collections import Counter
from functools import partial
from typing import Dict, Optional

import cv2
import numpy as np
import rclpy
from cv_bridge import CvBridge, CvBridgeError
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import Executor, MultiThreadedExecutor, SingleThreadedExecutor
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


def configure_opencv_threads(threads: int) -> None:
    """Set a process-local budget before the executor starts callbacks."""
    if not isinstance(threads, int) or isinstance(threads, bool) or threads < 1:
        raise ValueError('opencv_threads 必须为正整数')
    cv2.setNumThreads(threads)


def create_image_executor(threads: int) -> Executor:
    """Use a true single-thread executor for the scheduling comparison."""
    if not isinstance(threads, int) or isinstance(threads, bool) or threads < 1:
        raise ValueError('executor_threads 必须为正整数')
    if threads == 1:
        return SingleThreadedExecutor()
    return MultiThreadedExecutor(num_threads=threads)


def output_qos(kind: str) -> QoSProfile:
    """Buffer RGB for recording, while leaving raw depth best-effort."""
    return QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=30 if kind == 'color' else 2,
        reliability=ReliabilityPolicy.RELIABLE if kind == 'color' else ReliabilityPolicy.BEST_EFFORT,
        durability=DurabilityPolicy.VOLATILE,
    )


class StreamDiagnostics:
    """Bounded per-stream counters; no images or hardware connections retained."""

    def __init__(self, keys, now):
        self._lock = threading.Lock()
        self._since = now
        self._rows = {key: Counter() for key in keys}
        self._last_input = {}
        self._last_callback = {}
        self._last_output = {}

    def input(self, key, stamp, now):
        with self._lock:
            row = self._rows[key]
            row['input'] += 1
            if key in self._last_input and stamp > self._last_input[key]:
                row['input_gap_ms'] = max(row['input_gap_ms'],
                                          (stamp - self._last_input[key]) / 1e6)
            self._last_input[key] = max(stamp, self._last_input.get(key, stamp))
            if key in self._last_callback:
                row['callback_gap_ms'] = max(row['callback_gap_ms'],
                                             (now - self._last_callback[key]) * 1000)
            self._last_callback[key] = max(now, self._last_callback.get(key, now))

    def skip(self, key, reason):
        with self._lock:
            self._rows[key][reason] += 1

    def output(self, key, stamp, encode_ms, publish_ms):
        with self._lock:
            row = self._rows[key]
            row['output'] += 1
            row['encode_ms'] = max(row['encode_ms'], encode_ms)
            row['publish_ms'] = max(row['publish_ms'], publish_ms)
            if key in self._last_output:
                row['output_gap_ms'] = max(row['output_gap_ms'],
                                           (stamp - self._last_output[key]) / 1e6)
            self._last_output[key] = stamp

    def snapshot(self, now):
        with self._lock:
            elapsed = max(now - self._since, 1e-9)
            result = {key: dict(row, elapsed=elapsed,
                                input_hz=row['input'] / elapsed,
                                output_hz=row['output'] / elapsed)
                      for key, row in self._rows.items()}
            self._rows = {key: Counter() for key in self._rows}
            self._since = now
            return result


class PiperDatasetStreams(Node):
    """Throttle and compress six camera streams without controlling hardware."""

    def __init__(self) -> None:
        super().__init__('piper_dataset_streams')
        # Three colour JPEG encoders and three depth streams run stably at 5 Hz
        # on the experiment workstation.  Higher rates can be requested
        # explicitly, but are not the verified collection default.
        self.declare_parameter('output_rate', 5.0)
        self.declare_parameter('jpeg_quality', 90)
        self.declare_parameter('enable_depth', True)
        self.declare_parameter('diagnostics_period', 5.0)
        self.declare_parameter('opencv_threads', 1)
        self.declare_parameter('executor_threads', 1)

        self._output_rate = float(self.get_parameter('output_rate').value)
        self._jpeg_quality = int(self.get_parameter('jpeg_quality').value)
        self._enable_depth = bool(self.get_parameter('enable_depth').value)
        diagnostics_period = float(self.get_parameter('diagnostics_period').value)
        if not math.isfinite(diagnostics_period) or diagnostics_period <= 0:
            raise ValueError('diagnostics_period 必须为有限正数')
        validate_options(self._output_rate, self._jpeg_quality)
        configure_opencv_threads(self.get_parameter('opencv_threads').value)
        self._diagnostics = StreamDiagnostics(
            [key for key, (_, _, kind) in STREAMS.items()
             if self._enable_depth or kind == 'color'], time.monotonic())

        self._bridge = CvBridge()
        self._last_emit: Dict[str, float] = {}
        self._last_source_stamp: Dict[str, int] = {}
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
            if kind == 'depth' and not self._enable_depth:
                continue
            output_type = CompressedImage if kind == 'color' else Image
            self._output_publishers[key] = self.create_publisher(
                output_type, output_topic, output_qos(kind))
            self._image_subscriptions.append(self.create_subscription(
                Image,
                input_topic,
                partial(self._on_image, key, kind),
                camera_qos,
                callback_group=self._callback_group,
            ))

        self.get_logger().info(
            f'训练图像流：{self._output_rate:g} Hz，JPEG质量='
            f'{self._jpeg_quality}，' + ('深度图保持原始格式' if self._enable_depth else '仅发布三路 RGB'))
        self.get_logger().info(
            '本节点只读取并压缩图像，不访问 CAN，不发送机械臂控制命令')
        self.get_logger().info(f'本进程 OpenCV 线程数：{cv2.getNumThreads()}')
        self.get_logger().info(
            f'ROS 执行器线程数：{self.get_parameter("executor_threads").value}')
        self._diagnostics_timer = self.create_timer(
            diagnostics_period, self._report_diagnostics)

    def _report_diagnostics(self):
        for key, row in self._diagnostics.snapshot(time.monotonic()).items():
            self.get_logger().info(
                f'图像诊断 {key}：输入={row.get("input", 0)} '
                f'({row["input_hz"]:.1f}Hz)，输出={row.get("output", 0)} '
                f'({row["output_hz"]:.1f}Hz)，'
                f'主动降频={row.get("throttle", 0)}，忙跳过={row.get("busy", 0)}，'
                f'旧时间戳={row.get("old_stamp", 0)}，错误={row.get("error", 0)}；'
                f'输入源/回调/输出源最大间隔ms='
                f'{row.get("input_gap_ms", 0):.1f}/'
                f'{row.get("callback_gap_ms", 0):.1f}/'
                f'{row.get("output_gap_ms", 0):.1f}，'
                f'转换编码/发布最大耗时ms='
                f'{row.get("encode_ms", 0):.1f}/{row.get("publish_ms", 0):.1f}')

    def _on_image(self, key: str, kind: str, message: Image) -> None:
        source_stamp = (message.header.stamp.sec * 1_000_000_000
                        + message.header.stamp.nanosec)
        self._diagnostics.input(key, source_stamp, time.monotonic())
        stream_lock = self._stream_locks[key]
        if not stream_lock.acquire(blocking=False):
            self._diagnostics.skip(key, 'busy')
            return
        try:
            if source_stamp <= self._last_source_stamp.get(key, 0):
                self._diagnostics.skip(key, 'old_stamp')
                return
            now = time.monotonic()
            with self._schedule_lock:
                next_reference = next_emit_reference(
                    self._last_emit.get(key), now, self._output_rate)
                if next_reference is None:
                    self._diagnostics.skip(key, 'throttle')
                    return
                self._last_emit[key] = next_reference

            if kind == 'depth':
                publish_start = time.perf_counter()
                self._output_publishers[key].publish(message)
                self._diagnostics.output(
                    key, source_stamp, 0, (time.perf_counter() - publish_start) * 1000)
                self._last_source_stamp[key] = source_stamp
                return

            encode_start = time.perf_counter()
            image = self._bridge.imgmsg_to_cv2(
                message, desired_encoding='bgr8')
            payload = encode_color_jpeg(image, self._jpeg_quality)
            encode_ms = (time.perf_counter() - encode_start) * 1000
            # Keep serialization/publication inside the stream lock so a
            # second encoder cannot overtake the first and reverse timestamps.
            output = CompressedImage()
            output.header = message.header
            output.format = 'jpeg; source_encoding=bgr8'
            output.data = payload
            publish_start = time.perf_counter()
            self._output_publishers[key].publish(output)
            self._diagnostics.output(
                key, source_stamp, encode_ms, (time.perf_counter() - publish_start) * 1000)
            self._last_source_stamp[key] = source_stamp
        except (CvBridgeError, ValueError, cv2.error) as exc:
            self._diagnostics.skip(key, 'error')
            self.get_logger().error(f'{key} 图像压缩失败：{exc}')
            return
        finally:
            stream_lock.release()


def main(args=None) -> None:
    rclpy.init(args=args)
    node: Optional[PiperDatasetStreams] = None
    executor: Optional[Executor] = None
    try:
        node = PiperDatasetStreams()
        executor = create_image_executor(node.get_parameter('executor_threads').value)
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
