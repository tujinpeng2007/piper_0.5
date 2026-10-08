#!/usr/bin/env python3
"""Validate a Piper Pi05 rosbag without accessing robot hardware.

The validator only opens an existing rosbag for reading.  It checks required
topics and episode-marker consistency, then prints a JSON summary suitable for
an offline data inventory.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple


CAMERA_TOPICS = (
    '/dataset/camera_gripper_left/color/image_jpeg',
    '/dataset/camera_gripper_left/depth/image_raw',
    '/dataset/camera_gripper_right/color/image_jpeg',
    '/dataset/camera_gripper_right/depth/image_raw',
    '/dataset/camera_third_view/color/image_jpeg',
    '/dataset/camera_third_view/depth/image_raw',
)
MARKER_TOPIC = '/dataset/episode_marker'
JOINT_TOPICS = (
    '/joint_states_teach_shared',
    '/joint_states_follower_shared',
)
MODES = ('static', 'demonstration')


def required_topics(mode: str) -> Tuple[str, ...]:
    """Return required ROS topics for one recording mode."""
    if mode not in MODES:
        raise ValueError(f'未知录制模式：{mode}')
    if mode == 'static':
        return CAMERA_TOPICS + (MARKER_TOPIC,)
    return CAMERA_TOPICS + JOINT_TOPICS + (MARKER_TOPIC,)


def parse_marker_payload(payload: str) -> Dict[str, Any]:
    """Parse and minimally validate one marker JSON payload."""
    marker = json.loads(payload)
    required = (
        'schema_version', 'episode_id', 'label', 'stamp_ns', 'task',
        'scene_id', 'attempt', 'operator',
    )
    missing = [key for key in required if key not in marker]
    if missing:
        raise ValueError('标签缺少字段：' + '、'.join(missing))
    if not isinstance(marker['episode_id'], str) or not marker['episode_id']:
        raise ValueError('标签 episode_id 无效')
    if not isinstance(marker['attempt'], int) or marker['attempt'] < 0:
        raise ValueError('标签 attempt 无效')
    return marker


def validate_episode(
    topics: Iterable[str],
    marker_payloads: Iterable[str],
    mode: str,
) -> Dict[str, Any]:
    """Validate required topics and repeated episode markers."""
    available = set(topics)
    missing_topics = sorted(set(required_topics(mode)) - available)
    errors: List[str] = []
    if missing_topics:
        errors.append('缺少话题：' + '、'.join(missing_topics))

    markers: List[Dict[str, Any]] = []
    for index, payload in enumerate(marker_payloads, start=1):
        try:
            markers.append(parse_marker_payload(payload))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f'第 {index} 条标签无效：{exc}')

    label_counts = Counter(marker['label'] for marker in markers)
    episode_ids = sorted({marker['episode_id'] for marker in markers})
    metadata_keys = ('schema_version', 'task', 'scene_id', 'attempt', 'operator')
    metadata: Dict[str, Any] = {}
    if len(episode_ids) != 1:
        errors.append('标签必须且只能对应一个 episode_id')
    if markers:
        for key in metadata_keys:
            values = {marker[key] for marker in markers}
            if len(values) != 1:
                errors.append(f'标签 {key} 不一致')
            else:
                metadata[key] = values.pop()
        for key in ('task', 'scene_id', 'operator'):
            if not metadata.get(key):
                errors.append(f'标签 {key} 不能为空')
        if not metadata.get('attempt'):
            errors.append('标签 attempt 必须大于 0')
    else:
        errors.append('未找到任何回合标签')

    expected_labels = ('start', 'note', 'end')
    if mode == 'demonstration':
        expected_labels = ('start', 'end')
        if not (label_counts['success'] or label_counts['failure']):
            errors.append('示教回合必须包含 success 或 failure 标签')
    for label in expected_labels:
        if label_counts[label] < 3:
            errors.append(f'标签 {label} 少于 3 条可靠投递副本')

    return {
        'valid': not errors,
        'mode': mode,
        'available_topics': sorted(available),
        'missing_topics': missing_topics,
        'marker_count': len(markers),
        'marker_label_counts': dict(sorted(label_counts.items())),
        'episode_id': episode_ids[0] if len(episode_ids) == 1 else '',
        'metadata': metadata,
        'errors': errors,
    }


def read_bag(bag_dir: Path) -> Tuple[Sequence[str], List[str]]:
    """Read topic names and marker payloads from one existing rosbag."""
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message

    # 采集流程采用 ``--compression-mode file --compression-format zstd``。
    # SequentialCompressionReader 会按 rosbag 元数据自动解压；普通
    # SequentialReader 会把 .db3.zstd 当作 SQLite 文件，因而无法读取。
    reader = rosbag2_py.SequentialCompressionReader()
    reader.open(
        rosbag2_py.StorageOptions(uri=str(bag_dir), storage_id='sqlite3'),
        rosbag2_py.ConverterOptions('', ''),
    )
    topic_types = {
        topic.name: topic.type for topic in reader.get_all_topics_and_types()
    }
    marker_type = get_message(topic_types.get(MARKER_TOPIC, 'std_msgs/msg/String'))
    markers: List[str] = []
    while reader.has_next():
        topic, serialized, _stamp = reader.read_next()
        if topic == MARKER_TOPIC:
            markers.append(deserialize_message(serialized, marker_type).data)
    return tuple(topic_types), markers


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bag_dir', type=Path, help='rosbag 目录，例如 data/.../banana-a01-001')
    parser.add_argument('--mode', choices=MODES, required=True, help='static 或 demonstration')
    parser.add_argument(
        '--write-manifest', action='store_true',
        help='在 bag 目录写入 episode_manifest.json；默认只打印结果',
    )
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    if not args.bag_dir.is_dir():
        print(f'ERROR: rosbag 目录不存在：{args.bag_dir}')
        return 2
    try:
        topics, markers = read_bag(args.bag_dir)
        summary = validate_episode(topics, markers, args.mode)
    except Exception as exc:
        print(f'ERROR: 无法读取 rosbag：{exc}')
        return 2

    summary['bag_dir'] = str(args.bag_dir)
    rendered = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if args.write_manifest:
        path = args.bag_dir / 'episode_manifest.json'
        path.write_text(rendered + '\n', encoding='utf-8')
        print(f'已写入清单：{path}')
    return 0 if summary['valid'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
