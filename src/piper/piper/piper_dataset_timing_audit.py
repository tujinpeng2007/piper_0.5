"""只读审计候选观测与原始动作的时间覆盖，不导出训练样本。"""

import argparse
import bisect
import json
import math
import shutil
import tempfile
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from piper.piper_dataset_validate import DIRECT_TOPICS, validate_episode
from piper.piper_direct_dataset_prepare import _read


@contextmanager
def isolated_bag_for_read(bag_dir, metadata):
    """Prevent rosbag's file decompression from writing into the source bag."""
    if not metadata.compression_mode:
        yield bag_dir
        return
    with tempfile.TemporaryDirectory(prefix='piper_timing_audit_') as directory:
        copied = Path(directory)
        shutil.copy2(bag_dir / 'metadata.yaml', copied / 'metadata.yaml')
        for name in metadata.relative_file_paths:
            relative = Path(name)
            if relative.is_absolute() or '..' in relative.parts or not relative.name:
                raise ValueError('rosbag 数据文件路径无效')
            destination = copied / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bag_dir / relative, destination)
        yield copied


def _select_action_indices(observation, action_stamps, step, horizon, max_age_ns, end_ns):
    """Return source indices or a rejection reason for one validated time grid."""
    stop = observation + (horizon - 1) * step
    if stop > end_ns:
        return None, '超过结果标签'
    if not action_stamps or stop > action_stamps[-1]:
        return None, '超出动作数据末尾'
    first = bisect.bisect_right(action_stamps, observation) - 1
    last = bisect.bisect_right(action_stamps, stop) - 1
    if first < 0:
        return None, '缺少初始动作'
    has_gap = any(action_stamps[i + 1] - action_stamps[i] > max_age_ns
                  for i in range(first, last))
    if (action_stamps[last] < stop and last + 1 < len(action_stamps)
            and action_stamps[last + 1] - action_stamps[last] > max_age_ns):
        has_gap = True
    if has_gap:
        return None, '动作源存在较长间隔'
    selected = []
    for k in range(horizon):
        sample_ns = observation + k * step
        index = bisect.bisect_right(action_stamps, sample_ns) - 1
        if index < 0 or sample_ns - action_stamps[index] > max_age_ns:
            return None, '动作过期'
        selected.append(index)
    return selected, None


def inspect_action_windows(observation_stamps, action_stamps, *, fps, horizon,
                           max_age_ns=100_000_000, end_ns):
    """Count hypothetical windows; each target is bounded to past recorded data.

    A sampled value may reuse a recent observation for <= max_age_ns. This is
    only an audit policy, not evidence that the physical controller holds it.
    """
    if (not math.isfinite(fps) or fps <= 0 or fps > 200
            or not isinstance(horizon, int) or isinstance(horizon, bool) or horizon <= 0
            or not isinstance(max_age_ns, int) or max_age_ns <= 0):
        raise ValueError('频率、窗口长度或动作新鲜度无效')
    step = round(1_000_000_000 / fps)
    if any(b <= a for a, b in zip(action_stamps, action_stamps[1:])):
        raise ValueError('动作时间戳必须严格递增')
    if any(b <= a for a, b in zip(observation_stamps, observation_stamps[1:])):
        raise ValueError('观测时间戳必须严格递增')
    reasons = Counter()
    valid = 0
    max_used_age_ns = 0
    repeated_sources = 0
    for observation in observation_stamps:
        selected, reason = _select_action_indices(
            observation, action_stamps, step, horizon, max_age_ns, end_ns)
        if reason:
            reasons[reason] += 1
            continue
        valid += 1
        repeated_sources += len(selected) - len(set(selected))
        max_used_age_ns = max(max_used_age_ns, max(
            observation + k * step - action_stamps[index]
            for k, index in enumerate(selected)))
    return {
        'action_fps_hypothesis': fps,
        'action_horizon': horizon,
        'action_span_seconds': (horizon - 1) * step / 1e9,
        'observation_count': len(observation_stamps),
        'covered_windows': valid,
        'rejected_windows': dict(reasons),
        'max_target_age_ms': max_used_age_ns / 1e6 if valid else None,
        'reused_target_indices': repeated_sources,
    }


def audit(bag_dir, candidate_dir, rates=(5, 10, 20, 50), horizon=50):
    """Check provenance and report timing coverage; never write candidate files."""
    import rosbag2_py

    manifest = json.loads((candidate_dir / 'candidate_manifest.json').read_text())
    if manifest.get('schema_version') != 'piper_pi05_candidate_v2':
        raise ValueError('需要 v2 候选清单')
    if Path(manifest['source_bag']).resolve() != bag_dir.resolve():
        raise ValueError('候选清单的源包与指定路径不一致')
    metadata = rosbag2_py.Info().read_metadata(str(bag_dir), 'sqlite3')
    with isolated_bag_for_read(bag_dir, metadata) as safe_bag:
        types, streams, markers, _, _, _ = _read(safe_bag)
    validation = validate_episode(types, markers, 'direct_demonstration')
    if not validation['valid'] or validation['episode_id'] != manifest['episode_id']:
        raise ValueError('源包和候选的标签、话题或回合不匹配')
    parsed = [json.loads(payload) for payload in markers]
    start = min(m['stamp_ns'] for m in parsed if m['label'] == 'start')
    result = 'success' if validation['marker_label_counts'].get('success') else 'failure'
    end = min(m['stamp_ns'] for m in parsed if m['label'] == result)
    with np.load(candidate_dir / 'aligned_candidate.npz', allow_pickle=False) as data:
        observations = [int(t) for t in data['timestamp_ns']]
    if (len(observations) != manifest['sample_count'] or not observations
            or any(not start <= t <= end for t in observations)):
        raise ValueError('候选观测数或时间范围与清单不一致')
    targets = [int(stamp) for stamp, _ in streams[DIRECT_TOPICS[1]]
               if start <= stamp <= end]
    return {
        'schema_version': 'piper_timing_audit_v1',
        'episode_id': validation['episode_id'],
        'parent_result': result,
        'candidate_count': len(observations),
        'target_message_count': len(targets),
        'target_max_age_ms': 100,
        'audit_only': True,
        'training_ready': False,
        'limitations': [
            '动作频率仅为对照假设，尚未确定推理执行节拍',
            '采用不超过100ms的历史目标取样，不证明固件保持语义',
            '候选观测本身来源与质量尚未通过正式训练验收',
            '官方标准加载器按数据集FPS取动作，不自动支持本审计的双频方案',
        ],
        'rates': [inspect_action_windows(observations, targets, fps=rate,
                                       horizon=horizon, end_ns=end) for rate in rates],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bag_dir', type=Path)
    parser.add_argument('candidate_dir', type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(audit(args.bag_dir, args.candidate_dir), ensure_ascii=False, indent=2))
    except (KeyError, OSError, ValueError) as exc:
        print(f'ERROR: {exc}')
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
