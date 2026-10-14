"""离线将固件直连演示整理成 π0.5 适配用候选数据，不访问 CAN。"""

import argparse
import bisect
import json
import math
from collections import Counter
from pathlib import Path

from piper.piper_dataset_validate import (
    DIRECT_TOPICS, MARKER_TOPIC, RGB_TOPICS, validate_episode,
)

NAMES = [f'joint{i}' for i in range(1, 7)] + ['gripper']
ANCHOR_TOPIC = '/dataset/camera_third_view/color/image_jpeg'
CAMERAS = dict(zip(RGB_TOPICS, ('left_wrist', 'right_wrist', 'third_view')))


def latest_index(stamps, target, max_age_ns):
    """Causal selection: never use a future sample or silently interpolate."""
    index = bisect.bisect_right(stamps, target) - 1
    if index < 0 or target - stamps[index] > max_age_ns:
        return None
    return index


def segment_ranges(grid_stamps, step_ns):
    """Split at every missing grid point, even if a gap looks short."""
    if step_ns <= 0:
        raise ValueError('采样间隔必须为正数')
    if not grid_stamps:
        return []
    starts = [0]
    for i in range(1, len(grid_stamps)):
        gap = grid_stamps[i] - grid_stamps[i - 1]
        if gap <= 0:
            raise ValueError('采样网格时间必须严格递增')
        if gap != step_ns:
            starts.append(i)
    return list(zip(starts, starts[1:] + [len(grid_stamps)]))


def action_window_starts(segments, horizon):
    """Eligible fixed-length action chunks; never cross a recording gap."""
    if not isinstance(horizon, int) or isinstance(horizon, bool) or horizon <= 0:
        raise ValueError('动作序列长度必须为正整数')
    return [i for start, stop in segments for i in range(start, stop - horizon + 1)]


def align_streams(stamps, start_ns, stop_ns, fps, image_age_ms=250, vector_age_ms=100):
    """Return aligned source indices and explicit reasons for rejected grid points."""
    if not math.isfinite(fps) or not 0 < fps <= 200:
        raise ValueError('fps 必须在 (0, 200] 内')
    if start_ns >= stop_ns or image_age_ms <= 0 or vector_age_ms <= 0:
        raise ValueError('时间范围或新鲜度上限无效')
    expected = RGB_TOPICS + DIRECT_TOPICS[:2]
    for topic in expected:
        if topic not in stamps or not stamps[topic]:
            raise ValueError(f'话题没有数据：{topic}')
        if any(b <= a for a, b in zip(stamps[topic], stamps[topic][1:])):
            raise ValueError(f'源时间戳不严格递增：{topic}')
    step = round(1e9 / fps)
    aligned, dropped = [], Counter()
    previous_image = None
    for grid_ns in range(start_ns, stop_ns, step):
        anchor_i = latest_index(stamps[ANCHOR_TOPIC], grid_ns, round(image_age_ms * 1e6))
        if anchor_i is None:
            dropped['third_view_missing_or_stale'] += 1
            continue
        if anchor_i == previous_image:
            dropped['duplicate_third_view'] += 1
            continue
        anchor_ns = stamps[ANCHOR_TOPIC][anchor_i]
        if anchor_ns < start_ns:
            dropped['before_start'] += 1
            continue
        indices = {}
        for topic in expected:
            age = image_age_ms if topic in RGB_TOPICS else vector_age_ms
            index = latest_index(stamps[topic], anchor_ns, round(age * 1e6))
            if index is None:
                dropped[f'{topic}:missing_or_stale'] += 1
                break
            indices[topic] = index
        else:
            indices['grid_stamp_ns'] = grid_ns
            aligned.append((anchor_ns, indices))
            previous_image = anchor_i
    return aligned, dict(dropped)


