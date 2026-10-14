import ast
from pathlib import Path
from types import SimpleNamespace

import can
import pytest

from piper import piper_direct_dataset_reader as reader


def payload(a, b):
    return a.to_bytes(4, 'big', signed=True) + b.to_bytes(4, 'big', signed=True)


def feed(tracker, times=(1.0, 1.001, 1.002, 1.003), gripper_mode=1):
    frames = [payload(90_000, -90_000), payload(0, 1000), payload(-1, 180_000),
              payload(-1300, 0)[:4] + bytes((0, 100, gripper_mode, 0))]
    out = None
    for key, data, now in zip(tracker.ids, frames, times):
        out = tracker.update(key, data, round(now * 1e9), now)
    return out


def test_separate_target_feedback_signed_units_and_source_stamp():
    feedback = reader.FrameSet(reader.FEEDBACK_IDS)
    target = reader.FrameSet(reader.COMMAND_IDS, command=True)
    assert feedback.update(0x155, payload(1000, 2000), 10, 1.0) is None
    assert not feedback.latest
    positions, stamp = feed(target)
    assert positions[:2] == pytest.approx([1.5707963268, -1.5707963268])
    assert positions[-1] == pytest.approx(-0.0013)  # retain zero offset; no clamping
    assert stamp == 1_003_000_000
    assert target.update(0x159, bytes(8), stamp + 1, 1.004) is None


def test_stale_or_skewed_fragments_are_not_published():
    tracker = reader.FrameSet(reader.COMMAND_IDS, command=True)
    assert feed(tracker, times=(1.0, 1.001, 1.002, 1.3)) is None
    assert feed(tracker, times=(2.0, 2.001, 2.002, 2.003)) is not None


def test_can_timestamp_skew_is_checked_even_when_recv_is_a_burst():
    tracker = reader.FrameSet(reader.COMMAND_IDS, command=True)
    for i, key in enumerate(tracker.ids):
        data = payload(0, 0) if i < 3 else bytes((0, 0, 0, 0, 0, 0, 1, 0))
        assert tracker.update(key, data, int((1 + i * 0.2) * 1e9), 3 + i * 0.001) is None


@pytest.mark.parametrize('mode', (0, 2, 0xFF))
def test_non_position_gripper_events_are_not_action_targets(mode):
    assert feed(reader.FrameSet(reader.COMMAND_IDS, command=True), gripper_mode=mode) is None


def test_missing_gripper_or_bad_payload_cannot_produce_seven_positions():
    tracker = reader.FrameSet(reader.FEEDBACK_IDS)
    for key in tracker.ids[:3]:
        assert tracker.update(key, payload(0, 0), 1_000_000_000, 1.0) is None
    assert tracker.update(tracker.ids[-1], bytes(7), 1_000_000_000, 1.0) is None


def test_zero_setting_frame_is_not_a_position_target():
    tracker = reader.FrameSet(reader.COMMAND_IDS, command=True)
    for key in tracker.ids[:3]:
        assert tracker.update(key, payload(0, 0), 1_000_000_000, 1.0) is None
    assert tracker.update(0x159, bytes((0, 0, 0, 0, 0, 100, 1, 0xAE)),
                          1_001_000_000, 1.001) is None


def test_read_loop_never_sends_and_stops_on_errors():
    frame = SimpleNamespace(is_error_frame=False, is_extended_id=False, is_remote_frame=False)
    seen = []

    class Bus:
        def __init__(self):
            self.frames = iter((frame, None))

        def recv(self, timeout):
            assert timeout == 0.0
            return next(self.frames)

        def send(self, *args, **kwargs):
            pytest.fail('只读接收器不得发送 CAN 帧')

    reader.receive_batch(Bus(), seen.append)
    assert seen == [frame]
    frame.is_error_frame = True
    with pytest.raises(can.CanOperationError):
        reader.receive_batch(Bus(), seen.append)


def test_cli_has_no_send_path():
    with pytest.raises(SystemExit):
        reader._parser().parse_args(['--can-port', 'can_left', '--send'])
    tree = ast.parse(Path(reader.__file__).read_text())
    calls = [n.func.attr for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    assert 'send' not in calls
