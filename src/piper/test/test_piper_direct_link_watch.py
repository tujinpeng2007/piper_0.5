"""Tests for the read-only direct CAN linkage monitor."""

from piper.piper_direct_link_watch import LINKAGE_IDS, _format, main


class _Message:
    def __init__(self, arbitration_id, data=b'\x01\x02'):
        self.arbitration_id = arbitration_id
        self.data = data
        self.dlc = len(data)
        self.is_error_frame = False


class _Bus:
    def __init__(self, messages):
        self._messages = iter(messages)
        self.shutdown_called = False

    def recv(self, timeout):
        try:
            return next(self._messages)
        except StopIteration as error:
            raise KeyboardInterrupt from error

    def shutdown(self):
        self.shutdown_called = True


def test_format_uses_hex_can_id_and_payload():
    assert _format(_Message(0x155, b'\x01\xab')) == '0x155 [2] 01 AB'


def test_main_reports_detected_linkage_frame(capsys):
    bus = _Bus((_Message(0x2A1), _Message(0x155)))

    result = main(
        ['--can-port', 'can_left', '--duration', '0'],
        bus_factory=lambda **kwargs: bus,
    )

    output = capsys.readouterr().out
    assert result == 0
    assert '0x155 [2] 01 02' in output
    assert '结果：检测到官方主从联动控制帧。' in output
    assert bus.shutdown_called


def test_main_reports_no_linkage_frame(capsys):
    bus = _Bus((_Message(0x2A1),))

    result = main(
        ['--can-port', 'can_right', '--duration', '0'],
        bus_factory=lambda **kwargs: bus,
    )

    output = capsys.readouterr().out
    assert result == 0
    assert '结果：未检测到联动控制帧' in output
    assert '监听已正常完成' in output
    assert bus.shutdown_called


def test_expected_linkage_ids_are_official_motion_frames():
    assert LINKAGE_IDS == frozenset((0x151, 0x155, 0x156, 0x157, 0x159))
