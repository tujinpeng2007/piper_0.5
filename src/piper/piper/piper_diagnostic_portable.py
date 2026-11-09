"""只用 NumPy/Pillow 读取跨环境诊断副本；不依赖 ROS 或 CAN。"""

import argparse
import hashlib
import io
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

from piper.piper_openpi_inputs import PiperInputs


class PortableDiagnosticDataset:
    """Read diagnostic-only windows with timestamp and image-integrity checks."""

    def __init__(self, directory):
        self.root = Path(directory).resolve()
        self.manifest = json.loads((self.root / 'manifest.json').read_text())
        m = self.manifest
        if (m.get('schema_version') != 'piper_diagnostic_portable_v2'
                or m.get('diagnostic_only') is not True or m.get('training_ready') is not False):
            raise ValueError('不是明确标记为非训练用途的诊断副本')
        if m.get('image_columns') != ['left_wrist', 'right_wrist', 'third_view']:
            raise ValueError('相机顺序不正确')
        if m.get('position_names') != [f'joint{i}' for i in range(1, 7)] + ['gripper']:
            raise ValueError('关节顺序不正确')
        if m.get('position_units') != ['rad'] * 6 + ['m']:
            raise ValueError('关节或夹爪单位不正确')
        if m.get('source_timestamp_columns') != [
                '/dataset/camera_gripper_left/color/image_jpeg',
                '/dataset/camera_gripper_right/color/image_jpeg',
                '/dataset/camera_third_view/color/image_jpeg',
                '/dataset/can_left/feedback_observed',
                '/dataset/can_left/action_target']:
            raise ValueError('源时间戳列不正确')
        metadata = m.get('metadata')
        if (not isinstance(metadata, dict) or metadata.get('task') != 'banana_into_box'
                or not isinstance(metadata.get('scene_id'), str) or not metadata['scene_id'].strip()):
            raise ValueError('任务或场景信息无效')
        if m.get('max_target_age_ms') != 100:
            raise ValueError('动作新鲜度约定不正确')
        count, horizon, fps = m['sample_count'], m['action_horizon'], m['action_fps_hypothesis']
        if (not isinstance(count, int) or isinstance(count, bool) or count < 1
                or not isinstance(horizon, int) or isinstance(horizon, bool) or horizon < 1
                or not isinstance(fps, (int, float)) or isinstance(fps, bool)
                or not math.isfinite(fps) or not 0 < fps <= 200):
            raise ValueError('样本数、动作长度或频率无效')
        arrays_path = self.root / 'arrays.npz'
        if hashlib.sha256(arrays_path.read_bytes()).hexdigest() != m.get('arrays_sha256'):
            raise ValueError('诊断数组文件校验失败')
        with np.load(arrays_path, allow_pickle=False) as data:
            self.arrays = {key: data[key] for key in data.files}
        required = {
            'state': (count, 7), 'actions': (count, horizon, 7),
            'observation_stamp_ns': (count,), 'observation_source_stamps_ns': (count, 5),
            'action_grid_stamps_ns': (count, horizon), 'action_source_stamps_ns': (count, horizon),
            'candidate_index': (count,), 'image_paths': (count, 3), 'image_sha256': (count, 3),
        }
        if any(key not in self.arrays or self.arrays[key].shape != shape
               for key, shape in required.items()):
            raise ValueError('诊断数组字段或形状不匹配')
        a = self.arrays
        for key in ('observation_stamp_ns', 'observation_source_stamps_ns',
                    'action_grid_stamps_ns', 'action_source_stamps_ns', 'candidate_index'):
            if a[key].dtype != np.int64:
                raise ValueError(f'{key} 必须为 int64')
        if (a['state'].dtype != np.float32 or a['actions'].dtype != np.float32
                or a['image_paths'].dtype.kind != 'U' or a['image_sha256'].dtype.kind != 'U'
                or not np.isfinite(a['state']).all() or not np.isfinite(a['actions']).all()
                or np.any(np.diff(a['observation_stamp_ns']) <= 0)
                or np.any(np.diff(a['candidate_index']) <= 0)):
            raise ValueError('状态、动作或样本顺序无效')
        if (np.any(a['observation_stamp_ns'] <= 0)
                or np.any(a['observation_source_stamps_ns'] <= 0)
                or np.any(a['action_source_stamps_ns'] <= 0)):
            raise ValueError('源时间戳无效')
        start, end = m['task_start_stamp_ns'], m['task_result_stamp_ns']
        if (not isinstance(start, int) or not isinstance(end, int) or start >= end
                or np.any(a['observation_stamp_ns'] < start)
                or np.any(a['action_grid_stamps_ns'][:, -1] > end)
                or np.any(a['action_source_stamps_ns'] < start)):
            raise ValueError('窗口超出原始回合范围')
        obs = a['observation_stamp_ns'][:, None]
        expected = obs + np.arange(horizon, dtype=np.int64) * round(1e9 / fps)
        action_age = a['action_grid_stamps_ns'] - a['action_source_stamps_ns']
        obs_age = obs - a['observation_source_stamps_ns']
        if (not np.array_equal(a['action_grid_stamps_ns'], expected)
                or np.any(action_age < 0) or np.any(action_age > 100_000_000)
                or np.any(np.diff(a['action_source_stamps_ns'], axis=1) < 0)
                or np.any(obs_age < 0) or np.any(obs_age[:, :3] > 250_000_000)
                or np.any(obs_age[:, 3:] > 100_000_000)
                or np.any(a['observation_source_stamps_ns'][:, 2] != a['observation_stamp_ns'])):
            raise ValueError('诊断数据存在未来数据、过期数据或时间网格不一致')

    def __len__(self):
        return self.manifest['sample_count']

    def __getitem__(self, index):
        a, m = self.arrays, self.manifest
        images = {}
        for i, name in enumerate(m['image_columns']):
            path = (self.root / str(a['image_paths'][index, i])).resolve()
            if not path.is_relative_to(self.root):
                raise ValueError('图像路径超出诊断目录')
            payload = path.read_bytes()
            if hashlib.sha256(payload).hexdigest() != str(a['image_sha256'][index, i]):
                raise ValueError(f'诊断图像校验失败：{name}')
            with Image.open(io.BytesIO(payload)) as image:
                images[name] = np.asarray(image.convert('RGB'))
        sample = PiperInputs(action_horizon=m['action_horizon'])({
            'state': a['state'][index], 'actions': a['actions'][index],
            'images': images, 'prompt': m['task_prompt'],
        })
        return sample, {
            'episode_id': m['episode_id'], 'scene_id': m['metadata']['scene_id'],
            'candidate_index': int(a['candidate_index'][index]),
            'observation_stamp_ns': int(a['observation_stamp_ns'][index]),
            'action_source_stamps_ns': a['action_source_stamps_ns'][index].tolist(),
            'diagnostic_only': True, 'training_ready': False,
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args(argv)
    try:
        dataset = PortableDiagnosticDataset(args.directory)
        for i in range(len(dataset)):
            dataset[i]
        print(json.dumps({'episode_id': dataset.manifest['episode_id'],
                          'windows_checked': len(dataset),
                          'diagnostic_only': True, 'training_ready': False},
                         ensure_ascii=False, indent=2))
    except (KeyError, OSError, ValueError) as exc:
        print(f'ERROR: {exc}')
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
