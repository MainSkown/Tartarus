import json
import os
import stat
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from guest_engine.builds import BuildStore
from guest_engine.errors import Conflict, GuestNotFound
from guest_engine.profile import PipelineStep
from guest_engine.sequencer import (
    INTERRUPTED_MESSAGE,
    SHUTDOWN_MESSAGE,
    BuildFailed,
    BuildJob,
    Sequencer,
)
from guest_engine.steps import PAUSE_EXIT_CODE, is_step_process

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
SECRET = "Sup3r-secret-pw"  # noqa: S105 - a fixture value


class Workshop:
    """A registry root, a folder of step scripts and a sequencer over them."""

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path / "guests"
        self.steps = tmp_path / "steps"
        self.steps.mkdir()
        self.profile_dir = tmp_path / "profile"
        self.profile_dir.mkdir()
        self.store = BuildStore(self.root)
        self.lock = threading.RLock()
        self.sequencer = self.service(self.lock)
        self.statuses: list[str] = []

    def service(self, lock=None, **options) -> Sequencer:
        """A sequencer over this workshop's builds, as a freshly started control service has."""
        return Sequencer(
            self.store, lock or threading.RLock(), {"PATH": "/usr/bin:/bin"}, **options
        )

    def step(self, name: str, body: str) -> None:
        path = self.steps / name
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def job(self, **hooks) -> BuildJob:
        return BuildJob(
            find_step=lambda name: (self.steps / name) if (self.steps / name).exists() else None,
            profile_dir=self.profile_dir,
            secrets=(SECRET,),
            on_status=lambda build: self.statuses.append(build.status),
            **hooks,
        )

    def new(self, *names, guest="alpha", timeout_s=30, **hooks):
        (self.root / guest).mkdir(parents=True, exist_ok=True)
        (self.root / guest / "guest.json").write_text("{}")
        pipeline = [PipelineStep(name, False, timeout_s, 1) for name in names]
        return self.sequencer.begin(guest, "build", pipeline, self.job(**hooks), now=NOW)

    def finish(self, build_id):
        assert self.sequencer.wait(build_id, timeout=20), "the build did not end"
        return self.store.load(build_id)

    def log(self, build_id) -> list[str]:
        return self.store.tail(build_id, 1000)


@pytest.fixture
def shop(tmp_path):
    return Workshop(tmp_path)


def statuses_of(build):
    return [step.status for step in build.steps]


# --- a build that works ------------------------------------------------------------------


def test_the_steps_run_in_order_and_the_build_succeeds(shop):
    shop.step("one", "echo one >> $TT_GUEST_DIR/order")
    shop.step("two", "echo two >> $TT_GUEST_DIR/order")

    build = shop.finish(shop.new("one", "two").id)

    assert build.status == "succeeded"
    assert statuses_of(build) == ["succeeded", "succeeded"]
    assert (shop.root / "alpha" / "order").read_text() == "one\ntwo\n"
    assert build.percent == 100
    assert build.pause is None
    assert all(step.started and step.finished and step.exit_code == 0 for step in build.steps)


def test_a_step_is_told_its_inputs_by_environment_variables(shop):
    shop.step(
        "show",
        'echo "dir=$TT_GUEST_DIR json=$TT_GUEST_JSON profile=$TT_PROFILE_DIR step=$TT_STEP"\n'
        'echo "state=$TT_STATE_FILE log=$TT_LOG id=$TT_BUILD_ID"\n'
        'echo "context=$TT_CONTEXT_JSON build=$TT_BUILD_DIR"',
    )

    started = shop.new("show")
    build = shop.finish(started.id)
    build_dir = shop.root / "alpha" / "builds" / build.id

    assert shop.log(build.id)[1:4] == [
        f"dir={shop.root / 'alpha'} json={shop.root / 'alpha' / 'guest.json'} "
        f"profile={shop.profile_dir} step=show",
        f"state={build_dir / 'build.json'} log={build_dir / 'log'} id={build.id}",
        f"context={build_dir / 'context.json'} build={build_dir}",
    ]


