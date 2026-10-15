"""The control service's side of a guest's self-test: the benign sample and the guest-side checks.

The backend asks for the sample of a guest's profile, submits it as an ordinary analysis on that
guest, and asks for the guest-side checks. Everything operating-system specific is in the
profile: the command that builds the sample and the step that runs the checks.
"""

import hashlib
import json
import re
import shutil
import tempfile
import threading
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from guest_engine.errors import Conflict
from guest_engine.media import Fault, MediaProblem, Runner
from guest_engine.profile import OUTPUT_PLACEHOLDER, SOURCE_PLACEHOLDER, Profile
from guest_engine.steps import Redactor, StepControl, failure_message, run_step

SAMPLE_BUILD_TIMEOUT_S = 300
FAILURE_OUTPUT_LINES = 10
KEY_SUFFIX = ".key"
SCRATCH_PREFIX = "build-"
CHECK_LOG_LINES = 50
LOG_PREFIX = "LOG "
FACT_LINE = re.compile(r"FACT ([A-Za-z0-9_.-]+)=(.*)")
GIVEAWAY_LINE = re.compile(r"GIVEAWAY (\S.*)")
PROOF_LINE = re.compile(r"PROOF ([a-z][a-z0-9_.-]*)=(ok|failed)(?: (.*))?")
STOPPED_MESSAGE = "the control service was stopped while the self-test checks were running"

type Json = dict[str, Any]


class SampleBuildFailed(RuntimeError):  # noqa: N818 - the message is shown to the analyst, it is not a program error
    """The profile's command did not produce the sample; the message holds the end of its output."""


@dataclass(frozen=True)
class BuiltSample:
    path: Path
    filename: str


def _tail(text: str, lines: int = FAILURE_OUTPUT_LINES) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


class SampleBuilder:
    """Builds a profile's sample once; the cache holds until the source or the command change."""

    def __init__(self, cache_dir: Path, runner: Runner) -> None:
        self._cache_dir = cache_dir
        self._runner = runner
        self._lock = threading.Lock()

    def sample(self, profile: Profile, profile_dir: Path) -> BuiltSample:
        definition = profile.selftest.sample
        if definition is None:
            raise Conflict(f"the profile {profile.id} defines no self-test sample")
        source = profile_dir / definition.source
        directory = self._cache_dir / profile.id
        built = BuiltSample(directory / definition.output, definition.output)
        key = _cache_key(source, definition.build)
        with self._lock:
            if not self._is_cached(built, key):
                directory.mkdir(parents=True, exist_ok=True)
                self._build(definition.build, source, built, key)
        return built

    @staticmethod
    def _is_cached(built: BuiltSample, key: str) -> bool:
        key_file = built.path.with_name(built.filename + KEY_SUFFIX)
        return built.path.is_file() and key_file.is_file() and key_file.read_text() == key

    def _build(self, command: list[str], source: Path, built: BuiltSample, key: str) -> None:
        built.path.with_name(built.filename + KEY_SUFFIX).unlink(missing_ok=True)
        scratch = Path(tempfile.mkdtemp(prefix=SCRATCH_PREFIX, dir=built.path.parent))
        try:
            produced = scratch / built.filename
            self._run(_argv(command, source, produced))
            if not produced.is_file():
                raise SampleBuildFailed(f"the build ran but produced no file {built.filename}")
            produced.replace(built.path)
            built.path.with_name(built.filename + KEY_SUFFIX).write_text(key)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def _run(self, argv: list[str]) -> None:
        try:
            result = self._runner(argv, timeout=SAMPLE_BUILD_TIMEOUT_S)
        except MediaProblem as problem:
            raise SampleBuildFailed(_cannot_run(argv[0], problem)) from None
        if result.returncode != 0:
            output = _tail(f"{result.stdout}\n{result.stderr}")
            raise SampleBuildFailed(
                f"building the sample failed (exit code {result.returncode}):\n{output}"
            )


