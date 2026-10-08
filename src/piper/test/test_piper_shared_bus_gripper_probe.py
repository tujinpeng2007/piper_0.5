from piper.piper_shared_bus_gripper_probe import (
    GripperFeedback,
    MAX_PROBE_STEP_MM,
    OBSERVED_SAFE_MAX_MM,
    _parser,
    validate_probe,
)


def feedback(position_mm):
    return GripperFeedback(position_mm=position_mm, effort_nm=0.0, status=0)


def test_default_mode_is_dry_run():
    args = _parser().parse_args(['--can-port', 'can_left', '--target-mm', '0.5'])
    assert not args.apply
    assert args.effort_nm == 0.1


def test_preflight_accepts_small_step_for_both_grippers():
    assert validate_probe(0.5, feedback(-1.4), feedback(0.4)) == []


def test_preflight_rejects_large_step():
    errors = validate_probe(5.0, feedback(-1.4), feedback(0.4))
    assert any('主臂当前' in error for error in errors)
    assert any('从臂当前' in error for error in errors)
    assert MAX_PROBE_STEP_MM == 2.0


def test_preflight_rejects_target_outside_observed_range():
    errors = validate_probe(OBSERVED_SAFE_MAX_MM + 0.1, feedback(55.0), feedback(55.0))
    assert any('实测保守范围' in error for error in errors)
