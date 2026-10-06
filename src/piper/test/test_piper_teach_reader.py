import math
from piper.piper_teach_reader import decode_teach_joint_frame


def test_decode_shifted_teaching_joint_frame():
    data = (1234).to_bytes(4, 'big', signed=True) + (-2500).to_bytes(
        4, 'big', signed=True)
    decoded = decode_teach_joint_frame(0x2C5, data)
    assert math.isclose(decoded[1], 1234 * 0.001 * 3.141592653589793 / 180.0)
    assert math.isclose(decoded[2], -2500 * 0.001 * 3.141592653589793 / 180.0)


def test_ignore_non_joint_teaching_frame():
    assert decode_teach_joint_frame(0x2C1, bytes(8)) == {}
