import cv2
import numpy as np
import pytest
import threading
from types import SimpleNamespace
from sensor_msgs.msg import Image
from rclpy.qos import ReliabilityPolicy

from piper.piper_dataset_streams import (
    encode_color_jpeg,
    next_emit_reference,
    output_qos,
    PiperDatasetStreams,
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


def test_recording_rgb_is_reliable_but_depth_stays_best_effort():
    assert output_qos('color').reliability == ReliabilityPolicy.RELIABLE
    assert output_qos('color').depth == 30
    assert output_qos('depth').reliability == ReliabilityPolicy.BEST_EFFORT


def test_rgb_publication_keeps_stream_lock_and_original_stamp():
    lock = threading.Lock()
    messages = []
    message = Image()
    message.header.stamp.sec = 123
    def publish(output):
        assert lock.locked()
        messages.append(output)
    node = SimpleNamespace(
        _stream_locks={'left_color': lock}, _schedule_lock=threading.Lock(),
        _last_emit={}, _last_source_stamp={}, _output_rate=5.0, _jpeg_quality=85,
        _bridge=SimpleNamespace(imgmsg_to_cv2=lambda *a, **k: np.zeros((24, 32, 3), np.uint8)),
        _output_publishers={'left_color': SimpleNamespace(publish=publish)},
    )
    PiperDatasetStreams._on_image(node, 'left_color', 'color', message)
    assert len(messages) == 1
    assert messages[0].header.stamp.sec == 123
    assert not lock.locked()
    # An older callback may be scheduled late; do not publish backwards time.
    node._last_emit.clear()
    message.header.stamp.sec = 122
    PiperDatasetStreams._on_image(node, 'left_color', 'color', message)
    assert len(messages) == 1