def test_every_output_line_goes_to_the_log_file_the_step_was_told_about(shop):
    shop.step("noisy", "echo plain\necho err >&2\necho 'LOG from the step'\necho 'STEP doing it'")

    build = shop.finish(shop.new("noisy").id)

    log = (shop.root / "alpha" / "builds" / build.id / "log").read_text()
    for line in ("plain", "err", "LOG from the step", "STEP doing it"):
        assert line in log.splitlines()


def test_progress_and_step_lines_update_the_record_while_the_step_runs(shop):
    gate = shop.root / "gate"
    shop.step(
        "slow",
        f"echo 'STEP Copying the disk'\necho 'PROGRESS 40'\n"
        f"while [ ! -e {gate} ]; do sleep 0.05; done",
    )
    started = shop.new("slow")

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        seen = shop.store.load(started.id)
        if seen.steps[0].progress == 40:
            break
        time.sleep(0.05)

    assert seen.status == "running"
    assert seen.message == "Copying the disk"
    assert seen.percent == 40
    assert seen.steps[0].status == "running"
    gate.write_text("go")
    assert shop.finish(started.id).status == "succeeded"


def test_percent_follows_the_weights_of_the_entries(shop):
    shop.step("quick", "true")
    shop.step("stuck", "exit 1")
    (shop.root / "alpha").mkdir(parents=True)
    (shop.root / "alpha" / "guest.json").write_text("{}")
    pipeline = [PipelineStep("quick", False, 30, 1), PipelineStep("stuck", False, 30, 3)]

    build = shop.finish(shop.sequencer.begin("alpha", "build", pipeline, shop.job()).id)

    assert build.status == "failed"
    assert build.percent == 25


def test_the_hooks_see_running_then_the_final_status(shop):
    shop.step("one", "true")

    shop.finish(shop.new("one").id)

    assert shop.statuses == ["running", "succeeded"]


# --- a step that fails -------------------------------------------------------------------


def test_a_failing_step_fails_the_build_with_the_last_log_lines(shop):
    shop.step("ok", "true")
    shop.step("bad", "echo first line\necho the disk is full >&2\nexit 7")
    shop.step("never", "echo ran >> $TT_GUEST_DIR/never")

    build = shop.finish(shop.new("ok", "bad", "never").id)

    assert build.status == "failed"
    assert statuses_of(build) == ["succeeded", "failed", "pending"]
    assert build.step == 1
    assert build.steps[1].exit_code == 7
    assert "bad" in build.message
    assert "exit code 7" in build.message
    assert "the disk is full" in build.message
    assert not (shop.root / "alpha" / "never").exists()
    assert shop.statuses == ["running", "failed"]


def test_the_message_holds_only_the_tail_of_a_long_log(shop):
    shop.step("bad", "i=0\nwhile [ $i -lt 100 ]; do echo line$i; i=$((i+1)); done\nexit 1")

    build = shop.finish(shop.new("bad").id)

    assert "line99" in build.message
    assert "line10\n" not in build.message + "\n"


def test_a_missing_step_file_fails_the_build_naming_the_step(shop):
    build = shop.finish(shop.new("ghost").id)

    assert build.status == "failed"
    assert "ghost" in build.message
    assert "not found" in build.message or "missing" in build.message


def test_a_step_killed_by_a_signal_says_so(shop):
    shop.step("killed", "kill -KILL $$")

    build = shop.finish(shop.new("killed").id)

    assert build.status == "failed"
    assert "signal" in build.message


# --- resume and restart ------------------------------------------------------------------


def fix_after_first_failure(shop):
    shop.step("first", "echo first >> $TT_GUEST_DIR/runs")
    shop.step("second", "echo second >> $TT_GUEST_DIR/runs\n[ -e $TT_GUEST_DIR/fixed ]")
    shop.step("third", "echo third >> $TT_GUEST_DIR/runs")


def test_resume_reruns_the_failed_step_and_carries_on_without_the_finished_ones(shop):
    fix_after_first_failure(shop)
    build = shop.finish(shop.new("first", "second", "third").id)
    assert build.status == "failed"
    (shop.root / "alpha" / "fixed").write_text("")

    shop.sequencer.resume(build.id, shop.job())
    build = shop.finish(build.id)

    assert build.status == "succeeded"
    assert (shop.root / "alpha" / "runs").read_text().split() == [
        "first",
        "second",
        "second",
        "third",
    ]
    assert build.message == ""
    assert shop.statuses == ["running", "failed", "running", "succeeded"]