def _read(bag_dir):
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message

    metadata = rosbag2_py.Info().read_metadata(str(bag_dir), 'sqlite3')
    reader = (rosbag2_py.SequentialCompressionReader() if metadata.compression_mode
              else rosbag2_py.SequentialReader())
    reader.open(rosbag2_py.StorageOptions(uri=str(bag_dir), storage_id='sqlite3'),
                rosbag2_py.ConverterOptions('', ''))
    types = {item.name: item.type for item in reader.get_all_topics_and_types()}
    expected = {t: 'sensor_msgs/msg/CompressedImage' for t in RGB_TOPICS}
    expected.update({t: 'sensor_msgs/msg/JointState' for t in DIRECT_TOPICS[:2]})
    expected.update({DIRECT_TOPICS[2]: 'std_msgs/msg/String', MARKER_TOPIC: 'std_msgs/msg/String'})
    for topic, type_name in expected.items():
        if types.get(topic) != type_name:
            raise ValueError(f'缺少话题或类型错误：{topic}')
    message_types = {t: get_message(k) for t, k in expected.items()}
    streams = {t: [] for t in RGB_TOPICS + DIRECT_TOPICS[:2]}
    markers, counts, raw_ids, entities = [], Counter(), Counter(), set()
    while reader.has_next():
        topic, serialized, _ = reader.read_next()
        counts[topic] += 1
        if topic not in expected:
            continue
        message = deserialize_message(serialized, message_types[topic])
        if topic == MARKER_TOPIC:
            markers.append(message.data)
            continue
        if topic == DIRECT_TOPICS[2]:
            record = json.loads(message.data)
            if record.get('schema_version') != 'piper_direct_can_v1':
                raise ValueError('原始 CAN schema 无效')
            if record.get('can_port') != 'can_left':
                raise ValueError('原始 CAN 接口不是 can_left')
            raw_ids[int(record['can_id'])] += 1
            continue
        stamp = message.header.stamp.sec * 1_000_000_000 + message.header.stamp.nanosec
        if stamp <= 0:
            raise ValueError(f'源时间戳无效：{topic}')
        if topic in RGB_TOPICS:
            if not any(s in message.format.lower() for s in ('jpeg', 'jpg')):
                raise ValueError(f'相机不是 JPEG：{topic}')
            data = bytes(message.data)
        else:
            if list(message.name) != NAMES or len(message.position) != 7:
                raise ValueError(f'七维名称、顺序或长度不符合约定：{topic}')
            data = tuple(message.position)
            if not all(math.isfinite(v) for v in data):
                raise ValueError(f'位置有非有限值：{topic}')
            entities.add(message.header.frame_id)
        streams[topic].append((stamp, data))
    return types, streams, markers, counts, raw_ids, sorted(entities)


