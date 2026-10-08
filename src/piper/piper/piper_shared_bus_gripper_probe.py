#!/usr/bin/env python3
"""Probe one shared-CAN gripper target with a read-only default.

The tool is intentionally narrower than ``piper_teach_follow``: it never
sends joint targets, never enables an arm, and by default only reads the two
gripper feedback frames.  A real probe is limited to one 0x159 frame after
both arms report a position close to the requested target.
"""

from __future__ import annotations

import argparse
import subprocess
import time
from dataclasses import dataclass
from typing import Dict, Iterable

import can

from piper.piper_teach_follow import (
    GRIPPER_FEEDBACK_ID,
    decode_gripper_frame,
    encode_gripper_frame,
)


MASTER_FEEDBACK_OFFSET = 0x20
OBSERVED_SAFE_MAX_MM = 55.0
MAX_PROBE_STEP_MM = 2.0
CONTROL_PROCESS_PATTERN = 'piper_(single_ctrl|teleop|teach_follow|joint_move)'


@dataclass(frozen=True)
class GripperFeedback:
    """One fresh gripper feedback sample expressed in millimetres."""

    position_mm: float
    effort_nm: float
    status: int


def validate_probe(target_mm: float, master: GripperFeedback,
                   follower: GripperFeedback) -> list[str]:
    """Return conservative preflight failures for a single absolute target."""
    errors: list[str] = []
    if not 0.0 <= target_mm <= OBSERVED_SAFE_MAX_MM:
        errors.append(
            f'目标必须在 0~{OBSERVED_SAFE_MAX_MM:g} mm 的实测保守范围内')
    for role, feedback in (('主臂', master), ('从臂', follower)):
        delta = abs(target_mm - feedback.position_mm)
        if delta > MAX_PROBE_STEP_MM:
            errors.append(
                f'{role}当前 {feedback.position_mm:.3f} mm，与目标相差 '
                f'{delta:.3f} mm，超过 {MAX_PROBE_STEP_MM:g} mm 单次探测上限')
    return errors


def running_control_processes() -> str:
    """Return active movement-control processes, excluding this probe."""
    completed = subprocess.run(
        ['ps', '-eo', 'args='], check=False, capture_output=True, text=True)
    import re
    return '\n'.join(
        line for line in completed.stdout.splitlines()
        if re.search(CONTROL_PROCESS_PATTERN, line)
        and 'piper_shared_bus_gripper_probe' not in line
    )


def collect_feedback(bus: can.BusABC, timeout: float = 2.0) -> Dict[str, GripperFeedback]:
    """Read one fresh master and follower gripper feedback sample."""
    deadline = time.monotonic() + timeout
    readings: Dict[str, GripperFeedback] = {}
    while time.monotonic() < deadline and len(readings) < 2:
        message = bus.recv(timeout=min(0.2, max(0.0, deadline - time.monotonic())))
        if message is None or message.is_error_frame:
            continue
        for role, offset in (('master', MASTER_FEEDBACK_OFFSET), ('follower', 0)):
            decoded = decode_gripper_frame(message.arbitration_id, message.data, offset)
            if decoded is not None:
                readings[role] = GripperFeedback(
                    position_mm=decoded[0] * 1000.0,
                    effort_nm=decoded[1],
                    status=decoded[2],
                )
    return readings


