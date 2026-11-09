import json
import hashlib
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
import rosbag2_py

from piper.piper_dataset_sample_preview import DiagnosticEpisode, _image_within_candidate, check_all, preview
from piper.piper_diagnostic_export import export_diagnostic
from piper.piper_diagnostic_portable import PortableDiagnosticDataset
from piper.piper_dataset_validate import DIRECT_TOPICS, RGB_TOPICS
from piper.piper_direct_dataset_prepare import NAMES


def _fixture(tmp_path, monkeypatch):
    import piper.piper_dataset_sample_preview as module

    bag = tmp_path / 'bag'
    bag.mkdir()
    candidate = tmp_path / 'candidate'
    candidate.mkdir()
    stamp = 10_000_000_000
    names = ['left_wrist', 'right_wrist', 'third_view']
    paths = []
    for index, name in enumerate(names):
        name = f'{name}.jpg'
        assert cv2.imwrite(str(candidate / name), np.full((8, 12, 3), index * 40, np.uint8))
        paths.append(name)
    manifest = {
        'schema_version': 'piper_pi05_candidate_v2', 'source_bag': str(bag),
        'position_names': NAMES, 'image_columns': names,
        'position_units': ['rad'] * 6 + ['m'],
        'metadata': {'scene_id': 'scene-test', 'task': 'banana_into_box'},
        'result': 'success',
        'source_timestamp_columns': list(RGB_TOPICS + DIRECT_TOPICS[:2]),
        'sample_count': 1, 'episode_id': 'test-001', 'task_prompt': '把香蕉放入纸盒',
    }
    (candidate / 'candidate_manifest.json').write_text(json.dumps(manifest))
    np.savez_compressed(candidate / 'aligned_candidate.npz', timestamp_ns=[stamp],
                        state=np.zeros((1, 7)), image_paths=np.asarray([paths]),
                        source_timestamp_ns=np.asarray([[stamp] * 5]))
    targets = [(t, [0.1] * 6 + [-0.001])
               for t in range(stamp, stamp + 3_000_000_001, 10_000_000)]
    labels = [json.dumps({'label': 'start', 'stamp_ns': stamp - 1_000_000_000}),
              json.dumps({'label': 'success', 'stamp_ns': stamp + 3_000_000_000})]
    streams = {DIRECT_TOPICS[1]: targets, DIRECT_TOPICS[0]: [(stamp, [0.0] * 7)]}
    streams.update({topic: [(stamp, (candidate / name).read_bytes())]
                    for topic, name in zip(RGB_TOPICS, paths)})
    monkeypatch.setattr(rosbag2_py, 'Info', lambda: SimpleNamespace(
        read_metadata=lambda *_: SimpleNamespace(compression_mode='')))
    monkeypatch.setattr(module, '_read', lambda _: ({}, streams, labels, {}, {}, []))
    monkeypatch.setattr(module, 'validate_episode', lambda *_: {
        'valid': True, 'episode_id': 'test-001', 'marker_label_counts': {'success': 3},
        'metadata': {'scene_id': 'scene-test', 'task': 'banana_into_box'}})
    return bag, candidate


def test_preview_builds_one_traceable_sample_without_export(tmp_path, monkeypatch):
    bag, candidate = _fixture(tmp_path, monkeypatch)
    before = sorted(p.name for p in candidate.iterdir())
    result = preview(bag, candidate, action_fps=20)
    assert result['state_shape'] == [7]
    assert result['action_shape'] == [50, 7]
    assert result['coverage_windows'] == 1
    assert result['training_ready'] is False and result['audit_only'] is True
    assert len(result['action_source_stamps_ns']) == 50
    assert all(s <= g for s, g in zip(result['action_source_stamps_ns'],
                                      result['action_grid_stamps_ns']))
    assert result['image_shapes']['base_0_rgb'] == [8, 12, 3]
    assert sorted(p.name for p in candidate.iterdir()) == before


def test_preview_rejects_future_or_stale_observation(tmp_path, monkeypatch):
    bag, candidate = _fixture(tmp_path, monkeypatch)
    stamp = 10_000_000_000
    np.savez_compressed(candidate / 'aligned_candidate.npz', timestamp_ns=[stamp],
                        state=np.zeros((1, 7)), image_paths=np.asarray([['a', 'b', 'c']]),
                        source_timestamp_ns=np.asarray([[stamp + 1, stamp, stamp, stamp, stamp]]))
    with pytest.raises(ValueError, match='未来数据或过期数据'):
        preview(bag, candidate, action_fps=20)


def test_preview_rejects_image_path_escape(tmp_path):
    candidate = tmp_path / 'candidate'
    candidate.mkdir()
    with pytest.raises(ValueError, match='超出候选目录'):
        _image_within_candidate(candidate, '../other.jpg')


