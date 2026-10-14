import json
from pathlib import Path

import pytest

from piper.piper_dataset_validate import (
    DIRECT_TOPICS, MARKER_TOPIC, RGB_TOPICS, required_topics, validate_episode,
)
from piper.piper_direct_dataset_prepare import (
    NAMES, action_window_starts, align_streams, latest_index, prepare, segment_ranges,
)


def markers():
    return [json.dumps({
        'schema_version': 'piper_pi05_episode_v1', 'episode_id': 'synthetic-001',
        'label': label, 'stamp_ns': stamp, 'note': '', 'task': 'banana_into_box',
        'scene_id': 'scene-synthetic', 'attempt': 1, 'operator': 'test',
    }) for label, stamp in [('start', 10_000_000_000), ('success', 14_000_000_000),
                           ('end', 15_000_000_000)] for _ in range(3)]


def test_direct_mode_requires_real_target_raw_feedback_and_three_rgb():
    expected = required_topics('direct_demonstration')
    assert set(expected) == set(RGB_TOPICS + DIRECT_TOPICS + (MARKER_TOPIC,))
    assert validate_episode(expected, markers(), 'direct_demonstration')['valid']
    result = validate_episode(RGB_TOPICS + DIRECT_TOPICS[:1] + (MARKER_TOPIC,),
                              markers(), 'direct_demonstration')
    assert not result['valid']
    assert DIRECT_TOPICS[1] in result['missing_topics']


def test_future_samples_and_stale_values_are_not_used():
    assert latest_index([100, 200], 150, 50) == 0
    assert latest_index([100, 200], 99, 50) is None
    assert latest_index([100, 200], 175, 50) is None
    streams = {t: [1_000_000_000, 1_200_000_000, 1_400_000_000]
               for t in RGB_TOPICS + DIRECT_TOPICS[:2]}
    streams[DIRECT_TOPICS[1]] = [1_300_000_000, 1_400_000_000]
    aligned, dropped = align_streams(streams, 1_000_000_000, 1_600_000_000, 5)
    assert [t for t, _ in aligned] == [1_400_000_000]
    assert sum(dropped.values()) == 2


def test_timestamp_reset_is_rejected_instead_of_silently_sorted():
    streams = {t: [100, 90] for t in RGB_TOPICS + DIRECT_TOPICS[:2]}
    with pytest.raises(ValueError, match='不严格递增'):
        align_streams(streams, 50, 150, 5)


def test_action_chunks_never_cross_even_one_missing_grid_point():
    segments = segment_ranges([0, 200, 400, 800, 1000, 1200, 1400], 200)
    assert segments == [(0, 3), (3, 7)]
    assert action_window_starts(segments, 3) == [0, 3, 4]
    assert action_window_starts(segments, 5) == []
    with pytest.raises(ValueError):
        segment_ranges([200, 100], 200)
    with pytest.raises(ValueError):
        action_window_starts(segments, 0)


def test_conflicting_episode_results_are_rejected():
    data = markers()
    bad = json.loads(data[3]); bad['label'] = 'failure'
    data.append(json.dumps(bad))
    assert not validate_episode(required_topics('direct_demonstration'), data,
                                'direct_demonstration')['valid']


def test_offline_rosbag_export_preserves_targets_and_never_claims_training_ready(tmp_path):
    import cv2
    import numpy as np
    import rosbag2_py
    from rclpy.serialization import serialize_message
    from sensor_msgs.msg import CompressedImage, JointState
    from std_msgs.msg import String

    bag = tmp_path / 'bag'
    writer = rosbag2_py.SequentialWriter()
    writer.open(rosbag2_py.StorageOptions(uri=str(bag), storage_id='sqlite3'),
                rosbag2_py.ConverterOptions('', ''))
    for topic in required_topics('direct_demonstration'):
        kind = ('sensor_msgs/msg/CompressedImage' if topic in RGB_TOPICS else
                'sensor_msgs/msg/JointState' if topic in DIRECT_TOPICS[:2] else 'std_msgs/msg/String')
        writer.create_topic(rosbag2_py.TopicMetadata(name=topic, type=kind, serialization_format='cdr'))
    _, jpeg = cv2.imencode('.jpg', np.zeros((32, 48, 3), dtype=np.uint8))
    for number in range(20):
        stamp = 10_000_000_000 + number * 200_000_000
        for topic in RGB_TOPICS:
            message = CompressedImage()
            message.header.stamp.sec = stamp // 1_000_000_000
            message.header.stamp.nanosec = stamp % 1_000_000_000
            message.format = 'jpeg'; message.data = jpeg.tobytes()
            writer.write(topic, serialize_message(message), stamp)
        for index, topic in enumerate(DIRECT_TOPICS[:2]):
            message = JointState()
            message.header.stamp.sec = stamp // 1_000_000_000
            message.header.stamp.nanosec = stamp % 1_000_000_000
            message.header.frame_id = 'can_left:unverified'
            message.name = list(NAMES)
            message.position = [number * 0.001 + index * 0.1] * 6 + [-0.0013]
            writer.write(topic, serialize_message(message), stamp)
        for key in (0x155, 0x156, 0x157, 0x159, 0x2A5, 0x2A6, 0x2A7, 0x2A8):
            message = String()
            message.data = json.dumps({'schema_version': 'piper_direct_can_v1',
                                      'can_port': 'can_left', 'can_id': key})
            writer.write(DIRECT_TOPICS[2], serialize_message(message), stamp)
    for payload in markers():
        message = String(); message.data = payload
        writer.write(MARKER_TOPIC, serialize_message(message), json.loads(payload)['stamp_ns'])
    del writer
    output = tmp_path / 'candidate'
    report = prepare(bag, output, 5)
    assert report['format_valid']
    assert report['training_ready'] is False
    assert report['sample_count'] == 20
    assert report['action_window_counts']['10'] == 11
    assert report['action_window_counts']['25'] == 0
    data = np.load(output / 'aligned_candidate.npz', allow_pickle=False)
    assert data['state'].shape == data['action'].shape == (20, 7)
    assert list(data['segment_id']) == [0] * 20
    assert data['action'][:, 0] - data['state'][:, 0] == pytest.approx([0.1] * 20)
    assert data['action'][:, -1] == pytest.approx([-0.0013] * 20)
    assert len(list((output / 'images').rglob('*.jpg'))) == 60
    assert (output / 'candidate_manifest.json').is_file()
    with pytest.raises(ValueError, match='拒绝覆盖'):
        prepare(bag, output, 5)
