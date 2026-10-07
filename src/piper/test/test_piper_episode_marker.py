import json

import pytest

from piper.piper_episode_marker import build_marker


def test_marker_payload_is_compact_json():
    payload = build_marker('demo-001', 'success', '香蕉已入盒', 123)
    assert json.loads(payload) == {
        'episode_id': 'demo-001',
        'label': 'success',
        'note': '香蕉已入盒',
        'stamp_ns': 123,
    }


def test_marker_rejects_unknown_label():
    with pytest.raises(ValueError):
        build_marker('demo-001', 'unknown', '', 123)


def test_marker_rejects_empty_episode_id():
    with pytest.raises(ValueError):
        build_marker('', 'start', '', 123)
