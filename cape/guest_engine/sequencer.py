"""Runs a build's steps one after another on a thread of its own and keeps `build.json` true.

The state machine, per build: `running` ends as `succeeded`, `failed` or `paused`. A failed or
paused build is picked up again from the step that stopped it (`resume`, `continue_after_pause`) or
from the first step (`restart`); steps are idempotent, so re-running one is always safe. At most
one build or clone is active (running, or paused and waiting for the analyst) engine-wide.

Every change of the build's status happens under the engine's lock, which the engine's own
operations hold too, so a delete or a resume never sees a half-made transition.
"""

import logging
import threading
import traceback
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from guest_engine.builds import BuildRecord, BuildStore, StepState, timestamp
from guest_engine.errors import Conflict
from guest_engine.profile import PipelineStep
from guest_engine.registry import GUEST_FILE
from guest_engine.steps import (
    PAUSE_EXIT_CODE,
    Log,
    PauseRequest,
    Progress,
    Redactor,
    StepControl,
    StepOutcome,
    StepPaths,
    StepTitle,
    is_step_process,
    parse_line,
    run_step,
    step_environment,
    terminate_group,
)

log = logging.getLogger(__name__)

INTERRUPTED_MESSAGE = "the control service restarted while this step was running; resume it"
SHUTDOWN_MESSAGE = "the control service was stopped while this step was running; resume it"
STOP_GRACE_S = 5.0
CONCLUDE_WAIT_S = 10.0
DEFAULT_PAUSE_INSTRUCTIONS = (
    "This step is waiting for you. Follow what the page shows, then continue."
)
FAILURE_LOG_LINES = 10
FULL = 100


class BuildFailed(Exception):  # noqa: N818 - a build ended badly with a message for the analyst, not a program error
    """Raised by a build's hooks to fail it with a message meant to be shown as it is."""


def _nothing(_build: BuildRecord) -> None:
    return None


@dataclass(frozen=True)
class BuildJob:
    """What the sequencer needs from the engine to run one build.

    `prepare` runs before the steps of every attempt (the engine writes `context.json` there),
    `finalize` after the last step succeeded, `on_status` after each change of the build's status.
    The first two may raise `BuildFailed`.
    """

    find_step: Callable[[str], Path | None]
    profile_dir: Path
    secrets: Sequence[str]
    on_status: Callable[[BuildRecord], None] = _nothing
    prepare: Callable[[BuildRecord], None] = _nothing
    finalize: Callable[[BuildRecord], None] = _nothing


