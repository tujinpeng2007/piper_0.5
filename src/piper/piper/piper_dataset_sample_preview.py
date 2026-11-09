"""从现有演示预览一条离线模型输入；不保存样本，也不访问 CAN。"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from piper.piper_dataset_timing_audit import (
    _select_action_indices, inspect_action_windows, isolated_bag_for_read,
)
from piper.piper_dataset_validate import DIRECT_TOPICS, RGB_TOPICS, validate_episode
from piper.piper_direct_dataset_prepare import NAMES, _read
from piper.piper_openpi_inputs import PiperInputs


def _image_within_candidate(candidate_dir, relative):
    root = candidate_dir.resolve()
    image_path = (root / str(relative)).resolve()
    if not image_path.is_relative_to(root):
        raise ValueError('图像路径超出候选目录')
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f'无法读取候选图像：{relative}')
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


class DiagnosticEpisode:
    """Read-only per-episode sequence; no claim of training or execution safety."""

    def __init__(self, bag_dir, candidate_dir, action_fps, horizon=50):
        import rosbag2_py

        self.candidate_dir = candidate_dir
        self.action_fps = action_fps
        self.horizon = horizon
        self.manifest = json.loads((candidate_dir / 'candidate_manifest.json').read_text())
        manifest = self.manifest
        if manifest.get('schema_version') != 'piper_pi05_candidate_v2':
            raise ValueError('需要 v2 候选清单')
        if Path(manifest['source_bag']).resolve() != bag_dir.resolve():
            raise ValueError('候选清单的源包与指定路径不一致')
        if manifest.get('position_names') != NAMES:
            raise ValueError('候选的七维顺序不符合约定')
        if manifest.get('position_units') != ['rad'] * 6 + ['m']:
            raise ValueError('候选的关节与夹爪单位不符合约定')
        if manifest.get('image_columns') != ['left_wrist', 'right_wrist', 'third_view']:
            raise ValueError('候选相机顺序不符合约定')
        if manifest.get('source_timestamp_columns') != list(RGB_TOPICS + DIRECT_TOPICS[:2]):
            raise ValueError('候选源时间戳列不符合约定')

        metadata = rosbag2_py.Info().read_metadata(str(bag_dir), 'sqlite3')
        with isolated_bag_for_read(bag_dir, metadata) as safe_bag:
            types, streams, markers, _, _, _ = _read(safe_bag)
        validation = validate_episode(types, markers, 'direct_demonstration')
        if (not validation['valid'] or validation['episode_id'] != manifest['episode_id']
                or validation.get('metadata') != manifest.get('metadata')):
            raise ValueError('源包与候选的标签、话题或回合不匹配')
        parsed = [json.loads(payload) for payload in markers]
        start = min(m['stamp_ns'] for m in parsed if m['label'] == 'start')
        label = 'success' if validation['marker_label_counts'].get('success') else 'failure'
        if manifest.get('result') != label:
            raise ValueError('候选结果与原始回合标签不一致')
        end = min(m['stamp_ns'] for m in parsed if m['label'] == label)
        if start >= end:
            raise ValueError('回合开始和结果的时间顺序无效')
        self.start_ns, self.end_ns = start, end
        self.episode_id = validation['episode_id']
        self.parent_result = label
        self.target_rows = [(int(stamp), values) for stamp, values in streams[DIRECT_TOPICS[1]]
                            if start <= stamp <= end]
        self.target_stamps = [stamp for stamp, _ in self.target_rows]
        self.sources = {}
        for topic in RGB_TOPICS + DIRECT_TOPICS[:1]:
            rows = streams[topic]
            indexed = {int(stamp): value for stamp, value in rows}
            if len(indexed) != len(rows):
                raise ValueError(f'源话题存在重复时间戳：{topic}')
            self.sources[topic] = indexed
        with np.load(candidate_dir / 'aligned_candidate.npz', allow_pickle=False) as data:
            self.observations = np.asarray(data['timestamp_ns'], dtype=np.int64)
            self.states = np.asarray(data['state'])
            self.image_paths = np.asarray(data['image_paths'])
            self.source_stamps = np.asarray(data['source_timestamp_ns'], dtype=np.int64)
        count = manifest['sample_count']
        if (self.observations.shape != (count,) or self.states.shape != (count, 7)
                or self.image_paths.shape != (count, 3) or self.source_stamps.shape != (count, 5)
                or not count or np.any(self.observations < start) or np.any(self.observations > end)):
            raise ValueError('候选数组形状或时间范围无效')
        coverage = inspect_action_windows(
            self.observations.tolist(), self.target_stamps,
            fps=action_fps, horizon=horizon, end_ns=end)
        self.step = round(1_000_000_000 / action_fps)
        self.eligible = []
        for row, observation in enumerate(self.observations.tolist()):
            indices, reason = _select_action_indices(
                observation, self.target_stamps, self.step, horizon, 100_000_000, end)
            if not reason:
                self.eligible.append((row, indices))
        if len(self.eligible) != coverage['covered_windows']:
            raise ValueError('候选窗口数量不一致')

    def __len__(self):
        return len(self.eligible)

    def __getitem__(self, index):
        row, indices = self.eligible[index]
        observation = int(self.observations[row])
        source_stamps = self.source_stamps[row]
        ages = observation - source_stamps
        if (source_stamps[2] != observation or np.any(ages < 0)
                or np.any(ages[:3] > 250_000_000) or np.any(ages[3:] > 100_000_000)):
            raise ValueError('候选观测使用了未来数据或过期数据')
        feedback = self.sources[DIRECT_TOPICS[0]].get(int(source_stamps[3]))
        if feedback is None or not np.array_equal(np.asarray(feedback, dtype=np.float32),
                                                  np.asarray(self.states[row], dtype=np.float32)):
            raise ValueError('候选状态与原始反馈不一致')
        if int(source_stamps[4]) not in self.target_stamps:
            raise ValueError('候选目标时间戳不在原始动作中')
        images = {}
        for i, name in enumerate(self.manifest['image_columns']):
            root = self.candidate_dir.resolve()
            path = (root / str(self.image_paths[row, i])).resolve()
            if not path.is_relative_to(root):
                raise ValueError('图像路径超出候选目录')
            source = self.sources[RGB_TOPICS[i]].get(int(source_stamps[i]))
            if source is None or not path.is_file() or path.read_bytes() != source:
                raise ValueError(f'候选图像与原始录包不一致：{name}')
            images[name] = _image_within_candidate(self.candidate_dir, self.image_paths[row, i])
        actions = np.asarray([self.target_rows[i][1] for i in indices], dtype=np.float32)
        sample = PiperInputs(action_horizon=self.horizon)({
            'state': self.states[row], 'actions': actions,
            'images': images, 'prompt': self.manifest['task_prompt'],
        })
        desired = [observation + k * self.step for k in range(self.horizon)]
        action_sources = [self.target_stamps[i] for i in indices]
        return sample, {
            'candidate_index': row,
            'observation_stamp_ns': observation,
            'observation_source_stamps_ns': source_stamps.tolist(),
            'action_grid_stamps_ns': desired,
            'action_source_stamps_ns': action_sources,
            'max_target_age_ms': max(a - b for a, b in zip(desired, action_sources)) / 1e6,
            'reused_target_indices': len(indices) - len(set(indices)),
        }


def preview(bag_dir, candidate_dir, action_fps, horizon=50):
    """Build one in-memory diagnostic sample, with conservative provenance."""
    dataset = DiagnosticEpisode(bag_dir, candidate_dir, action_fps, horizon)
    if not dataset:
        raise ValueError('给定动作节拍下没有符合审计条件的完整窗口')
    sample, provenance = dataset[0]
    return {
        'schema_version': 'piper_input_preview_v1',
        'episode_id': dataset.episode_id,
        **provenance,
        'action_fps_hypothesis': action_fps,
        'state_shape': list(sample['state'].shape),
        'action_shape': list(sample['actions'].shape),
        'image_shapes': {key: list(value.shape) for key, value in sample['image'].items()},
        'coverage_windows': len(dataset),
        'audit_only': True,
        'training_ready': False,
        'limitations': [
            '仅在内存检查结构，未接入 openpi 或 LeRobot',
            '动作节拍和目标保持语义尚未确定',
            '状态实体与夹爪执行映射尚未确认',
        ],
    }


def check_all(bag_dir, candidate_dir, action_fps, horizon=50):
    """Read every time-covered diagnostic sample; fail on the first mismatch."""
    dataset = DiagnosticEpisode(bag_dir, candidate_dir, action_fps, horizon)
    if not dataset:
        raise ValueError('给定动作节拍下没有符合审计条件的完整窗口')
    max_age = 0.0
    reused = 0
    for index in range(len(dataset)):
        try:
            sample, provenance = dataset[index]
        except (OSError, ValueError) as exc:
            raise ValueError(f'第 {index} 个覆盖窗口检查失败：{exc}') from exc
        if sample['actions'].shape != (horizon, 7) or sample['state'].shape != (7,):
            raise ValueError(f'第 {index} 个覆盖窗口维度不正确')
        max_age = max(max_age, provenance['max_target_age_ms'])
        reused += provenance['reused_target_indices']
    return {
        'schema_version': 'piper_input_check_v1',
        'episode_id': dataset.episode_id,
        'parent_result': dataset.parent_result,
        'action_fps_hypothesis': action_fps,
        'action_horizon': horizon,
        'windows_checked': len(dataset),
        'max_target_age_ms': max_age,
        'reused_target_indices': reused,
        'audit_only': True,
        'training_ready': False,
        'limitations': [
            '覆盖窗口互相重叠，不等于独立演示数量',
            '动作节拍和目标保持语义尚未确定',
            '状态实体与夹爪执行映射尚未确认',
            '尚未接入 openpi 或 LeRobot',
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bag_dir', type=Path)
    parser.add_argument('candidate_dir', type=Path)
    parser.add_argument('--action-fps', type=float, required=True,
                        help='仅作预览假设，不代表真实执行频率')
    parser.add_argument('--check-all', action='store_true',
                        help='逐条验证全部时间覆盖窗口及原包来源')
    args = parser.parse_args(argv)
    try:
        operation = check_all if args.check_all else preview
        report = operation(args.bag_dir, args.candidate_dir, args.action_fps)
    except (KeyError, OSError, ValueError) as exc:
        print(f'ERROR: {exc}')
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
