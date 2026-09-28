"""Read-only monitor for Piper firmware master-slave control frames."""

import argparse
import collections
import sys
import time

import can


LINKAGE_IDS = frozenset((0x151, 0x155, 0x156, 0x157, 0x159))


def _parser():
    parser = argparse.ArgumentParser(
        description='只读监听 Piper 同总线主从联动控制帧，不发送任何 CAN 帧。',
    )
    parser.add_argument('--can-port', required=True, help='要监听的 SocketCAN 接口，例如 can_left')
    parser.add_argument('--duration', type=float, default=15.0, help='监听秒数，0 表示持续监听')
    return parser


def _format(message):
    payload = ' '.join(f'{byte:02X}' for byte in message.data)
    return f'0x{message.arbitration_id:03X} [{message.dlc}] {payload}'


def main(argv=None, bus_factory=can.Bus, monotonic=time.monotonic):
    args = _parser().parse_args(argv)
    if args.duration < 0:
        raise SystemExit('--duration 必须大于等于 0')

    print(f'只读监听 {args.can_port}；仅统计 0x151、0x155~0x157、0x159。')
    print('不会发送 CAN 帧。拖动已确认的主臂时，直连模式应出现这些帧。')
    bus = bus_factory(channel=args.can_port, interface='socketcan', receive_own_messages=False)
    counts = collections.Counter()
    start = monotonic()
    try:
        while args.duration == 0 or monotonic() - start < args.duration:
            message = bus.recv(timeout=0.25)
            if message is None or message.is_error_frame:
                continue
            if message.arbitration_id not in LINKAGE_IDS:
                continue
            counts[message.arbitration_id] += 1
            print(_format(message))
    except KeyboardInterrupt:
        print('\n收到 Ctrl-C，停止监听。')
    finally:
        bus.shutdown()

    print('\n联动帧统计：')
    for arbitration_id in sorted(LINKAGE_IDS):
        print(f'  0x{arbitration_id:03X}: {counts[arbitration_id]}')
    if counts:
        print('结果：检测到官方主从联动控制帧。')
        return 0
    print('结果：未检测到联动控制帧；本工具没有改变机械臂状态。')
    print('说明：监听已正常完成。请确认拖动的是已配置主臂，并保留此输出用于排查。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
