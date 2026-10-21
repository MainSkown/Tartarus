"""Turns what the self-test saw into its verdict. Pure: no I/O, so each case is a table row.

The signals are the ones a guest profile declares (`selftest.signals`); a profile may only name
signals this module can judge, and one it cannot is a failure rather than a silent pass.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.guest.schemas import SelfTestChecks
from app.guest.selftest import SelfTestVerdict

# The name every bundled self-test sample resolves, and nothing else in a guest does.
SELFTEST_LOOKUP_NAME = "tartarus-selftest.example"
# The sample and the process it starts: fewer means the child process was never seen.
MIN_PROCESSES = 2
PASSED_MESSAGE = "all checks passed"
# Reported by the guest's facts script: the apps still open on the desktop of the clean snapshot.
OPEN_APPS_FACT = "desktop.app_windows"
# Facts the analyst sees on the guest's card; the rest stay in the control service's log.
SUMMARISED_FACTS = (
    "os.hostname",
    "os.user",
    "defender.antivirus_enabled",
    "defender.realtime_enabled",
    "defender.tamper_protected",
)


class DnsLookup(StrEnum):
    ANSWERED = "answered"
    UNANSWERED = "unanswered"
    ABSENT = "absent"


@dataclass(frozen=True)
class AnalysisOutcome:
    """How the self-test's analysis ended; `finished` is False when the wait ran out."""

    analysis_id: int
    status: str
    finished: bool
    error: str | None = None

    @property
    def done(self) -> bool:
        return self.finished and self.status == "done"


@dataclass(frozen=True)
class Evidence:
    """What the finished analysis' own data holds."""

    process_count: int
    file_events: int
    registry_events: int
    dns: DnsLookup
    report_present: bool


@dataclass(frozen=True)
class ChecksRefused:
    """The control service answered that it could not run the checks, and why."""

    message: str


@dataclass(frozen=True)
class _Signal:
    ok: bool
    message: str


type _Judge = Callable[[Evidence], _Signal]


def _processes(evidence: Evidence) -> _Signal:
    count = evidence.process_count
    if count >= MIN_PROCESSES:
        return _Signal(True, f"{count} processes recorded")
    if count == 0:
        return _Signal(False, "no process was recorded")
    return _Signal(False, "only the sample's own process was recorded, not its child process")


def _events_of(lane: str, count: int) -> _Signal:
    if count:
        return _Signal(True, f"{count} {lane} events recorded")
    return _Signal(False, f"no {lane} event was recorded")


def _report(evidence: Evidence) -> _Signal:
    if evidence.report_present:
        return _Signal(True, "the analysis has a report")
    return _Signal(False, "the analysis has no report")


def _dns(evidence: Evidence) -> _Signal:
    if evidence.dns is DnsLookup.ABSENT:
        return _Signal(
            False, f"the lookup of {SELFTEST_LOOKUP_NAME} was not seen in the network events"
        )
    # A real analysis of the sample (task 6) records the lookup with no answer at all, so an
    # answer is reported but not required.
    answer = "answered" if evidence.dns is DnsLookup.ANSWERED else "with no answer recorded"
    return _Signal(True, f"{SELFTEST_LOOKUP_NAME} was looked up, {answer}")


SIGNAL_JUDGES: Mapping[str, _Judge] = {
    "events.process": _processes,
    "events.file": lambda evidence: _events_of("file", evidence.file_events),
    "events.registry": lambda evidence: _events_of("registry", evidence.registry_events),
    "report.present": _report,
    "report.dns_answer": _dns,
}


def judge(
    signal_ids: Sequence[str],
    outcome: AnalysisOutcome,
    evidence: Evidence | None,
    checks: SelfTestChecks | ChecksRefused | None,
) -> SelfTestVerdict:
    """`evidence` and `checks` are only needed, and only looked at, when the analysis is done."""
    if not outcome.done:
        return _verdict(outcome, [_unfinished_message(outcome)], signals={})
    if evidence is None or checks is None:
        raise ValueError("a finished analysis needs its evidence and the guest checks to be judged")
    signals = {signal_id: _signal(signal_id, evidence) for signal_id in signal_ids}
    problems = [signal.message for signal in signals.values() if not signal.ok]
    if isinstance(checks, ChecksRefused):
        problems.append(f"the checks inside the guest could not run: {checks.message}")
        return _verdict(outcome, problems, signals)
    problems += _check_problems(checks)
    return _verdict(outcome, problems, signals, checks)


def not_run(message: str) -> SelfTestVerdict:
    """A failing verdict for a test that could not even start."""
    details = _details(message, None, {}, None)
    return SelfTestVerdict(passed=False, details=details)


def _signal(signal_id: str, evidence: Evidence) -> _Signal:
    judge_signal = SIGNAL_JUDGES.get(signal_id)
    if judge_signal is None:
        return _Signal(
            False, f"the signal {signal_id} of the profile is not one the backend can judge"
        )
    return judge_signal(evidence)


def _check_problems(checks: SelfTestChecks) -> list[str]:
    problems = []
    if checks.giveaways:
        problems.append(f"the guest gives itself away: {'; '.join(checks.giveaways)}")
    problems += _open_apps_problem(checks)
    problems += [
        f"{name}: {proof.message}" for name, proof in checks.proofs.items() if not proof.ok
    ]
    return problems


def _open_apps_problem(checks: SelfTestChecks) -> list[str]:
    names = [name.strip() for name in checks.facts.get(OPEN_APPS_FACT, "").split(",")]
    names = [name for name in names if name]
    if not names:
        return []
    noun = "an open app" if len(names) == 1 else "open apps"
    return [f"the clean snapshot has {noun}: {', '.join(names)}"]


def _unfinished_message(outcome: AnalysisOutcome) -> str:
    if not outcome.finished:
        return (
            f"the self-test analysis {outcome.analysis_id} did not finish in time "
            f"(still {outcome.status})"
        )
    reason = f": {outcome.error}" if outcome.error else ""
    return f"the self-test analysis {outcome.analysis_id} ended {outcome.status}{reason}"


def _verdict(
    outcome: AnalysisOutcome,
    problems: list[str],
    signals: Mapping[str, _Signal],
    checks: SelfTestChecks | None = None,
) -> SelfTestVerdict:
    message = "; ".join(problems) if problems else PASSED_MESSAGE
    details = _details(message, outcome.analysis_id, signals, checks)
    return SelfTestVerdict(passed=not problems, details=details)


def _details(
    message: str,
    analysis_id: int | None,
    signals: Mapping[str, _Signal],
    checks: SelfTestChecks | None,
) -> dict[str, Any]:
    return {
        "message": message,
        "analysis_id": analysis_id,
        "signals": {
            signal_id: {"ok": signal.ok, "message": signal.message}
            for signal_id, signal in signals.items()
        },
        "proofs": {
            name: {"ok": proof.ok, "message": proof.message}
            for name, proof in (checks.proofs if checks else {}).items()
        },
        "giveaways": list(checks.giveaways) if checks else [],
        "facts_summary": _facts_summary(checks),
    }


def _facts_summary(checks: SelfTestChecks | None) -> dict[str, str]:
    facts = checks.facts if checks else {}
    return {key: facts[key] for key in SUMMARISED_FACTS if key in facts}
