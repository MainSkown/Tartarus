"""Build records: one directory per build under the guest's, holding `build.json` and the log.

    <registry root>/<guest>/builds/<build id>/{build.json, log, context.json}

`build.json` is what the engine reports to the backend. Only the build's sequencer writes it (always
by replacing the whole file), so a reader sees one complete version or the next.
"""

import json
import os
import re
import secrets
from collections import deque
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from guest_engine.errors import GuestNotFound
from guest_engine.profile import PipelineStep
from guest_engine.registry import write_atomically

BUILD_FILE = "build.json"
LOG_FILE = "log"
CONTEXT_FILE = "context.json"
BUILDS_DIR = "builds"
BUILD_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
ACTIVE_STATUSES = ("running", "paused")
FULL = 100


def timestamp(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class StepState:
    name: str
    status: str = "pending"
    started: str | None = None
    finished: str | None = None
    exit_code: int | None = None
    weight: int = 1
    timeout_s: int = 600
    desktop: bool = False
    progress: int = 0


@dataclass
class BuildRecord:
    id: str
    guest: str
    kind: str
    status: str
    step: int
    steps: list[StepState]
    created: str
    updated: str
    message: str = ""
    pause: dict[str, str] | None = field(default=None)

    @property
    def percent(self) -> int:
        if self.status == "succeeded":
            return FULL
        total = sum(step.weight for step in self.steps)
        if total == 0:
            return 0
        done = sum(self._weight_done(step) for step in self.steps)
        return min(FULL, int(FULL * done / total))

    @staticmethod
    def _weight_done(step: StepState) -> float:
        if step.status == "succeeded":
            return step.weight
        if step.status in ("running", "paused"):
            return step.weight * step.progress / FULL
        return 0

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "percent": self.percent}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BuildRecord":
        fields = {key: value for key, value in data.items() if key != "percent"}
        fields["steps"] = [StepState(**step) for step in data["steps"]]
        return cls(**fields)


def _new_build_id() -> str:
    return f"b{secrets.token_hex(6)}"


def _step_state(entry: PipelineStep) -> StepState:
    return StepState(
        name=entry.step, weight=entry.weight, timeout_s=entry.timeout_s, desktop=entry.desktop
    )


class BuildStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def directory(self, build: BuildRecord) -> Path:
        return self.root / build.guest / BUILDS_DIR / build.id

    def log_path(self, build: BuildRecord) -> Path:
        return self.directory(build) / LOG_FILE

    def create(
        self, guest: str, kind: str, pipeline: Sequence[PipelineStep], now: datetime | None = None
    ) -> BuildRecord:
        stamp = timestamp(now)
        build = BuildRecord(
            id=_new_build_id(),
            guest=guest,
            kind=kind,
            status="running",
            step=0,
            steps=[_step_state(entry) for entry in pipeline],
            created=stamp,
            updated=stamp,
        )
        self.save(build, now=now)
        return build

    def save(self, build: BuildRecord, now: datetime | None = None) -> None:
        build.updated = timestamp(now)
        text = json.dumps(build.to_dict(), indent=2) + "\n"
        write_atomically(self.directory(build) / BUILD_FILE, text, mode=0o600)

    def load(self, build_id: str) -> BuildRecord:
        if not BUILD_ID.fullmatch(build_id):
            raise GuestNotFound(build_id)
        for guest_dir in self._guest_directories():
            file = guest_dir / BUILDS_DIR / build_id / BUILD_FILE
            if file.is_file():
                return self._read(file)
        raise GuestNotFound(build_id)

    def all(self) -> list[BuildRecord]:
        builds = []
        for guest_dir in self._guest_directories():
            for file in sorted((guest_dir / BUILDS_DIR).glob(f"*/{BUILD_FILE}")):
                try:
                    builds.append(self._read(file))
                except (ValueError, KeyError, TypeError, OSError):
                    continue
        return sorted(builds, key=lambda build: (build.created, build.id))

    def of_guest(self, guest: str) -> list[BuildRecord]:
        return [build for build in self.all() if build.guest == guest]

    def active(self) -> BuildRecord | None:
        """The build that holds the engine's one build slot: running or waiting for the user."""
        return next((build for build in self.all() if build.status in ACTIVE_STATUSES), None)

    def append_log(self, build: BuildRecord, line: str) -> None:
        path = self.log_path(build)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8", errors="replace") as handle:
            handle.write(" ".join(line.splitlines()) + "\n")

    def tail(self, build_id: str, lines: int) -> list[str]:
        path = self.log_path(self.load(build_id))
        try:
            with path.open(encoding="utf-8", errors="replace") as handle:
                return [line.rstrip("\n") for line in deque(handle, maxlen=lines)]
        except FileNotFoundError:
            return []

    def _guest_directories(self) -> list[Path]:
        if not self.root.is_dir():
            return []
        return sorted(path for path in self.root.iterdir() if path.is_dir())

    @staticmethod
    def _read(file: Path) -> BuildRecord:
        return BuildRecord.from_dict(json.loads(file.read_text()))
