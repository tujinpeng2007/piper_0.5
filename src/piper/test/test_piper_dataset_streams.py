import cv2
import numpy as np
import pytest
import threading
from types import SimpleNamespace
from sensor_msgs.msg import Image
from rclpy.qos import ReliabilityPolicy

from piper.piper_dataset_streams import (
    configure_opencv_threads,
    create_image_executor,
    encode_color_jpeg,
    next_emit_reference,
    output_qos,
    PiperDatasetStreams,
    StreamDiagnostics,
    validate_options,
)


def test_single_executor_is_not_a_thread_pool_with_one_worker(monkeypatch):
    import piper.piper_dataset_streams as streams
    single = object()
    monkeypatch.setattr(streams, 'SingleThreadedExecutor', lambda: single)
    calls = []
    monkeypatch.setattr(streams, 'MultiThreadedExecutor',
                        lambda **kw: calls.append(kw) or 'multi')
    assert create_image_executor(1) is single
    assert create_image_executor(6) == 'multi'
    assert calls == [{'num_threads': 6}]


@pytest.mark.parametrize('threads', [0, -1, True, 1.5, '1'])
def test_invalid_executor_thread_count_is_rejected(threads):
    with pytest.raises(ValueError):
        create_image_executor(threads)


def test_opencv_thread_budget_is_set_explicitly(monkeypatch):
    calls = []
    monkeypatch.setattr(cv2, 'setNumThreads', calls.append)
    configure_opencv_threads(1)
    assert calls == [1]


@pytest.mark.parametrize('threads', [0, -1, True, 1.5, '1'])
def test_invalid_opencv_thread_budget_is_rejected(threads):
    with pytest.raises(ValueError):
        configure_opencv_threads(threads)


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
        _diagnostics=StreamDiagnostics(['left_color'], 0),
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


def test_diagnostics_counts_skips_and_does_not_keep_images():
    stats = StreamDiagnostics(['left_color'], 10)
    stats.input('left_color', 1_000_000_000, 10)
    stats.input('left_color', 1_033_000_000, 10.04)
    stats.skip('left_color', 'throttle')
    stats.skip('left_color', 'busy')
    stats.skip('left_color', 'old_stamp')
    stats.skip('left_color', 'error')
    stats.output('left_color', 1_000_000_000, 5, 2)
    row = stats.snapshot(12)['left_color']
    assert row['input'] == 2 and row['output'] == 1
    assert row['input_hz'] == 1 and row['output_hz'] == 0.5
    assert row['input_gap_ms'] == 33
    assert row['callback_gap_ms'] == pytest.approx(40)
    assert row['encode_ms'] == 5 and row['publish_ms'] == 2
    assert all(row[key] == 1 for key in ['throttle', 'busy', 'old_stamp', 'error'])
    # Snapshot clears interval counters but keeps gap continuity across reports.
    stats.input('left_color', 1_533_000_000, 12.1)
    stats.output('left_color', 1_600_000_000, 3, 1)
    row = stats.snapshot(14)['left_color']
    assert row['input'] == 1 and row['input_gap_ms'] == 500
    assert row['output_gap_ms'] == 600
    assert row['encode_ms'] == 3


def test_diagnostics_reports_missing_stream_and_tolerates_callback_reordering():
    stats = StreamDiagnostics(['left_color', 'right_color'], 1)
    stats.input('left_color', 100_000_000, 1)
    stats.input('left_color', 90_000_000, 1.01)
    stats.input('left_color', 120_000_000, 1.02)
    rows = stats.snapshot(2)
    assert rows['left_color']['input_gap_ms'] == 20
    assert rows['right_color']['input_hz'] == 0
    assert rows['right_color']['output_hz'] == 0
