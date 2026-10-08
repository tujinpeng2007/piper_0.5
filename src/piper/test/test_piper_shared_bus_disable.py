"""Tests for the guarded shared-CAN SDK disable tool."""

from piper.piper_enable_status import EnableState
from piper import piper_shared_bus_disable as subject


def test_dry_run_never_calls_sdk(monkeypatch, capsys):
    monkeypatch.setattr(subject, 'running_control_processes', lambda: '')
    monkeypatch.setattr(subject, 'disable_once', lambda port: (_ for _ in ()).throw(
        AssertionError('dry run must not send')))

    assert subject.main(['--port', 'can_left']) == 0
    assert '未发送任何 CAN 帧' in capsys.readouterr().out


def test_apply_requires_both_safety_confirmations(monkeypatch, capsys):
    monkeypatch.setattr(subject, 'running_control_processes', lambda: '')
    assert subject.main(['--port', 'can_left', '--apply']) == 2
    assert '--mechanical-support-confirmed' in capsys.readouterr().out


def test_apply_sends_once_per_unique_port_then_checks(monkeypatch):
    sent = []
    checked = []
    monkeypatch.setattr(subject, 'running_control_processes', lambda: '')
    monkeypatch.setattr(subject, 'disable_once', sent.append)
    monkeypatch.setattr(subject, 'check_port', lambda port: checked.append(port) or EnableState.DISABLED)
    monkeypatch.setattr(subject.time, 'sleep', lambda _: None)

    assert subject.main([
        '--port', 'can_left', '--port', 'can_left', '--port', 'can_right',
        '--apply', '--mechanical-support-confirmed',
        '--shared-can-broadcast-acknowledged',
    ]) == 0
    assert sent == ['can_left', 'can_right']
    assert checked == ['can_left', 'can_right']


def test_control_process_refuses_apply(monkeypatch, capsys):
    monkeypatch.setattr(subject, 'running_control_processes', lambda: 'piper_teach_follow')
    assert subject.main([
        '--port', 'can_left', '--apply', '--mechanical-support-confirmed',
        '--shared-can-broadcast-acknowledged',
    ]) == 2
    assert '拒绝执行' in capsys.readouterr().out


def test_disable_once_uses_original_service_sequence(monkeypatch):
    calls = []

    class FakePiper:
        def __init__(self, can_name):
            calls.append(('init', can_name))

        def ConnectPort(self):
            calls.append(('connect',))

        def DisconnectPort(self):
            calls.append(('disconnect',))

        def DisableArm(self, motor):
            calls.append(('disable', motor))

        def GripperCtrl(self, position, effort, mode, code):
            calls.append(('gripper', position, effort, mode, code))

    monkeypatch.setattr(subject, 'C_PiperInterface', FakePiper)
    subject.disable_once('can_left')
    assert calls == [
        ('init', 'can_left'), ('connect',), ('disable', 7),
        ('gripper', 0, 1000, 0x02, 0), ('disconnect',),
    ]
