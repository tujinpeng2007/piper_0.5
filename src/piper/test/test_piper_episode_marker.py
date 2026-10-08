import json

import pytest

from piper.piper_episode_marker import SCHEMA_VERSION, build_marker


def test_marker_payload_is_compact_json():
    payload = build_marker('demo-001', 'success', '香蕉已入盒', 123)
    assert json.loads(payload) == {
        'schema_version': SCHEMA_VERSION,
        'episode_id': 'demo-001',
        'label': 'success',
        'note': '香蕉已入盒',
        'stamp_ns': 123,
        'task': '',
        'scene_id': '',
        'attempt': 0,
        'operator': '',
    }


def test_marker_includes_dataset_metadata():
    payload = build_marker(
        'banana-a03-002', 'start', '', 123,
        task='banana_into_box', scene_id='scene-a03', attempt=2,
        operator='mips',
    )
    assert json.loads(payload)['task'] == 'banana_into_box'
    assert json.loads(payload)['scene_id'] == 'scene-a03'
    assert json.loads(payload)['attempt'] == 2
    assert json.loads(payload)['operator'] == 'mips'


def test_marker_rejects_unknown_label():
    with pytest.raises(ValueError):
        build_marker('demo-001', 'unknown', '', 123)


def test_marker_rejects_empty_episode_id():
    with pytest.raises(ValueError):
        build_marker('', 'start', '', 123)


def test_marker_rejects_negative_attempt():
    with pytest.raises(ValueError):
        build_marker('demo-001', 'start', '', 123, attempt=-1)
