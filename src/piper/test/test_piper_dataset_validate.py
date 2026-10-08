"""Tests for the offline rosbag episode validator."""

import json

from piper.piper_dataset_validate import (
    CAMERA_TOPICS,
    JOINT_TOPICS,
    MARKER_TOPIC,
    required_topics,
    validate_episode,
)


def _marker(label, **overrides):
    payload = {
        'schema_version': 'piper_pi05_episode_v1',
        'episode_id': 'banana-a01-001',
        'label': label,
        'note': '',
        'stamp_ns': 123,
        'task': 'banana_into_box',
        'scene_id': 'scene-a01',
        'attempt': 1,
        'operator': 'mips',
    }
    payload.update(overrides)
    return json.dumps(payload)


def _repeated(*labels):
    return [_marker(label) for label in labels for _ in range(3)]


def test_static_episode_accepts_cameras_and_complete_markers():
    summary = validate_episode(
        CAMERA_TOPICS + (MARKER_TOPIC,),
        _repeated('start', 'note', 'end'),
        'static',
    )
    assert summary['valid'] is True
    assert summary['marker_count'] == 9
    assert summary['episode_id'] == 'banana-a01-001'


def test_demonstration_requires_joint_topics_and_result_label():
    summary = validate_episode(
        CAMERA_TOPICS + (MARKER_TOPIC,),
        _repeated('start', 'success', 'end'),
        'demonstration',
    )
    assert summary['valid'] is False
    assert set(JOINT_TOPICS).issubset(summary['missing_topics'])


def test_demonstration_accepts_result_and_joint_topics():
    summary = validate_episode(
        CAMERA_TOPICS + JOINT_TOPICS + (MARKER_TOPIC,),
        _repeated('start', 'failure', 'end'),
        'demonstration',
    )
    assert summary['valid'] is True


def test_rejects_inconsistent_metadata_and_missing_retries():
    markers = _repeated('start', 'note', 'end')
    markers[-1] = _marker('end', scene_id='scene-other')
    summary = validate_episode(CAMERA_TOPICS + (MARKER_TOPIC,), markers, 'static')
    assert summary['valid'] is False
    assert any('scene_id 不一致' in error for error in summary['errors'])


def test_required_topics_rejects_unknown_mode():
    try:
        required_topics('unknown')
    except ValueError as exc:
        assert '未知录制模式' in str(exc)
    else:
        raise AssertionError('unknown mode must be rejected')
