import numpy as np
import pytest

from piper.piper_openpi_inputs import CAMERA_MAP, PiperInputs


def sample():
    return {
        'state': np.array([0.1] * 6 + [-0.0007]),
        'images': {name: np.full((8, 12, 3), i * 50, dtype=np.uint8)
                   for i, name in enumerate(CAMERA_MAP)},
        'actions': np.tile([0.2] * 6 + [-0.0013], (50, 1)),
        'prompt': '把香蕉放入纸盒',
    }


def test_absolute_seven_dimensions_and_camera_mapping_are_preserved():
    data = sample()
    result = PiperInputs()(data)
    assert result['state'].shape == (7,)
    assert result['actions'].shape == (50, 7)
    assert result['actions'].dtype == np.float32
    np.testing.assert_allclose(result['actions'], data['actions'])
    np.testing.assert_allclose(result['state'], data['state'])
    for source, target in CAMERA_MAP.items():
        np.testing.assert_array_equal(result['image'][target], data['images'][source])
        assert result['image_mask'][target]
    result['actions'][0, 0] = 9
    assert data['actions'][0, 0] == 0.2
    assert result['prompt'] == data['prompt']
    assert set(result) == {'state', 'actions', 'image', 'image_mask', 'prompt'}


def test_observation_only_input_never_fabricates_actions():
    data = sample()
    del data['actions']
    result = PiperInputs()(data)
    assert 'actions' not in result


def test_lerobot_chw_normalized_rgb_is_converted_without_channel_swap():
    data = sample()
    image = np.zeros((3, 8, 12), dtype=np.float32)
    image[0] = 1  # red, not blue
    data['images']['third_view'] = image
    result = PiperInputs()(data)['image']['base_0_rgb']
    assert result.shape == (8, 12, 3)
    assert result.dtype == np.uint8
    np.testing.assert_array_equal(result[0, 0], [255, 0, 0])


@pytest.mark.parametrize('horizon', [0, -1, True, 2.5])
def test_invalid_horizon_is_rejected(horizon):
    with pytest.raises(ValueError):
        PiperInputs(horizon)


@pytest.mark.parametrize('key,value', [
    ('state', np.zeros(14)), ('state', [np.nan] * 7),
    ('state', [1e100] * 7), ('state', [True] * 7),
    ('actions', np.zeros((49, 7))), ('actions', np.zeros((50, 32))),
    ('actions', np.full((50, 7), np.inf)), ('prompt', ''), ('prompt', None),
])
def test_malformed_samples_are_rejected(key, value):
    data = sample()
    data[key] = value
    with pytest.raises(ValueError):
        PiperInputs()(data)


@pytest.mark.parametrize('image', [
    np.zeros((8, 12)), np.zeros((8, 12, 4)), np.zeros((0, 12, 3)),
    np.full((8, 12, 3), np.nan), np.full((8, 12, 3), 255.0),
    np.zeros((8, 12, 3), dtype=np.uint16),
])
def test_invalid_rgb_is_not_silently_cast(image):
    data = sample()
    data['images']['third_view'] = image
    with pytest.raises(ValueError):
        PiperInputs()(data)


def test_missing_camera_or_unknown_camera_is_not_padded_or_guessed():
    data = sample()
    del data['images']['right_wrist']
    with pytest.raises(ValueError):
        PiperInputs()(data)
    data['images']['unknown'] = np.zeros((8, 12, 3), dtype=np.uint8)
    with pytest.raises(ValueError):
        PiperInputs()(data)
