import cv2
import numpy as np
import pytest

from piper.piper_dataset_streams import (
    encode_color_jpeg,
    next_emit_reference,
    validate_options,
)


def test_next_emit_reference_keeps_requested_phase():
    assert next_emit_reference(None, 10.0, 10.0) == 10.0
    assert next_emit_reference(10.0, 10.05, 10.0) is None
    assert next_emit_reference(10.0, 10.1, 10.0) == 10.1
    assert next_emit_reference(10.0, 10.133, 10.0) == 10.1
    assert next_emit_reference(10.0, 10.305, 10.0) == 10.3


def test_jpeg_encoder_produces_decodable_image():
    source = np.zeros((24, 32, 3), dtype=np.uint8)
    source[:, :, 1] = 200
    payload = encode_color_jpeg(source, 90)
    decoded = cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == source.shape


@pytest.mark.parametrize(
    'options',
    [
        (0.0, 90),
        (10.0, 0),
        (10.0, 101),
    ],
)
def test_invalid_options_are_rejected(options):
    with pytest.raises(ValueError):
        validate_options(*options)
