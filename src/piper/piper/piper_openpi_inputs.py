"""Offline Piper input transform matching openpi's DataTransformFn protocol.

This module has no ROS, SocketCAN or model-loading dependency. It does not
certify a dataset or provide a robot execution interface.
"""

from dataclasses import dataclass

import numpy as np


CAMERA_MAP = {
    'third_view': 'base_0_rgb',
    'left_wrist': 'left_wrist_0_rgb',
    'right_wrist': 'right_wrist_0_rgb',
}


def _rgb(image):
    """Accept RGB uint8 or normalized RGB float, HWC or CHW; never BGR."""
    array = np.asarray(image)
    if array.ndim != 3:
        raise ValueError('RGB 图像必须为三维 HWC 或 CHW 数组')
    if array.shape[-1] != 3:
        if array.shape[0] != 3:
            raise ValueError('RGB 图像必须有三个通道')
        array = np.moveaxis(array, 0, -1)
    if min(array.shape[:2]) <= 0:
        raise ValueError('RGB 图像不能为空')
    if np.issubdtype(array.dtype, np.floating):
        if not np.isfinite(array).all() or array.min() < 0 or array.max() > 1:
            raise ValueError('浮点 RGB 必须为有限的 [0, 1] 数值')
        array = np.rint(array * 255).astype(np.uint8)
    elif array.dtype != np.uint8:
        raise ValueError('RGB 只接受 uint8 或 [0, 1] 浮点数')
    return np.array(array, copy=True, order='C')


def _positions(value, shape, label):
    array = np.asarray(value)
    if array.shape != shape or array.dtype.kind not in 'fiu':
        raise ValueError(f'{label} 必须为形状 {shape} 的数值数组')
    if not np.isfinite(array).all() or np.any(np.abs(array) > np.finfo(np.float32).max):
        raise ValueError(f'{label} 含非有限值或超出 float32 范围')
    return array.astype(np.float32, copy=True)


@dataclass(frozen=True)
class PiperInputs:
    """Map an unbatched, repacked sample to openpi's pre-normalization input.

    state: (7,), actions: (action_horizon, 7), images: CAMERA_MAP keys.
    Positions remain absolute rad/m, including signed gripper readings.
    Resizing, normalization, tokenization and model-dimension padding belong
    to the downstream openpi pipeline. Training windows must be checked by
    the caller; this transform cannot infer recording gaps from pixel arrays.
    """

    action_horizon: int = 50

    def __post_init__(self):
        if (not isinstance(self.action_horizon, int)
                or isinstance(self.action_horizon, bool) or self.action_horizon <= 0):
            raise ValueError('action_horizon 必须为正整数')

    def __call__(self, data):
        images = data.get('images')
        if not isinstance(images, dict) or set(images) != set(CAMERA_MAP):
            raise ValueError('images 必须明确包含 third_view、left_wrist、right_wrist 三路 RGB')
        prompt = data.get('prompt')
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError('prompt 必须是非空任务文本')
        if 'state' not in data:
            raise ValueError('缺少七维 state')
        result = {
            'state': _positions(data['state'], (7,), 'state'),
            'image': {target: _rgb(images[source]) for source, target in CAMERA_MAP.items()},
            'image_mask': {target: np.True_ for target in CAMERA_MAP.values()},
            'prompt': prompt,
        }
        if 'actions' in data:
            result['actions'] = _positions(
                data['actions'], (self.action_horizon, 7), 'actions')
        return result
