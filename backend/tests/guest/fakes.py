from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.guest.lan_schemas import LanHealth, LanHost, LanPreset, LanService
from app.guest.schemas import (
    BuildProgress,
    BuildStatus,
    Guest,
    GuestProfile,
    HealthCheckResult,
    MediaEntry,
    ProofResult,
    SelfTestChecks,
    SelfTestSample,
)
from tests.guest.captured import captured

BUILD_ID = "b2f48f9dcd08a"
LAN_CALLS = frozenset(
    {"lan_presets", "lan_health", "lan_sessions", "open_lan_session", "close_lan_session"}
)


def a_preset(preset_id: str = "small-office") -> LanPreset:
    host = LanHost(
        fqdn="dc01.corp.example",
        address="192.168.150.200",
        role="domain-controller",
        services=[LanService(kind="smb", port=445)],
    )
    return LanPreset(id=preset_id, name="Small office", description="A small office", hosts=[host])


@dataclass
class Poll:
    """What the control service answers to one `build()` call: a status, or the failure to raise,
    and the build's whole log at that moment."""

    answer: BuildStatus | Exception
    log: list[str] = field(default_factory=list)


class FakeGuestControl:
    """Answers from the lists it was given, records the calls it got, and fails with `error`.

    A build is played from `polls`, one entry per `build()` call; the last entry repeats.
    """

    def __init__(
        self,
        guests: list[Guest] | None = None,
        *,
        error: Exception | None = None,
        check_result: HealthCheckResult | None = None,
    ) -> None:
        self.guests_listed = guests if guests is not None else real_guests()
        self.error = error
        self.check_result = check_result
        self.calls: list[tuple[str, Any]] = []
        self.polls: list[Poll] = [Poll(a_build("running"))]
        self.polled = 0
        self.started_build_id = BUILD_ID
        self.error_by_call: dict[str, Exception] = {}
        self.selftest_sample_listed = SelfTestSample("benign.exe", b"MZ pretend")
        self.selftest_checks_listed = clean_checks()
        self.lan_presets_listed = [a_preset()]
        self.lan_health_answer = LanHealth(ready=True)
        self.lan_open: dict[str, tuple[str, str]] = {}

    def _record(self, call: str, argument: Any = None) -> None:
        self.calls.append((call, argument))
        if self.error is not None:
            raise self.error
        if call in self.error_by_call:
            raise self.error_by_call[call]

    def calls_named(self, call: str) -> list[Any]:
        return [argument for name, argument in self.calls if name == call]

    def non_lan_calls(self) -> list[tuple[str, Any]]:
        return [(name, argument) for name, argument in self.calls if name not in LAN_CALLS]

    def lan_calls(self) -> list[tuple[str, Any]]:
        return [(name, argument) for name, argument in self.calls if name in LAN_CALLS]

    async def lan_presets(self) -> list[LanPreset]:
        self._record("lan_presets")
        return self.lan_presets_listed

    async def lan_health(self) -> LanHealth:
        self._record("lan_health")
        return self.lan_health_answer

    async def lan_sessions(self) -> list[str]:
        self._record("lan_sessions")
        return list(self.lan_open)

    async def open_lan_session(self, key: str, guest: str, preset: str) -> None:
        self._record("open_lan_session", (key, guest, preset))
        self.lan_open[key] = (guest, preset)

    async def close_lan_session(self, key: str, task_id: int | None = None) -> bool:
        self._record("close_lan_session", (key, task_id))
        was_open = self.lan_open.pop(key, None) is not None
        return was_open and task_id is not None

    async def guests(self) -> list[Guest]:
        self._record("guests")
        return self.guests_listed

    async def guest(self, name: str) -> Guest:
        self._record("guest", name)
        return next(guest for guest in self.guests_listed if guest.name == name)

    async def delete_guest(self, name: str) -> None:
        self._record("delete_guest", name)

    async def delete_image_findings(self, task_id: int) -> None:
        self._record("delete_image_findings", task_id)

    async def check(self, name: str) -> HealthCheckResult:
        self._record("check", name)
        return self.check_result or HealthCheckResult.model_validate(captured("check_result.json"))

    async def media(self) -> list[MediaEntry]:
        self._record("media")
        return [MediaEntry.model_validate(entry) for entry in captured("media.json")]

    async def profiles(self) -> list[GuestProfile]:
        self._record("profiles")
        return [GuestProfile.model_validate(entry) for entry in captured("profiles.json")]

    async def start_build(self, params: Mapping[str, Any]) -> str:
        self._record("start_build", dict(params))
        return self.started_build_id

    async def start_clone(self, source: str, params: Mapping[str, Any]) -> str:
        self._record("start_clone", (source, dict(params)))
        return self.started_build_id

    async def retry_selftest(self, name: str) -> str:
        self._record("retry_selftest", name)
        return self.started_build_id

    async def build(self, build_id: str) -> BuildStatus:
        self._record("build", build_id)
        poll = self.polls[min(self.polled, len(self.polls) - 1)]
        self.polled += 1
        if isinstance(poll.answer, Exception):
            raise poll.answer
        return poll.answer

    async def build_log(self, build_id: str, tail: int) -> list[str]:
        self._record("build_log", (build_id, tail))
        current = self.polls[min(max(self.polled, 1), len(self.polls)) - 1]
        return current.log[-tail:]

    async def resume(self, build_id: str) -> None:
        self._record("resume", build_id)

    async def restart(self, build_id: str) -> None:
        self._record("restart", build_id)

    async def cancel_build(self, build_id: str) -> None:
        self._record("cancel", build_id)

    async def continue_(self, build_id: str) -> None:
        self._record("continue", build_id)

    async def complete(self, build_id: str, *, passed: bool, selftest: Mapping[str, Any]) -> None:
        self._record("complete", (build_id, passed, dict(selftest)))

    async def selftest_sample(self, name: str) -> SelfTestSample:
        self._record("selftest_sample", name)
        return self.selftest_sample_listed

    async def selftest_checks(self, name: str) -> SelfTestChecks:
        self._record("selftest_checks", name)
        return self.selftest_checks_listed


def clean_checks() -> SelfTestChecks:
    """What the checks of a healthy guest with Defender off say."""
    return SelfTestChecks(
        facts={
            "os.hostname": "DESKTOP-4F7Q",
            "os.user": "jan",
            "defender.realtime_enabled": "False",
        },
        giveaways=[],
        proofs={"eicar": ProofResult(ok=True, message="the file stayed")},
        log=["restored the snapshot"],
    )


def a_build(status: BuildProgress, *, pause: str | None = None, **fields: Any) -> BuildStatus:
    """The captured build, with only what a case is about changed."""
    record = captured("build_status.json")
    record.update(status=status, pause={"instructions": pause} if pause is not None else None)
    record.update(fields)
    return BuildStatus.model_validate(record)


def real_guests() -> list[Guest]:
    return [Guest.model_validate(record) for record in captured("guests.json")]