class Sequencer:
    def __init__(
        self,
        store: BuildStore,
        lock: threading.RLock,
        inherited_environment: Mapping[str, str],
        stop_grace_s: float = STOP_GRACE_S,
    ) -> None:
        self._store = store
        self._lock = lock
        self._inherited = inherited_environment
        self._stop_grace_s = stop_grace_s
        self._threads: dict[str, threading.Thread] = {}
        self._controls: dict[str, StepControl] = {}
        self._controls_lock = threading.Lock()
        self._closed = False

    def begin(
        self,
        guest: str,
        kind: str,
        pipeline: Sequence[PipelineStep],
        job: BuildJob,
        now: datetime | None = None,
    ) -> BuildRecord:
        with self._lock:
            self._require_open()
            self._require_free_slot(excluding=None)
            build = self._store.create(guest, kind, pipeline, now)
            self._launch(build, job)
        return build

    def resume(self, build_id: str, job: BuildJob) -> None:
        """Run the failed or paused build again from the step that stopped it."""
        with self._lock:
            build = self._stopped_build(build_id, ("failed", "paused"))
            self._start_again(build, job, from_step=self._first_unfinished(build))

    def continue_after_pause(self, build_id: str, job: BuildJob) -> None:
        with self._lock:
            build = self._stopped_build(build_id, ("paused",))
            self._start_again(build, job, from_step=self._first_unfinished(build))

    def restart(self, build_id: str, job: BuildJob) -> None:
        """Run the failed or paused build again from its first step."""
        with self._lock:
            build = self._stopped_build(build_id, ("failed", "paused"))
            self._store.append_log(build, "== restarting from the first step")
            self._start_again(build, job, from_step=0)

    def recover_interrupted(self) -> list[BuildRecord]:
        """Fail the builds a killed service left `running`, so the analyst can resume them."""
        recovered = []
        with self._lock:
            for build in self._store.all():
                if build.status != "running" or self._is_alive(build.id):
                    continue
                for step in build.steps:
                    if step.status == "running":
                        step.status = "failed"
                        step.finished = timestamp()
                build.status = "failed"
                note = self._stop_orphaned_step(build)
                build.message = f"{note}; resume it" if note else INTERRUPTED_MESSAGE
                build.forget_step_process()
                self._store.append_log(build, f"== {note or INTERRUPTED_MESSAGE}")
                self._store.save(build)
                recovered.append(build)
        return recovered

    def shutdown(self) -> None:
        """Stop the running step and fail its build so it can be resumed; start nothing afterwards.

        Safe to call again and when nothing runs. A paused build has no process, so it stays paused.
        """
        with self._controls_lock:
            self._closed = True
            controls = list(self._controls.values())
        for control in controls:
            control.stop(self._stop_grace_s)
        for thread in list(self._threads.values()):
            thread.join(self._stop_grace_s + CONCLUDE_WAIT_S)

    def require_free_slot(self) -> None:
        """Raise `Conflict` naming the build or clone that is active, if one is."""
        self._require_open()
        self._require_free_slot(excluding=None)

    def wait(self, build_id: str, timeout: float | None = None) -> bool:
        """Block until the build's thread ends; False if it still runs after `timeout` seconds."""
        thread = self._threads.get(build_id)
        if thread is not None:
            thread.join(timeout)
            return not thread.is_alive()
        return True

    def _stop_orphaned_step(self, build: BuildRecord) -> str | None:
        """Stop the step a dead service left running; the build's note, or None if none ran."""
        if build.step_pid is None or build.step_path is None:
            return None
        step_file = Path(build.step_path)
        if not is_step_process(build.step_pid, step_file):
            return None
        terminate_group(build.step_pid, self._stop_grace_s)
        return f"the previous control service left step '{step_file.name}' running; stopped it"

    def _is_alive(self, build_id: str) -> bool:
        thread = self._threads.get(build_id)
        return thread is not None and thread.is_alive()

    def _require_free_slot(self, excluding: str | None) -> None:
        active = self._store.active()
        if active is not None and active.id != excluding:
            raise Conflict(
                f"the {active.kind} of {active.guest} is {active.status}; "
                "only one build or clone can be active at a time"
            )

    def _require_open(self) -> None:
        if self._closed:
            raise Conflict("the control service is stopping; nothing new is started")

    def _stopped_build(self, build_id: str, allowed: tuple[str, ...]) -> BuildRecord:
        self._require_open()
        build = self._store.load(build_id)
        if build.status not in allowed:
            wanted = " or ".join(allowed)
            raise Conflict(f"the {build.kind} of {build.guest} is {build.status}, not {wanted}")
        self._require_free_slot(excluding=build.id)
        return build

    @staticmethod
    def _first_unfinished(build: BuildRecord) -> int:
        return next(
            (index for index, step in enumerate(build.steps) if step.status != "succeeded"),
            len(build.steps),
        )

    def _start_again(self, build: BuildRecord, job: BuildJob, from_step: int) -> None:
        build.status = "running"
        build.step = min(from_step, len(build.steps) - 1)
        build.message = ""
        build.pause = None
        for step in build.steps[from_step:]:
            step.status, step.progress, step.exit_code = "pending", 0, None
            step.started = step.finished = None
        self._launch(build, job)

    def _launch(self, build: BuildRecord, job: BuildJob) -> None:
        self._store.save(build)
        self._notify(job, build)
        thread = threading.Thread(
            target=self._run, args=(build.id, job), daemon=True, name=f"build-{build.id}"
        )
        self._threads[build.id] = thread
        thread.start()

    def _run(self, build_id: str, job: BuildJob) -> None:
        build = self._store.load(build_id)
        try:
            self._execute(build, job)
        except BuildFailed as failure:
            self._conclude(build, job, "failed", str(failure))
        except Exception as error:  # noqa: BLE001 - any crash must end as a failed build
            for line in traceback.format_exc().splitlines():
                self._store.append_log(build, line)
            self._conclude(build, job, "failed", f"internal error: {error!r}")
        finally:
            with self._controls_lock:
                self._controls.pop(build_id, None)

    def _execute(self, build: BuildRecord, job: BuildJob) -> None:
        job.prepare(build)
        redact = Redactor(job.secrets)
        for index in range(self._first_unfinished(build), len(build.steps)):
            build.step = index
            if not self._run_one(build, job, redact):
                return
        job.finalize(build)
        self._conclude(build, job, "succeeded")

    def _run_one(self, build: BuildRecord, job: BuildJob, redact: Redactor) -> bool:
        """Run the build's current step; True when it is done and the next one may start."""
        step = build.steps[build.step]
        path = job.find_step(step.name)
        if path is None:
            step.status, step.finished = "failed", timestamp()
            self._conclude(
                build, job, "failed", f"step '{step.name}' was not found or is not executable"
            )
            return False
        control = self._new_control(build)
        if control is None:
            self._conclude(build, job, "failed", SHUTDOWN_MESSAGE)
            return False
        step.status, step.started, step.progress = "running", timestamp(), 0
        build.message = step.name
        build.step_path = str(path)
        self._store.save(build)
        self._store.append_log(build, f"== step {step.name}")
        recent: deque[str] = deque(maxlen=FAILURE_LOG_LINES)
        instructions: list[str] = []

        def on_line(raw: str) -> None:
            line = redact(raw)
            self._store.append_log(build, line)
            recent.append(line)
            match parse_line(line):
                case StepTitle(text):
                    build.message = text or step.name
                    self._store.save(build)
                case Progress(percent):
                    step.progress = percent
                    self._store.save(build)
                case PauseRequest(text):
                    instructions.append(text)
                case Log():
                    pass

        outcome = run_step(
            [str(path)],
            step_environment(
                self._paths(build, job),
                step=step.name,
                build_id=build.id,
                inherited=self._inherited,
            ),
            timeout_s=step.timeout_s,
            on_line=on_line,
            control=control,
        )
        build.forget_step_process()
        step.finished, step.exit_code = timestamp(), outcome.exit_code
        if outcome.exit_code == 0:
            step.status, step.progress = "succeeded", FULL
            self._store.save(build)
            return True
        if outcome.exit_code == PAUSE_EXIT_CODE:
            step.status = "paused"
            text = redact(instructions[-1]) if instructions else ""
            self._conclude(
                build, job, "paused", pause={"instructions": text or DEFAULT_PAUSE_INSTRUCTIONS}
            )
            return False
        step.status = "failed"
        reason = (
            SHUTDOWN_MESSAGE if control.stop_requested else _failure_message(step, outcome, recent)
        )
        self._conclude(build, job, "failed", reason)
        return False

    def _new_control(self, build: BuildRecord) -> StepControl | None:
        """The handle on the next step of `build`, or None when the sequencer was shut down."""
        with self._controls_lock:
            if self._closed:
                return None
            control = StepControl(on_start=lambda pid: self._record_step_process(build, pid))
            self._controls[build.id] = control
            return control

    def _record_step_process(self, build: BuildRecord, pid: int) -> None:
        build.step_pid = pid
        self._store.save(build)

    def _paths(self, build: BuildRecord, job: BuildJob) -> StepPaths:
        guest_dir = self._store.root / build.guest
        build_dir = self._store.directory(build)
        return StepPaths(
            guest_dir=guest_dir,
            guest_json=guest_dir / GUEST_FILE,
            profile_dir=job.profile_dir,
            state_file=build_dir / "build.json",
            build_dir=build_dir,
            log=self._store.log_path(build),
            context_json=build_dir / "context.json",
        )

    def _conclude(
        self,
        build: BuildRecord,
        job: BuildJob,
        status: str,
        message: str = "",
        pause: dict[str, str] | None = None,
    ) -> None:
        with self._lock:
            build.status, build.message, build.pause = status, message, pause
            self._store.save(build)
            self._notify(job, build)

    @staticmethod
    def _notify(job: BuildJob, build: BuildRecord) -> None:
        try:
            job.on_status(build)
        except Exception:
            log.exception("the status hook failed for build %s (%s)", build.id, build.status)


def _failure_message(step: StepState, outcome: StepOutcome, recent: deque[str]) -> str:
    if outcome.timed_out:
        return f"step '{step.name}' timed out after {step.timeout_s} s and was stopped"
    if outcome.start_error:
        return f"step '{step.name}' could not be started: {outcome.start_error}"
    code = outcome.exit_code
    if code is not None and code < 0:
        reason = f"was killed by signal {-code}"
    else:
        reason = f"failed with exit code {code}"
    tail = "\n".join(line for line in recent if line)
    return f"step '{step.name}' {reason}" + (f":\n{tail}" if tail else "")