def test_a_resumed_step_has_a_fresh_record(shop):
    fix_after_first_failure(shop)
    build = shop.finish(shop.new("first", "second", "third").id)
    (shop.root / "alpha" / "fixed").write_text("")

    shop.sequencer.resume(build.id, shop.job())
    build = shop.finish(build.id)

    assert build.steps[1].exit_code == 0
    assert build.steps[1].progress == 100


def test_restart_says_so_in_the_log(shop):
    fix_after_first_failure(shop)
    build = shop.finish(shop.new("first", "second", "third").id)

    shop.sequencer.restart(build.id, shop.job())
    shop.finish(build.id)

    assert "== restarting from the first step" in shop.log(build.id)


def test_restart_runs_every_step_again_from_the_first(shop):
    fix_after_first_failure(shop)
    build = shop.finish(shop.new("first", "second", "third").id)
    (shop.root / "alpha" / "fixed").write_text("")

    shop.sequencer.restart(build.id, shop.job())
    build = shop.finish(build.id)

    assert build.status == "succeeded"
    assert (shop.root / "alpha" / "runs").read_text().split() == [
        "first",
        "second",
        "first",
        "second",
        "third",
    ]


def test_the_failed_attempts_log_survives_a_resume(shop):
    fix_after_first_failure(shop)
    build = shop.finish(shop.new("first", "second", "third").id)
    failed_log = shop.log(build.id)
    (shop.root / "alpha" / "fixed").write_text("")

    shop.sequencer.resume(build.id, shop.job())
    shop.finish(build.id)

    assert shop.log(build.id)[: len(failed_log)] == failed_log


@pytest.mark.parametrize("action", ["resume", "restart", "continue_after_pause"])
def test_a_build_that_succeeded_cannot_be_resumed_restarted_or_continued(shop, action):
    shop.step("one", "true")
    build = shop.finish(shop.new("one").id)

    with pytest.raises(Conflict, match="succeeded"):
        getattr(shop.sequencer, action)(build.id, shop.job())


def test_an_unknown_build_is_not_found(shop):
    with pytest.raises(GuestNotFound):
        shop.sequencer.resume("b-nothing", shop.job())


# --- pause and continue ------------------------------------------------------------------


def pausing_step(shop):
    shop.step(
        "ask",
        "if [ -e $TT_GUEST_DIR/answered ]; then echo 'STEP thanks'; exit 0; fi\n"
        "echo 'PROGRESS 30'\n"
        "echo 'PAUSE Toggle the switch, then press continue'\n"
        "exit 75",
    )
    shop.step("after", "echo after >> $TT_GUEST_DIR/runs")


def test_exit_code_75_pauses_the_build_with_the_instructions_the_step_wrote(shop):
    pausing_step(shop)

    build = shop.finish(shop.new("ask", "after").id)

    assert PAUSE_EXIT_CODE == 75
    assert build.status == "paused"
    assert build.pause == {"instructions": "Toggle the switch, then press continue"}
    assert statuses_of(build) == ["paused", "pending"]
    assert build.step == 0
    assert build.steps[0].exit_code == 75
    assert not (shop.root / "alpha" / "runs").exists()
    assert shop.statuses == ["running", "paused"]


def test_a_pause_without_instructions_gets_a_default_text(shop):
    shop.step("quiet", "exit 75")

    build = shop.finish(shop.new("quiet").id)

    assert build.status == "paused"
    assert build.pause["instructions"].strip() != ""


def test_continue_reruns_the_paused_step_and_carries_on(shop):
    pausing_step(shop)
    build = shop.finish(shop.new("ask", "after").id)
    (shop.root / "alpha" / "answered").write_text("")

    shop.sequencer.continue_after_pause(build.id, shop.job())
    build = shop.finish(build.id)

    assert build.status == "succeeded"
    assert build.pause is None
    assert (shop.root / "alpha" / "runs").read_text() == "after\n"