def prepare(bag_dir, output_dir, fps=5.0):
    import cv2
    import numpy as np

    if output_dir.exists():
        raise ValueError(f'输出目录已存在，拒绝覆盖：{output_dir}')
    types, streams, markers, counts, raw_ids, entities = _read(bag_dir)
    validation = validate_episode(types, markers, 'direct_demonstration')
    if not validation['valid']:
        raise ValueError('标签/话题校验失败：' + '；'.join(validation['errors']))
    if validation['metadata']['task'] != 'banana_into_box':
        raise ValueError('本工具当前只适配 banana_into_box，不能猜填其他任务提示')
    if not counts[DIRECT_TOPICS[2]]:
        raise ValueError('原始 CAN 话题为空')
    missing_ids = set((0x155, 0x156, 0x157, 0x159, 0x2A5, 0x2A6, 0x2A7, 0x2A8)) - set(raw_ids)
    if missing_ids:
        raise ValueError('原始 CAN 缺少动作/反馈 ID：' + ', '.join(hex(i) for i in sorted(missing_ids)))
    parsed = [json.loads(m) for m in markers]
    start_ns = min(m['stamp_ns'] for m in parsed if m['label'] == 'start')
    result_label = 'success' if validation['marker_label_counts'].get('success') else 'failure'
    result_ns = min(m['stamp_ns'] for m in parsed if m['label'] == result_label)
    end_ns = min(m['stamp_ns'] for m in parsed if m['label'] == 'end')
    if not start_ns < result_ns <= end_ns:
        raise ValueError('开始、结果、结束标签时间顺序错误')
    stamps = {t: [row[0] for row in rows] for t, rows in streams.items()}
    aligned, dropped = align_streams(stamps, start_ns, result_ns, fps)
    if not aligned:
        raise ValueError('没有可对齐的样本；检查动作目标是否录到以及相机频率')

    output_dir.mkdir(parents=True, exist_ok=False)
    for camera in CAMERAS.values():
        (output_dir / 'images' / camera).mkdir(parents=True)
    state, action, source_times, image_paths = [], [], [], []
    topics = RGB_TOPICS + DIRECT_TOPICS[:2]
    for number, (anchor, indices) in enumerate(aligned):
        row_paths = []
        for topic, camera in CAMERAS.items():
            payload = streams[topic][indices[topic]][1]
            if cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR) is None:
                raise ValueError(f'JPEG 无法解码：{topic}，样本 {number}')
            path = Path('images') / camera / f'{number:06d}_{anchor}.jpg'
            (output_dir / path).write_bytes(payload)
            row_paths.append(str(path))
        state.append(streams[DIRECT_TOPICS[0]][indices[DIRECT_TOPICS[0]]][1])
        action.append(streams[DIRECT_TOPICS[1]][indices[DIRECT_TOPICS[1]]][1])
        source_times.append([streams[t][indices[t]][0] for t in topics])
        image_paths.append(row_paths)
    anchor_times = [row[0] for row in aligned]
    grid_times = [row[1]['grid_stamp_ns'] for row in aligned]
    segments = segment_ranges(grid_times, round(1e9 / fps))
    segment_ids = np.empty(len(aligned), dtype=np.int32)
    segment_info = []
    for segment_id, (start, stop) in enumerate(segments):
        segment_ids[start:stop] = segment_id
        segment_info.append({
            'segment_id': segment_id, 'sample_start': start, 'sample_stop_exclusive': stop,
            'sample_count': stop - start,
            'source_start_ns': anchor_times[start], 'source_end_ns': anchor_times[stop - 1],
            'grid_start_ns': grid_times[start], 'grid_end_ns': grid_times[stop - 1],
            'parent_result': result_label,
            'segment_task_success_verified': False,
        })
    np.savez_compressed(
        output_dir / 'aligned_candidate.npz',
        timestamp_ns=np.asarray(anchor_times, dtype=np.int64),
        grid_timestamp_ns=np.asarray(grid_times, dtype=np.int64),
        segment_id=segment_ids,
        source_timestamp_ns=np.asarray(source_times, dtype=np.int64),
        state=np.asarray(state, dtype=np.float32),
        action=np.asarray(action, dtype=np.float32),
        image_paths=np.asarray(image_paths),
    )
    span = (anchor_times[-1] - anchor_times[0]) / 1e9
    effective_fps = (len(aligned) - 1) / span if span else 0.0
    max_gap = max((b - a) / 1e9 for a, b in zip(anchor_times, anchor_times[1:])) if len(aligned) > 1 else 0
    quality_errors = []
    if len(aligned) < 10:
        quality_errors.append('对齐样本少于 10 条')
    if effective_fps < 0.8 * fps:
        quality_errors.append('有效图像频率低于请求频率的 80%')
    if max_gap > max(0.6, 3 / fps):
        quality_errors.append('演示内部存在较长数据间隙')
    report = {
        'schema_version': 'piper_pi05_candidate_v2',
        'source_bag': str(bag_dir),
        'episode_id': validation['episode_id'],
        'metadata': validation['metadata'],
        'result': result_label,
        'task_prompt': '把香蕉放入纸盒',
        'requested_fps': fps,
        'effective_fps': effective_fps,
        'sample_count': len(aligned),
        'max_internal_gap_seconds': max_gap,
        'contiguous_segments': segment_info,
        'action_window_counts': {
            str(h): len(action_window_starts(segments, h)) for h in (5, 10, 25, 50)
        },
        'action_chunk_rule': '只能在同一连续采样网格片段内取完整序列；不补齐、不跨缺帧',
        'dropped_grid_points': dropped,
        'source_topic_counts': dict(counts),
        'raw_can_id_counts': {hex(k): v for k, v in sorted(raw_ids.items())},
        'source_timestamp_columns': list(topics),
        'image_columns': list(CAMERAS.values()),
        'position_names': NAMES,
        'position_units': ['rad'] * 6 + ['m'],
        'source_frame_ids': entities,
        'alignment': '各路取第三视角源时间之前最近数据，不插值，不填补缺失动作',
        'max_image_age_ms': 250,
        'max_vector_age_ms': 100,
        'format_valid': not quality_errors,
        'quality_errors': quality_errors,
        'training_ready': False,
        'pending': ['反馈实体归属', '夹爪零点与执行映射', 'openpi/LeRobot 版本和最终动作节拍'],
    }
    (output_dir / 'candidate_manifest.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bag_dir', type=Path)
    parser.add_argument('output_dir', type=Path, help='必须不存在；保存 JPEG、NPZ 和候选清单')
    parser.add_argument('--fps', type=float, default=5.0)
    args = parser.parse_args(argv)
    try:
        report = prepare(args.bag_dir, args.output_dir, args.fps)
    except Exception as exc:
        print(f'ERROR: 离线整理失败：{exc}')
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print('候选数据已保存；尚未导入 LeRobot 或用于训练，不访问 CAN。')
    return 0 if report['format_valid'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
