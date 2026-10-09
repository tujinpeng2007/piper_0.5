#!/usr/bin/env python3
"""从已结束的 Piper rosbag 离线导出待标注图像。

本工具只读取 rosbag 文件并写出图像、时间戳清单和 COCO 标注骨架；不初始化 ROS 节点，
不访问 CAN，也不发送任何机械臂或夹爪命令。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple


DEFAULT_TOPIC = '/dataset/camera_third_view/color/image_jpeg'
CATEGORIES = (
    {'id': 1, 'name': 'banana', 'supercategory': 'object'},
    {'id': 2, 'name': 'box', 'supercategory': 'object'},
)


def choose_indices(total: int, every: int, limit: int | None = None) -> Tuple[int, ...]:
    """Return zero-based source-frame indices sampled at a fixed interval."""
    if total < 0:
        raise ValueError('总帧数不能为负数')
    if every <= 0:
        raise ValueError('抽帧间隔必须为正数')
    if limit is not None and limit <= 0:
        raise ValueError('最大导出数量必须为正数')
    selected = tuple(range(0, total, every))
    return selected if limit is None else selected[:limit]


def build_coco_template(source_bag: Path, topic: str,
                        images: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Build an empty COCO annotation file for exported image records."""
    return {
        'info': {
            'description': 'Piper Pi05 香蕉入盒 A2 离线标注集',
            'source_bag': str(source_bag),
            'source_topic': topic,
        },
        'licenses': [],
        'categories': list(CATEGORIES),
        'images': list(images),
        'annotations': [],
    }


def _prepare_output(output_dir: Path) -> Path:
    """Create an empty output directory and its image child directory."""
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f'输出目录已存在且非空，拒绝覆盖：{output_dir}')
    output_dir.mkdir(parents=True, exist_ok=True)
    image_dir = output_dir / 'images'
    image_dir.mkdir(exist_ok=True)
    return image_dir


def _jpeg_size(payload: bytes) -> Tuple[int, int]:
    """Return JPEG width and height without depending on a ROS image node."""
    import cv2
    import numpy as np

    image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError('无法解码 JPEG 图像')
    height, width = image.shape[:2]
    return width, height


def export_images(bag_dir: Path, output_dir: Path, topic: str,
                  every: int, limit: int | None = None) -> Dict[str, Any]:
    """Export sampled JPEG messages and return the annotation summary."""
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message

    if not bag_dir.is_dir():
        raise ValueError(f'rosbag 目录不存在：{bag_dir}')
    image_dir = _prepare_output(output_dir)

    reader = rosbag2_py.SequentialCompressionReader()
    reader.open(
        rosbag2_py.StorageOptions(uri=str(bag_dir), storage_id='sqlite3'),
        rosbag2_py.ConverterOptions('', ''),
    )
    topic_types = {item.name: item.type for item in reader.get_all_topics_and_types()}
    if topic not in topic_types:
        raise ValueError(f'rosbag 中不存在图像话题：{topic}')
    if topic_types[topic] != 'sensor_msgs/msg/CompressedImage':
        raise ValueError(f'仅支持 CompressedImage，实际类型为：{topic_types[topic]}')

    message_type = get_message(topic_types[topic])
    source_index = 0
    exported: List[Dict[str, Any]] = []
    while reader.has_next():
        current_topic, serialized, bag_stamp_ns = reader.read_next()
        if current_topic != topic:
            continue
        should_export = source_index % every == 0
        reached_limit = limit is not None and len(exported) >= limit
        if should_export and not reached_limit:
            message = deserialize_message(serialized, message_type)
            image_format = message.format.lower()
            if 'jpeg' not in image_format and 'jpg' not in image_format:
                raise ValueError(f'只接受 JPEG 压缩图像，收到格式：{message.format}')
            payload = bytes(message.data)
            width, height = _jpeg_size(payload)
            image_id = len(exported) + 1
            file_name = f'images/frame_{image_id:05d}_{bag_stamp_ns}.jpg'
            (output_dir / file_name).write_bytes(payload)
            exported.append({
                'id': image_id,
                'file_name': file_name,
                'width': width,
                'height': height,
                'bag_stamp_ns': int(bag_stamp_ns),
                'source_frame_index': source_index,
            })
        source_index += 1

    if not exported:
        raise ValueError('没有导出任何图像；请检查话题、抽帧间隔和最大数量')

    coco = build_coco_template(bag_dir, topic, exported)
    annotation_path = output_dir / 'annotations_coco.json'
    annotation_path.write_text(
        json.dumps(coco, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    summary = {
        'source_bag': str(bag_dir),
        'source_topic': topic,
        'source_frame_count': source_index,
        'exported_image_count': len(exported),
        'sample_every': every,
        'annotations_template': str(annotation_path),
    }
    (output_dir / 'export_manifest.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bag_dir', type=Path, help='已结束的 rosbag 目录')
    parser.add_argument('output_dir', type=Path, help='必须不存在或为空的导出目录')
    parser.add_argument('--topic', default=DEFAULT_TOPIC, help='要导出的 JPEG 图像话题')
    parser.add_argument('--every', type=int, default=5, help='每隔 N 帧导出一张，默认 %(default)s')
    parser.add_argument('--limit', type=int, help='最多导出多少张图像')
    return parser


def main(argv=None) -> int:
    options = _parser().parse_args(argv)
    try:
        summary = export_images(
            options.bag_dir, options.output_dir, options.topic,
            options.every, options.limit)
    except Exception as exc:
        print(f'ERROR: 离线图像导出失败：{exc}')
        return 2
    print('RESULT: 离线图像导出完成，不访问 CAN、不控制机械臂。')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