def test_continue_that_pauses_again_stays_paused(shop):
    pausing_step(shop)
    build = shop.finish(shop.new("ask", "after").id)

    shop.sequencer.continue_after_pause(build.id, shop.job())
    build = shop.finish(build.id)

    assert build.status == "paused"
    assert build.pause is not None


def test_resume_works_on_a_paused_build_too(shop):
    pausing_step(shop)
    build = shop.finish(shop.new("ask", "after").id)
    (shop.root / "alpha" / "answered").write_text("")

    shop.sequencer.resume(build.id, shop.job())

    assert shop.finish(build.id).status == "succeeded"


def test_continue_needs_a_paused_build(shop):
    shop.step("bad", "exit 1")
    build = shop.finish(shop.new("bad").id)

    with pytest.raises(Conflict, match="failed"):
        shop.sequencer.continue_after_pause(build.id, shop.job())


def test_the_exit_code_not_the_pause_text_decides(shop):
    shop.step("chatty", "echo 'PAUSE just a remark'")

    assert shop.finish(shop.new("chatty").id).status == "succeeded"


def test_a_paused_build_holds_the_one_build_slot(shop):
    pausing_step(shop)
    shop.finish(shop.new("ask", "after").id)

    with pytest.raises(Conflict, match="alpha"):
        shop.new("after", guest="bravo")


# --- timeouts ----------------------------------------------------------------------------


def test_a_step_past_its_timeout_fails_the_build_naming_the_step(shop):
    pid_file = shop.root / "pid"
    shop.root.mkdir(parents=True, exist_ok=True)
    shop.step("hang", f"sleep 60 &\necho $! > {pid_file}\nwait")
    started = time.monotonic()

    build = shop.finish(shop.new("hang", timeout_s=1).id)

    assert time.monotonic() - started < 15
    assert build.status == "failed"
    assert "hang" in build.message
    assert "timed out after 1" in build.message
    assert build.steps[0].status == "failed"
    helper = int(pid_file.read_text())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and Path(f"/proc/{helper}/stat").exists():
        if Path(f"/proc/{helper}/stat").read_text().split()[2] == "Z":
            break
        time.sleep(0.05)
    assert not Path(f"/proc/{helper}").exists() or (
        Path(f"/proc/{helper}/stat").read_text().split()[2] == "Z"
    )


# --- one build at a time -----------------------------------------------------------------


def blocking_step(shop):
    gate = shop.root / "gate"
    shop.root.mkdir(parents=True, exist_ok=True)
    shop.step("block", f"while [ ! -e {gate} ]; do sleep 0.05; done")
    return gate


def test_a_second_build_is_refused_while_one_runs_and_the_message_names_it(shop):
    gate = blocking_step(shop)
    first = shop.new("block")

    with pytest.raises(Conflict, match="alpha"):
        shop.new("block", guest="bravo")

    gate.write_text("go")
    shop.finish(first.id)
    assert shop.new("block", guest="bravo")  # the slot is free again


def test_resuming_one_build_is_refused_while_another_runs(shop):
    shop.step("bad", "exit 1")
    failed = shop.finish(shop.new("bad", guest="alpha").id)
    gate = blocking_step(shop)
    running = shop.new("block", guest="bravo")

    with pytest.raises(Conflict, match="bravo"):
        shop.sequencer.resume(failed.id, shop.job())

    gate.write_text("go")
    shop.finish(running.id)


@pytest.mark.parametrize("action", ["resume", "restart", "continue_after_pause"])
def test_a_running_build_cannot_be_resumed_restarted_or_continued(shop, action):
    gate = blocking_step(shop)
    running = shop.new("block")

    with pytest.raises(Conflict, match="running"):
        getattr(shop.sequencer, action)(running.id, shop.job())

    gate.write_text("go")
    shop.finish(running.id)


def test_a_failed_build_does_not_hold_the_slot(shop):
    shop.step("bad", "exit 1")
    shop.finish(shop.new("bad", guest="alpha").id)

    assert shop.new("bad", guest="bravo")


# --- a service that was killed -----------------------------------------------------------


