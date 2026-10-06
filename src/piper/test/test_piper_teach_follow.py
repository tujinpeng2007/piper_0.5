import math

from piper.piper_teach_follow import (
    MOTION_CTRL_DATA,
    decode_joint_frame,
    encode_joint_frame,
    minimum_jerk,
)


def test_decode_shifted_master_frame():
    data = (1234).to_bytes(4, 'big', signed=True) + (-2500).to_bytes(
        4, 'big', signed=True)
    decoded = decode_joint_frame(0x2C5, data)
    assert math.isclose(decoded[1], 1234 * 0.001 * math.pi / 180.0)
    assert math.isclose(decoded[2], -2500 * 0.001 * math.pi / 180.0)


def test_decode_does_not_accept_follower_frame():
    assert decode_joint_frame(0x2A5, bytes(8)) == {}


def test_encode_round_trip():
    encoded = encode_joint_frame(0.5, -0.25)
    decoded = decode_joint_frame(0x2C5, encoded)
    assert math.isclose(decoded[1], 0.5, abs_tol=3e-6)
    assert math.isclose(decoded[2], -0.25, abs_tol=3e-6)


def test_motion_mode_is_high_follow_joint_mode():
    assert MOTION_CTRL_DATA[:4] == bytes((0x01, 0x01, 0x64, 0xAD))


def test_minimum_jerk_has_zero_endpoints():
    assert minimum_jerk(0.0) == 0.0
    assert minimum_jerk(1.0) == 1.0
    assert 0.0 < minimum_jerk(0.5) < 1.0
