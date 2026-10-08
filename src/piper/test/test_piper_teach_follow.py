import math

from piper.piper_teach_follow import (
    MOTION_CTRL_DATA,
    decode_gripper_frame,
    _parser,
    decode_joint_frame,
    encode_gripper_frame,
    encode_joint_frame,
    minimum_jerk,
)


def test_default_topics_include_master_and_follower_feedback():
    args = _parser().parse_args(['--can-port', 'can_left'])
    assert args.topic == '/joint_states_teach_shared'
    assert args.follower_topic == '/joint_states_follower_shared'
    assert not args.shared_can_gripper_risk_acknowledged


def test_decode_shifted_master_frame():
    data = (1234).to_bytes(4, 'big', signed=True) + (-2500).to_bytes(
        4, 'big', signed=True)
    decoded = decode_joint_frame(0x2C5, data)
    assert math.isclose(decoded[1], 1234 * 0.001 * math.pi / 180.0)
    assert math.isclose(decoded[2], -2500 * 0.001 * math.pi / 180.0)


def test_decode_does_not_accept_follower_frame():
    assert decode_joint_frame(0x2A5, bytes(8)) == {}


def test_decode_shifted_gripper_frame_uses_ros_metres():
    data = (42_500).to_bytes(4, 'big', signed=True) + (1_250).to_bytes(
        2, 'big', signed=True) + bytes((0xC0, 0x00))
    assert decode_gripper_frame(0x2C8, data) == (0.0425, 1.25, 0xC0)


def test_decode_gripper_rejects_non_gripper_frame():
    assert decode_gripper_frame(0x2C7, bytes(8)) is None


def test_encode_gripper_frame_uses_official_units_and_enable_mode():
    data = encode_gripper_frame(0.0425, 1.25)
    assert int.from_bytes(data[:4], 'big', signed=True) == 42_500
    assert int.from_bytes(data[4:6], 'big') == 1_250
    assert data[6:] == bytes((0x01, 0x00))


def test_encode_gripper_frame_can_encode_official_disable_clear_error_mode():
    data = encode_gripper_frame(0.0, 1.0, status_code=0x02)
    assert data[6:] == bytes((0x02, 0x00))


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