def test_a_build_left_running_by_a_killed_service_becomes_failed_and_resumable(shop):
    shop.step("long", "true")
    shop.step("tail", "echo tail >> $TT_GUEST_DIR/runs")
    build = shop.new("long", "tail")
    shop.finish(build.id)
    stale = shop.store.load(build.id)
    stale.status = "running"
    stale.step = 1
    stale.steps[1].status = "running"
    stale.steps[1].started = "2026-10-15T12:00:00Z"
    shop.store.save(stale, now=NOW)
    (shop.root / "alpha" / "runs").unlink()

    recovered = shop.sequencer.recover_interrupted()

    assert [b.id for b in recovered] == [build.id]
    after = shop.store.load(build.id)
    assert after.status == "failed"
    assert after.message == INTERRUPTED_MESSAGE
    assert "restarted while this step was running" in after.message
    assert statuses_of(after) == ["succeeded", "failed"]
    shop.sequencer.resume(build.id, shop.job())
    assert shop.finish(build.id).status == "succeeded"
    assert (shop.root / "alpha" / "runs").read_text() == "tail\n"


def test_recovery_leaves_finished_and_paused_builds_alone(shop):
    pausing_step(shop)
    paused = shop.finish(shop.new("ask", "after").id)

    assert shop.sequencer.recover_interrupted() == []
    assert shop.store.load(paused.id).status == "paused"


# --- crashes never kill the thread silently ----------------------------------------------


def test_an_error_while_preparing_fails_the_build_with_the_reason(shop):
    shop.step("one", "true")

    def refuse(_build):
        raise BuildFailed("the guest record cannot be written")

    build = shop.finish(shop.new("one", prepare=refuse).id)

    assert build.status == "failed"
    assert build.message == "the guest record cannot be written"
    assert statuses_of(build) == ["pending"]


def test_an_unexpected_exception_fails_the_build_with_its_type_and_a_traceback_in_the_log(shop):
    shop.step("one", "true")

    def explode(_build):
        raise ZeroDivisionError("kaboom")

    build = shop.finish(shop.new("one", prepare=explode).id)

    assert build.status == "failed"
    assert "internal error" in build.message
    assert "ZeroDivisionError" in build.message
    assert any("Traceback" in line for line in shop.log(build.id))


def test_a_failing_final_hook_fails_the_build_and_resume_runs_only_that_hook(shop):
    shop.step("one", "echo one >> $TT_GUEST_DIR/runs")
    attempts = []

    def finalize(_build):
        attempts.append(1)
        if len(attempts) == 1:
            raise BuildFailed("cape did not list the guest")

    build = shop.finish(shop.new("one", finalize=finalize).id)
    assert (build.status, build.message) == ("failed", "cape did not list the guest")
    assert statuses_of(build) == ["succeeded"]

    shop.sequencer.resume(build.id, shop.job(finalize=finalize))
    build = shop.finish(build.id)

    assert build.status == "succeeded"
    assert (shop.root / "alpha" / "runs").read_text() == "one\n"
    assert len(attempts) == 2


def test_a_status_hook_that_raises_does_not_stop_the_build(shop):
    shop.step("one", "true")
    (shop.root / "alpha").mkdir(parents=True, exist_ok=True)

    def broken_hook(_build):
        raise RuntimeError("hook bug")

    job = BuildJob(
        find_step=lambda name: shop.steps / name,
        profile_dir=shop.profile_dir,
        secrets=(),
        on_status=broken_hook,
    )
    (shop.root / "alpha" / "guest.json").write_text("{}")
    build = shop.sequencer.begin("alpha", "build", [PipelineStep("one", False, 30, 1)], job)

    assert shop.finish(build.id).status == "succeeded"


# --- secrets -----------------------------------------------------------------------------


def assert_no_secret_anywhere(shop, build):
    assert SECRET not in json.dumps(build.to_dict())
    assert SECRET not in "\n".join(shop.log(build.id))
    assert SECRET not in (shop.root / build.guest / "builds" / build.id / "log").read_text()


def test_the_guest_secrets_never_reach_the_log_or_the_pause_text(shop):
    shop.step(
        "leaky",
        f"echo 'password is {SECRET}'\necho 'PAUSE type {SECRET} in the box'\n"
        f"echo 'oops {SECRET}' >&2\nexit 75",
    )

    paused = shop.finish(shop.new("leaky").id)

    assert_no_secret_anywhere(shop, paused)
    assert paused.pause == {"instructions": "type *** in the box"}


