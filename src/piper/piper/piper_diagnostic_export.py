"""将离线检查窗口导出为跨 Python 环境的诊断副本，不用于训练或执行。"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from piper.piper_dataset_sample_preview import DiagnosticEpisode
from piper.piper_dataset_validate import RGB_TOPICS


def export_diagnostic(bag_dir, candidate_dir, output_dir, action_fps):
    """Verify all inputs before creating a new, never-overwritten directory."""
    if output_dir.exists():
        raise ValueError(f'输出目录已存在，拒绝覆盖：{output_dir}')
    dataset = DiagnosticEpisode(bag_dir, candidate_dir, action_fps)
    if not dataset:
        raise ValueError('没有符合时间覆盖条件的窗口')
    state, actions, observations, sources, grids, action_sources = [], [], [], [], [], []
    candidate_indices, images, image_paths, image_hashes = [], [], [], []
    for i in range(len(dataset)):
        sample, info = dataset[i]
        state.append(sample['state'])
        actions.append(sample['actions'])
        observations.append(info['observation_stamp_ns'])
        sources.append(info['observation_source_stamps_ns'])
        grids.append(info['action_grid_stamps_ns'])
        action_sources.append(info['action_source_stamps_ns'])
        candidate_indices.append(info['candidate_index'])
        row_images, row_paths, row_hashes = [], [], []
        for camera_index, camera in enumerate(dataset.manifest['image_columns']):
            payload = dataset.sources[RGB_TOPICS[camera_index]][int(info['observation_source_stamps_ns'][camera_index])]
            row_images.append(payload)
            row_paths.append(f'images/{i:06d}_{camera}.jpg')
            row_hashes.append(hashlib.sha256(payload).hexdigest())
        images.append(row_images)
        image_paths.append(row_paths)
        image_hashes.append(row_hashes)

    output_dir.mkdir(parents=True, exist_ok=False)
    try:
        (output_dir / 'images').mkdir()
        for row, paths in zip(images, image_paths):
            for payload, relative in zip(row, paths):
                (output_dir / relative).write_bytes(payload)
        np.savez_compressed(
            output_dir / 'arrays.npz', state=np.stack(state), actions=np.stack(actions),
            observation_stamp_ns=np.asarray(observations, dtype=np.int64),
            observation_source_stamps_ns=np.asarray(sources, dtype=np.int64),
            action_grid_stamps_ns=np.asarray(grids, dtype=np.int64),
            action_source_stamps_ns=np.asarray(action_sources, dtype=np.int64),
            candidate_index=np.asarray(candidate_indices, dtype=np.int64),
            image_paths=np.asarray(image_paths), image_sha256=np.asarray(image_hashes),
        )
        manifest = {
            'schema_version': 'piper_diagnostic_portable_v2',
            'diagnostic_only': True, 'training_ready': False,
            'episode_id': dataset.episode_id, 'parent_result': dataset.parent_result,
            'metadata': dataset.manifest['metadata'],
            'task_prompt': dataset.manifest['task_prompt'],
            'source_bag': str(bag_dir), 'source_candidate': str(candidate_dir),
            'image_columns': dataset.manifest['image_columns'],
            'position_names': dataset.manifest['position_names'],
            'position_units': dataset.manifest['position_units'],
            'source_timestamp_columns': dataset.manifest['source_timestamp_columns'],
            'source_frame_ids': dataset.manifest.get('source_frame_ids', []),
            'arrays_sha256': hashlib.sha256((output_dir / 'arrays.npz').read_bytes()).hexdigest(),
            'sample_count': len(dataset), 'action_horizon': dataset.horizon,
            'action_fps_hypothesis': action_fps, 'max_target_age_ms': 100,
            'task_start_stamp_ns': dataset.start_ns, 'task_result_stamp_ns': dataset.end_ns,
            'limitations': [
                '仅供跨环境诊断，不得直接训练或控制机械臂',
                '动作频率为假设，100ms 内的目标可能复用，固件保持语义未确认',
                '反馈实体与夹爪执行映射未确认',
                '相同场景的回合不能拆分到训练与验证集',
            ],
        }
        (output_dir / 'manifest.json').write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    except Exception as exc:
        raise RuntimeError(f'诊断副本未完成；保留已创建目录供检查：{output_dir}') from exc
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bag_dir', type=Path)
    parser.add_argument('candidate_dir', type=Path)
    parser.add_argument('output_dir', type=Path)
    parser.add_argument('--action-fps', type=float, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(export_diagnostic(args.bag_dir, args.candidate_dir,
                                           args.output_dir, args.action_fps),
                         ensure_ascii=False, indent=2))
    except (KeyError, OSError, RuntimeError, ValueError) as exc:
        print(f'ERROR: {exc}')
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
