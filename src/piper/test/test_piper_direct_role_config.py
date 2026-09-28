"""Tests for direct-link role configuration safeguards."""

from piper.piper_direct_role_config import CONFIG_CAN_ID, main, payload


class _Bus:
    def __init__(self):
        self.sent = []
        self.shutdown_called = False

    def send(self, message):
        self.sent.append(message)

    def shutdown(self):
        self.shutdown_called = True


def test_payloads_match_official_zero_offset_examples():
    assert payload('master') == bytes((0xFA, 0, 0, 0, 0, 0, 0, 0))
    assert payload('follower') == bytes((0xFC, 0, 0, 0, 0, 0, 0, 0))


def test_dry_run_does_not_open_a_can_bus(capsys):
    result = main(['--can-port', 'can_left', '--role', 'master'])

    assert result == 0
    assert '干跑完成：未发送 CAN 帧' in capsys.readouterr().out


def test_apply_requires_explicit_single_arm_confirmation(capsys):
    result = main(['--can-port', 'can_left', '--role', 'master', '--apply'])

    assert result == 2
    assert '拒绝发送' in capsys.readouterr().out


def test_apply_sends_one_standard_frame():
    bus = _Bus()
    result = main(
        ['--can-port', 'can_left', '--role', 'follower', '--apply', '--single-powered-arm'],
        bus_factory=lambda **kwargs: bus,
    )

    assert result == 0
    assert len(bus.sent) == 1
    assert bus.sent[0].arbitration_id == CONFIG_CAN_ID
    assert bytes(bus.sent[0].data) == payload('follower')
    assert not bus.sent[0].is_extended_id
    assert bus.shutdown_called
