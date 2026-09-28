"""Configure one physically isolated Piper arm for direct linkage."""

import argparse
import sys

import can


ROLE_BYTES = {'master': 0xFA, 'follower': 0xFC}
CONFIG_CAN_ID = 0x470


def _parser():
    parser = argparse.ArgumentParser(
        description='配置唯一上电的 Piper 为直连主臂/从臂；默认干跑且不发送 CAN 帧。',
    )
    parser.add_argument('--can-port', required=True, help='目标接口，例如 can_left')
    parser.add_argument('--role', choices=ROLE_BYTES, required=True, help='唯一上电臂要写入的角色')
    parser.add_argument('--apply', action='store_true', help='实际发送一次 0x470 配置帧')
    parser.add_argument('--single-powered-arm', action='store_true', help='确认同总线另一台 Piper 已物理断电')
    return parser


def payload(role):
    """Return the official zero-offset MasterSlaveConfig payload."""
    return bytes((ROLE_BYTES[role], 0, 0, 0, 0, 0, 0, 0))


def main(argv=None, bus_factory=can.Bus):
    args = _parser().parse_args(argv)
    frame = payload(args.role)
    role_text = '主臂（0xFA）' if args.role == 'master' else '从臂（0xFC）'
    print(f'目标：将 {args.can_port} 上唯一物理上电的 Piper 设置为{role_text}。')
    print('安全前提：同总线另一台 Piper 必须物理断电；旧 ROS 节点和 piper_teleop 均未运行。')
    print(f'准备帧：0x{CONFIG_CAN_ID:03X} [8] ' + ' '.join(f'{byte:02X}' for byte in frame))
    if not args.apply:
        print('干跑完成：未发送 CAN 帧。实际写入必须同时加入 --apply --single-powered-arm。')
        return 0
    if not args.single_powered_arm:
        print('拒绝发送：缺少 --single-powered-arm。')
        return 2

    bus = bus_factory(channel=args.can_port, interface='socketcan', receive_own_messages=False)
    try:
        bus.send(can.Message(arbitration_id=CONFIG_CAN_ID, data=frame, is_extended_id=False))
    finally:
        bus.shutdown()
    print('已发送一次官方 0x470 角色配置帧；请保持当前机械臂上电数秒后再断电。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