def print_feedback(readings: Dict[str, GripperFeedback]) -> None:
    """Print collected feedback without exposing raw CAN bytes."""
    for role in ('master', 'follower'):
        feedback = readings.get(role)
        if feedback is None:
            print(f'  {role}: 未收到新鲜夹爪反馈')
            continue
        print(
            f'  {role}: 位置={feedback.position_mm:.3f} mm，'
            f'反馈扭矩={feedback.effort_nm:.3f} N·m，状态=0x{feedback.status:02X}')


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--can-port', required=True, help='共享 SocketCAN 接口，例如 can_left')
    parser.add_argument('--target-mm', type=float, required=True,
                        help='绝对目标位置（mm）；必须在实测保守范围内')
    parser.add_argument('--effort-nm', type=float, default=0.1,
                        help='仅实际探测时编码的低扭矩值，默认 0.1 N·m')
    parser.add_argument('--apply', action='store_true',
                        help='实际发送一条 0x159；默认只读预演')
    parser.add_argument('--empty-gripper-confirmed', action='store_true',
                        help='确认同侧两把夹爪均为空，周围无人和无物体')
    parser.add_argument('--mechanical-support-confirmed', action='store_true',
                        help='确认两台臂均有可靠支撑，急停可达')
    parser.add_argument('--shared-can-gripper-risk-acknowledged', action='store_true',
                        help='确认一条 0x159 可能影响同侧两把夹爪')
    return parser


def _missing_confirmations(options: argparse.Namespace) -> Iterable[str]:
    checks = (
        ('--empty-gripper-confirmed', options.empty_gripper_confirmed),
        ('--mechanical-support-confirmed', options.mechanical_support_confirmed),
        ('--shared-can-gripper-risk-acknowledged',
         options.shared_can_gripper_risk_acknowledged),
    )
    return [name for name, accepted in checks if not accepted]


def main(argv=None, bus_factory=can.Bus) -> int:
    """Run a dry preflight or a tightly bounded, one-frame probe."""
    options = _parser().parse_args(argv)
    if not 0.0 < options.effort_nm <= 1.0:
        print('ERROR: effort-nm 必须在 (0, 1] N·m 的低扭矩探测范围内。')
        return 2

    print(f'共享 CAN 夹爪探测：接口={options.can_port}，目标={options.target_mm:.3f} mm')
    print('本工具不发送关节帧、不使能或失能机械臂，也绝不循环发送。')
    if not options.apply:
        print('模式：只读预演；不会发送 0x159。')

    try:
        bus = bus_factory(
            channel=options.can_port, interface='socketcan', receive_own_messages=False)
    except (can.CanError, OSError) as exc:
        print(f'ERROR: 无法打开 {options.can_port}：{exc}')
        return 3
    try:
        bus.set_filters([
            {'can_id': GRIPPER_FEEDBACK_ID, 'can_mask': 0x7FF, 'extended': False},
            {'can_id': GRIPPER_FEEDBACK_ID + MASTER_FEEDBACK_OFFSET,
             'can_mask': 0x7FF, 'extended': False},
        ])
        readings = collect_feedback(bus)
        print('当前只读夹爪反馈：')
        print_feedback(readings)
        if set(readings) != {'master', 'follower'}:
            print('RESULT: 缺少主臂或从臂夹爪反馈；拒绝实际探测。')
            return 2

        errors = validate_probe(options.target_mm, readings['master'], readings['follower'])
        if errors:
            print('RESULT: 预检不通过：')
            for error in errors:
                print(f'  - {error}')
            return 2
        print(f'预检通过：两把夹爪到目标的预估位移均不超过 {MAX_PROBE_STEP_MM:g} mm。')
        if not options.apply:
            print('RESULT: 干跑完成，未发送任何 CAN 帧。')
            return 0

        active = running_control_processes()
        if active:
            print('RESULT: 检测到控制进程，拒绝发送：')
            print(active)
            return 2
        missing = list(_missing_confirmations(options))
        if missing:
            print('RESULT: 缺少实际探测确认：' + '、'.join(missing))
            return 2

        bus.send(can.Message(
            arbitration_id=0x159,
            data=encode_gripper_frame(options.target_mm * 0.001, options.effort_nm),
            is_extended_id=False,
        ))
        print('已发送一条 0x159 低扭矩夹爪探测帧；请立即观察同侧两把夹爪。')
        return 0
    except (can.CanError, OSError) as exc:
        print(f'ERROR: CAN 通信失败：{exc}')
        return 3
    finally:
        bus.shutdown()


if __name__ == '__main__':
    raise SystemExit(main())