def test_the_guest_secrets_never_reach_the_failure_message(shop):
    shop.step("worse", f"echo 'oops {SECRET}'\nexit 2")

    failed = shop.finish(shop.new("worse").id)

    assert_no_secret_anywhere(shop, failed)
    assert "oops ***" in failed.message


def test_the_step_itself_still_receives_the_real_environment(shop):
    shop.step("check", '[ -n "$TT_GUEST_JSON" ]')

    assert shop.finish(shop.new("check").id).status == "succeeded"


# --- the process of the running step -----------------------------------------------------


def wait_for(condition, seconds=10):
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "timed out waiting"
        time.sleep(0.02)


def step_pid_of(shop, build_id) -> int:
    wait_for(lambda: shop.store.load(build_id).step_pid is not None)
    return shop.store.load(build_id).step_pid


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"


def test_the_steps_process_group_is_recorded_while_it_runs_and_cleared_when_it_ends(shop):
    gate = blocking_step(shop)
    running = shop.new("block")

    pid = step_pid_of(shop, running.id)

    recorded = shop.store.load(running.id)
    assert os.getpgid(pid) == pid
    assert recorded.step_path == str(shop.steps / "block")
    wait_for(lambda: is_step_process(pid, shop.steps / "block"))
    gate.write_text("go")
    finished = shop.finish(running.id)
    assert (finished.step_pid, finished.step_path) == (None, None)


@pytest.mark.parametrize(("body", "status"), [("exit 1", "failed"), ("exit 75", "paused")])
def test_a_step_that_fails_or_pauses_leaves_no_process_recorded(shop, body, status):
    shop.step("ends", body)

    build = shop.finish(shop.new("ends").id)

    assert build.status == status
    assert (build.step_pid, build.step_path) == (None, None)


# --- a step a dead service left running --------------------------------------------------


@pytest.fixture
def unrelated_process():
    process = subprocess.Popen(["sleep", "300"], start_new_session=True)  # noqa: S607
    yield process
    process.kill()
    process.wait(5)


def stale_build(shop, **step_process):
    """A finished build edited to look as a killed service left it: running, a step recorded."""
    shop.step("long", "true")
    build = shop.finish(shop.new("long").id)
    build.status = "running"
    build.steps[0].status = "running"
    for field, value in step_process.items():
        setattr(build, field, value)
    shop.store.save(build, now=NOW)
    return build


def test_a_step_left_running_by_a_dead_service_is_stopped_and_the_build_says_so(shop):
    shop.step("long", "sleep 300")
    build = shop.new("long")
    pid = step_pid_of(shop, build.id)
    successor = shop.service()

    with shop.lock:  # the dead service's thread must not write while the successor recovers
        recovered = successor.recover_interrupted()
        wait_for(lambda: not alive(pid))
        after = shop.store.load(build.id)

    assert [b.id for b in recovered] == [build.id]
    note = "the previous control service left step 'long' running; stopped it"
    assert (after.status, after.message) == ("failed", f"{note}; resume it")
    assert after.steps[0].status == "failed"
    assert (after.step_pid, after.step_path) == (None, None)
    assert f"== {note}" in shop.log(build.id)
    shop.finish(build.id)


def test_a_step_that_ignores_sigterm_is_killed_when_the_recovery_runs_out_of_patience(shop):
    shop.step("stubborn", "trap '' TERM\nwhile :; do sleep 0.05; done")
    build = shop.new("stubborn")
    pid = step_pid_of(shop, build.id)
    time.sleep(0.3)  # the trap must be set before the signal arrives
    successor = shop.service(stop_grace_s=0.5)

    with shop.lock:
        successor.recover_interrupted()
        wait_for(lambda: not alive(pid))

    shop.finish(build.id)


def test_a_pid_now_used_by_an_unrelated_process_is_never_killed(shop, unrelated_process):
    build = stale_build(shop, step_pid=unrelated_process.pid, step_path=str(shop.steps / "long"))

    shop.service().recover_interrupted()

    assert alive(unrelated_process.pid)
    after = shop.store.load(build.id)
    assert (after.status, after.message) == ("failed", INTERRUPTED_MESSAGE)
    assert (after.step_pid, after.step_path) == (None, None)
    assert not any("stopped it" in line for line in shop.log(build.id))