def _argv(command: list[str], source: Path, output: Path) -> list[str]:
    values = {SOURCE_PLACEHOLDER: str(source), OUTPUT_PLACEHOLDER: str(output)}
    return [values.get(argument, argument) for argument in command]


def _cache_key(source: Path, command: list[str]) -> str:
    try:
        digest = hashlib.sha256(source.read_bytes())
    except OSError:
        raise SampleBuildFailed(f"cannot read the sample source {source}") from None
    digest.update(json.dumps(command).encode())
    return digest.hexdigest()


REASONS_NOT_RUN: dict[Fault | str, str] = {
    Fault.TOOL_MISSING: "is not installed in this image",
    Fault.TIMED_OUT: "took too long and was stopped",
}


def _cannot_run(program: str, problem: MediaProblem) -> str:
    reason = REASONS_NOT_RUN.get(problem.fault, str(problem))
    return f"building the sample failed: {problem.detail or program} {reason}"


class ChecksFailed(RuntimeError):  # noqa: N818 - the message is shown to the analyst, it is not a program error
    """The check step did not run to its end; the message holds why and the end of its log."""


class ChecksCollector:
    """Reads the lines of a check step: `FACT key=value`, `GIVEAWAY text`, `PROOF name=ok` or
    `PROOF name=failed message`; every other line is log, of which the last few are kept.

    A line the guest wrote reaches here behind a `LOG ` prefix, so nothing in a guest can pass
    itself off as a fact, a giveaway or a proof.
    """

    def __init__(self) -> None:
        self._facts: dict[str, str] = {}
        self._giveaways: list[str] = []
        self._proofs: dict[str, Json] = {}
        self._log: deque[str] = deque(maxlen=CHECK_LOG_LINES)

    def add(self, line: str) -> None:
        if fact := FACT_LINE.fullmatch(line):
            self._facts[fact.group(1)] = fact.group(2)
        elif giveaway := GIVEAWAY_LINE.fullmatch(line):
            self._giveaways.append(giveaway.group(1).strip())
        elif proof := PROOF_LINE.fullmatch(line):
            name, status, message = proof.groups()
            self._proofs[name] = {"ok": status == "ok", "message": message or ""}
        else:
            self._log.append(line.removeprefix(LOG_PREFIX))

    def report(self) -> Json:
        return {
            "facts": dict(self._facts),
            "giveaways": list(self._giveaways),
            "proofs": {name: dict(proof) for name, proof in self._proofs.items()},
            "log": list(self._log),
        }

    def recent_log(self, lines: int = FAILURE_OUTPUT_LINES) -> list[str]:
        return list(self._log)[-lines:]


@dataclass(frozen=True)
class PreparedChecks:
    """What the engine hands over to run the check step: the file, its environment, its limits."""

    step: Path
    environment: Mapping[str, str]
    timeout_s: int
    log_path: Path


def run_check_step(prepared: PreparedChecks, *, redact: Redactor, control: StepControl) -> Json:
    """Run the profile's check step to its end and return what it reported.

    Every line is redacted before anything reads it, so the report, the log file and a failure
    message never hold the guest's secrets. Any exit code but 0 is a failure.
    """
    collector = ChecksCollector()
    with prepared.log_path.open("w") as transcript:

        def on_line(raw: str) -> None:
            line = redact(raw)
            transcript.write(line + "\n")
            collector.add(line)

        outcome = run_step(
            [str(prepared.step)],
            prepared.environment,
            timeout_s=prepared.timeout_s,
            on_line=on_line,
            control=control,
        )
    if control.stop_requested:
        raise ChecksFailed(STOPPED_MESSAGE)
    if outcome.exit_code != 0 or outcome.timed_out:
        raise ChecksFailed(
            failure_message(prepared.step.name, prepared.timeout_s, outcome, collector.recent_log())
        )
    return collector.report()