def test_dataset_exposes_auditable_items_and_checks_original_bytes(tmp_path, monkeypatch):
    bag, candidate = _fixture(tmp_path, monkeypatch)
    dataset = DiagnosticEpisode(bag, candidate, action_fps=20)
    assert len(dataset) == 1
    sample, provenance = dataset[0]
    assert sample['actions'].shape == (50, 7)
    assert provenance['candidate_index'] == 0
    assert provenance['observation_source_stamps_ns'][2] == provenance['observation_stamp_ns']
    (candidate / 'third_view.jpg').write_bytes(b'changed')
    with pytest.raises(ValueError, match='与原始录包不一致'):
        dataset[0]


def test_dataset_rejects_state_not_matching_recorded_feedback(tmp_path, monkeypatch):
    bag, candidate = _fixture(tmp_path, monkeypatch)
    path = candidate / 'aligned_candidate.npz'
    with np.load(path, allow_pickle=False) as data:
        values = {key: data[key] for key in data.files}
    values['state'][0, 2] = 0.5
    np.savez_compressed(path, **values)
    dataset = DiagnosticEpisode(bag, candidate, action_fps=20)
    with pytest.raises(ValueError, match='状态与原始反馈不一致'):
        dataset[0]


def test_check_all_reports_count_and_rejects_a_changed_image(tmp_path, monkeypatch):
    bag, candidate = _fixture(tmp_path, monkeypatch)
    result = check_all(bag, candidate, action_fps=20)
    assert result['windows_checked'] == 1
    assert result['training_ready'] is False and result['audit_only'] is True
    (candidate / 'left_wrist.jpg').write_bytes(b'changed')
    with pytest.raises(ValueError, match='第 0 个覆盖窗口检查失败'):
        check_all(bag, candidate, action_fps=20)


def test_dataset_rejects_scene_mismatch_to_avoid_split_leakage(tmp_path, monkeypatch):
    bag, candidate = _fixture(tmp_path, monkeypatch)
    path = candidate / 'candidate_manifest.json'
    data = json.loads(path.read_text())
    data['metadata']['scene_id'] = 'wrong-scene'
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='标签、话题或回合不匹配'):
        DiagnosticEpisode(bag, candidate, action_fps=20)


def test_portable_diagnostic_roundtrip_and_no_overwrite(tmp_path, monkeypatch):
    bag, candidate = _fixture(tmp_path, monkeypatch)
    output = tmp_path / 'diagnostic'
    report = export_diagnostic(bag, candidate, output, action_fps=20)
    assert report['sample_count'] == 1 and report['training_ready'] is False
    portable = PortableDiagnosticDataset(output)
    sample, provenance = portable[0]
    assert sample['state'].shape == (7,) and sample['actions'].shape == (50, 7)
    assert provenance['diagnostic_only'] is True and provenance['training_ready'] is False
    np.testing.assert_allclose(sample['actions'][:, -1], -0.001)
    with pytest.raises(ValueError, match='拒绝覆盖'):
        export_diagnostic(bag, candidate, output, action_fps=20)


def test_portable_rejects_changed_image_and_future_action(tmp_path, monkeypatch):
    bag, candidate = _fixture(tmp_path, monkeypatch)
    output = tmp_path / 'diagnostic'
    export_diagnostic(bag, candidate, output, action_fps=20)
    dataset = PortableDiagnosticDataset(output)
    image = output / str(dataset.arrays['image_paths'][0, 0])
    image.write_bytes(b'changed')
    with pytest.raises(ValueError, match='图像校验失败'):
        dataset[0]
    path = output / 'arrays.npz'
    with np.load(path, allow_pickle=False) as data:
        arrays = {key: data[key] for key in data.files}
    arrays['action_source_stamps_ns'][0, 0] = arrays['action_grid_stamps_ns'][0, 0] + 1
    np.savez_compressed(path, **arrays)
    manifest_path = output / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['arrays_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='未来数据'):
        PortableDiagnosticDataset(output)


def test_portable_rejects_arrays_corruption_and_non_diagnostic_flag(tmp_path, monkeypatch):
    bag, candidate = _fixture(tmp_path, monkeypatch)
    output = tmp_path / 'diagnostic'
    export_diagnostic(bag, candidate, output, action_fps=20)
    manifest_path = output / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['training_ready'] = True
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='非训练用途'):
        PortableDiagnosticDataset(output)
    manifest['training_ready'] = False
    manifest_path.write_text(json.dumps(manifest))
    with (output / 'arrays.npz').open('ab') as stream:
        stream.write(b'corruption')
    with pytest.raises(ValueError, match='数组文件校验失败'):
        PortableDiagnosticDataset(output)