def test_a_recorded_pid_that_no_longer_exists_only_fails_the_build(shop):
    gone = subprocess.Popen(["true"])  # noqa: S607
    gone.wait(5)
    build = stale_build(shop, step_pid=gone.pid, step_path=str(shop.steps / "long"))

    shop.service().recover_interrupted()

    assert shop.store.load(build.id).message == INTERRUPTED_MESSAGE


def test_a_build_with_no_recorded_step_process_is_recovered_as_before(shop):
    build = stale_build(shop)

    shop.service().recover_interrupted()

    assert shop.store.load(build.id).message == INTERRUPTED_MESSAGE


# --- stopping the sequencer --------------------------------------------------------------


def test_shutdown_stops_the_running_step_and_leaves_the_build_failed_and_resumable(shop):
    shop.step("long", "sleep 300")
    shop.step("after", "echo after >> $TT_GUEST_DIR/runs")
    build = shop.new("long", "after")
    pid = step_pid_of(shop, build.id)

    shop.sequencer.shutdown()

    after = shop.store.load(build.id)
    assert not alive(pid)
    assert (after.status, after.message) == ("failed", SHUTDOWN_MESSAGE)
    assert SHUTDOWN_MESSAGE == (
        "the control service was stopped while this step was running; resume it"
    )
    assert statuses_of(after) == ["failed", "pending"]
    assert (after.step_pid, after.step_path) == (None, None)
    assert shop.statuses[-1] == "failed"
    assert not (shop.root / "alpha" / "runs").exists()
    shop.step("long", "true")
    successor = shop.service()
    successor.resume(build.id, shop.job())
    assert successor.wait(build.id, timeout=20)
    assert shop.store.load(build.id).status == "succeeded"


def test_shutdown_kills_a_step_that_ignores_sigterm_after_the_grace(shop):
    shop.sequencer = shop.service(stop_grace_s=0.5)
    shop.step("stubborn", "trap '' TERM\nwhile :; do sleep 0.05; done")
    build = shop.new("stubborn")
    pid = step_pid_of(shop, build.id)
    time.sleep(0.3)

    shop.sequencer.shutdown()

    assert not alive(pid)
    assert shop.store.load(build.id).message == SHUTDOWN_MESSAGE


def test_shutdown_is_safe_when_idle_and_when_repeated(shop):
    shop.sequencer.shutdown()
    shop.sequencer.shutdown()


def test_shutdown_after_a_build_ended_changes_nothing(shop):
    shop.step("one", "true")
    build = shop.finish(shop.new("one").id)

    shop.sequencer.shutdown()

    assert shop.store.load(build.id).status == "succeeded"


def test_shutdown_leaves_a_paused_build_paused(shop):
    pausing_step(shop)
    paused = shop.finish(shop.new("ask", "after").id)

    shop.sequencer.shutdown()

    assert shop.store.load(paused.id).status == "paused"


def test_nothing_is_started_once_the_sequencer_was_shut_down(shop):
    shop.step("one", "true")
    shop.sequencer.shutdown()

    with pytest.raises(Conflict, match="stopping"):
        shop.new("one")


def is_stopping(sequencer) -> bool:
    try:
        sequencer.require_free_slot()
    except Conflict as refused:
        return "stopping" in str(refused)
    return False


def test_a_step_that_would_start_once_the_shutdown_began_is_not_started(shop):
    shop.step("one", "echo ran >> $TT_GUEST_DIR/runs")
    stopper = threading.Thread(target=shop.sequencer.shutdown)

    def stop_while_preparing(_build):
        stopper.start()
        wait_for(lambda: is_stopping(shop.sequencer))

    build = shop.finish(shop.new("one", prepare=stop_while_preparing).id)

    stopper.join(20)
    assert (build.status, build.message) == ("failed", SHUTDOWN_MESSAGE)
    assert statuses_of(build) == ["pending"]
    assert not (shop.root / "alpha" / "runs").exists()
