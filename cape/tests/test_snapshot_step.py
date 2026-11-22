from pathlib import Path

SNAPSHOT_STEP = Path(__file__).resolve().parents[2] / "guest" / "steps" / "snapshot"


def _body_after_the_functions() -> str:
    text = SNAPSHOT_STEP.read_text()
    return text[text.index('step "Shutting the guest down"') :]


def test_the_guest_idles_before_the_pre_snapshot_steps_so_the_last_thing_that_runs_is_the_quiet_pass():
    body = _body_after_the_functions()
    assert body.index('sleep "$IDLE_S"') < body.index("run_pre_snapshot_steps")


def test_the_snapshot_is_taken_right_after_the_pre_snapshot_steps():
    body = _body_after_the_functions()
    between = body[body.index("run_pre_snapshot_steps") : body.index("take_clean_snapshot")]
    assert "sleep" not in between
