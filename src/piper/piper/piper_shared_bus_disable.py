#!/usr/bin/env python3
"""Safely disable all Piper arms on a shared CAN bus.

The default is a dry run.  A real operation requires explicit acknowledgement
of mechanical support and shared-bus broadcast scope, and refuses to run while
motion-control processes are present.  The send sequence mirrors the original
``piper_single_ctrl`` disable service rather than constructing CAN frames.
"""

from __future__ import annotations

import subprocess
import time
from argparse import ArgumentParser
from typing import Iterable

from piper_sdk import C_PiperInterface

from piper.piper_enable_check import collect, report
from piper.piper_enable_status import EnableState


CONTROL_PROCESS_PATTERN = (
    'piper_(single_ctrl|teleop|teach_follow|joint_move)'
)


def running_control_processes() -> str:
    """Return matching motion-control processes, excluding this grep itself."""
    completed = subprocess.run(
        ['ps', '-eo', 'args='],
        check=False,
        capture_output=True,
        text=True,
    )
    import re
    return '\n'.join(
        line for line in completed.stdout.splitlines()
        if re.search(CONTROL_PROCESS_PATTERN, line)
        and 'piper_shared_bus_disable' not in line
    )


def disable_once(port: str) -> None:
    """Mirror the original Enable service's false branch exactly once."""
    piper = C_PiperInterface(can_name=port)
    piper.ConnectPort()
    try:
        # Keep this sequence aligned with PiperRosNode.handle_enable_service(false).
        piper.DisableArm(7)
        piper.GripperCtrl(0, 1000, 0x02, 0)
    finally:
        piper.DisconnectPort()


def check_port(port: str, duration: float = 3.0) -> EnableState:
    tracker = collect(port, duration=duration, timeout=0.5)
    return report(port, tracker)


def _parser() -> ArgumentParser:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        '--port', action='append', dest='ports', metavar='IFACE', required=True,
        help='要失能的共享 CAN 接口；可重复指定，例如 can_left 和 can_right',
    )
    parser.add_argument(
        '--apply', action='store_true',
        help='实际发送一次官方 SDK 失能序列；默认只预演',
    )
    parser.add_argument(
        '--mechanical-support-confirmed', action='store_true',
        help='确认所有机械臂均有可靠支撑，失能后不会因重力下落',
    )
    parser.add_argument(
        '--shared-can-broadcast-acknowledged', action='store_true',
        help='确认每条指定总线上的两台 Piper 都会同时收到失能广播',
    )
    return parser


def _print_plan(ports: Iterable[str]) -> None:
    ports = tuple(ports)
    print('共享 CAN 软件失能预演：')
    print('  接口：' + '、'.join(ports))
    print('  每个接口只执行一次官方 SDK DisableArm(7) + GripperCtrl(..., 0x02, 0)。')
    print('  同侧两台 Piper 都会收到广播；这不是单臂失能命令。')
    print('  不会发送运动目标，也不会启动 piper_teleop。')
    print('  实际执行后将自动进行 3 秒只读反馈复检。')


def main(args=None) -> int:
    options = _parser().parse_args(args)
    ports = tuple(dict.fromkeys(options.ports))
    _print_plan(ports)

    active = running_control_processes()
    if active:
        print('拒绝执行：检测到控制进程仍在运行：')
        print(active)
        print('请先在相应终端按 Ctrl-C，确认没有控制进程后再重新运行。')
        return 2

    if not options.apply:
        print('干跑完成：未发送任何 CAN 帧。实际执行需加入 --apply 和两个安全确认参数。')
        return 0

    if not options.mechanical_support_confirmed:
        print('拒绝执行：必须加入 --mechanical-support-confirmed。')
        return 2
    if not options.shared_can_broadcast_acknowledged:
        print('拒绝执行：必须加入 --shared-can-broadcast-acknowledged。')
        return 2

    for port in ports:
        print(f'正在对 {port} 执行一次官方 SDK 失能序列...')
        try:
            disable_once(port)
        except Exception as exc:  # SDK exceptions vary by adapter implementation.
            print(f'ERROR: {port} 失能命令未完成：{exc}')
            return 3
        time.sleep(0.3)

    states = {}
    for port in ports:
        print(f'正在只读复检 {port}（3 秒）...')
        try:
            states[port] = check_port(port)
        except Exception as exc:
            print(f'ERROR: 无法复检 {port}：{exc}')
            return 3

    if all(state is EnableState.DISABLED for state in states.values()):
        print('RESULT: 所有指定共享总线均报告 DISABLED。')
        return 0
    print('RESULT: 未得到全部 DISABLED；不要重试或循环发送，改用现场急停/物理断电并报告结果。')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
