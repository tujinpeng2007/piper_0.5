import pytest
from types import SimpleNamespace

from piper.piper_dataset_timing_audit import inspect_action_windows, isolated_bag_for_read


def test_compressed_bag_is_isolated_and_source_is_not_modified(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'metadata.yaml').write_text('metadata')
    (source / 'original.db3.zstd').write_bytes(b'compressed')
    metadata = SimpleNamespace(compression_mode='FILE',
                               relative_file_paths=['original.db3.zstd'])
    with isolated_bag_for_read(source, metadata) as isolated:
        assert isolated != source
        assert (isolated / 'original.db3.zstd').read_bytes() == b'compressed'
        (isolated / 'original.db3').write_bytes(b'decompressed')
        assert not (source / 'original.db3').exists()
    assert not isolated.exists()
    assert (source / 'original.db3.zstd').read_bytes() == b'compressed'


def test_isolated_reader_rejects_parent_traversal(tmp_path):
    (tmp_path / 'metadata.yaml').write_text('metadata')
    metadata = SimpleNamespace(compression_mode='FILE', relative_file_paths=['../other'])
    with pytest.raises(ValueError), isolated_bag_for_read(tmp_path, metadata):
        pass


def test_one_image_can_anchor_multiple_high_rate_actions():
    targets = list(range(1_000_000_000, 4_000_000_001, 10_000_000))
    result = inspect_action_windows([1_000_000_000], targets, fps=20, horizon=50,
                                    end_ns=4_000_000_000)
    assert result['covered_windows'] == 1
    assert result['action_span_seconds'] == 2.45
    assert result['max_target_age_ms'] == 0


def test_long_source_gap_is_rejected_even_if_grid_misses_it():
    targets = [1_000_000_000, 1_010_000_000, 1_130_000_000, 1_140_000_000]
    result = inspect_action_windows([1_000_000_000], targets, fps=20, horizon=3,
                                    end_ns=2_000_000_000)
    assert result['covered_windows'] == 0
    assert result['rejected_windows'] == {'动作源存在较长间隔': 1}


def test_no_trailing_extrapolation_or_crossing_success():
    targets = list(range(1_000_000_000, 2_000_000_001, 10_000_000))
    result = inspect_action_windows([1_800_000_000, 1_900_000_000], targets,
                                    fps=10, horizon=3, end_ns=2_050_000_000)
    assert result['covered_windows'] == 1
    assert result['rejected_windows'] == {'超过结果标签': 1}
    result = inspect_action_windows([1_900_000_000], targets, fps=10,
                                    horizon=2, end_ns=3_000_000_000)
    assert result['covered_windows'] == 1
    result = inspect_action_windows([1_900_000_001], targets, fps=10,
                                    horizon=2, end_ns=3_000_000_000)
    assert result['rejected_windows'] == {'超出动作数据末尾': 1}


def test_action_source_age_is_bounded_and_reported():
    targets = [1_000_000_000, 1_080_000_000, 1_160_000_000]
    result = inspect_action_windows([1_020_000_000], targets, fps=20, horizon=3,
                                    end_ns=2_000_000_000)
    assert result['covered_windows'] == 1
    assert result['max_target_age_ms'] == 70
    assert result['reused_target_indices'] == 1
    with pytest.raises(ValueError):
        inspect_action_windows([1, 1], targets, fps=20, horizon=2, end_ns=2_000_000_000)
    with pytest.raises(ValueError):
        inspect_action_windows([1], [2, 1], fps=20, horizon=2, end_ns=2_000_000_000)
