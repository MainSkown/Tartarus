import dataclasses
from typing import Any

import pytest

from app.guest.schemas import ProofResult, SelfTestChecks
from app.guest.selftest_verdict import (
    AnalysisOutcome,
    ChecksRefused,
    DnsLookup,
    Evidence,
    judge,
)
from tests.guest.fakes import clean_checks

ALL_SIGNALS = [
    "events.process",
    "events.file",
    "events.registry",
    "report.present",
    "report.dns_answer",
]
FINISHED = AnalysisOutcome(analysis_id=41, status="done", finished=True)
FULL_EVIDENCE = Evidence(
    process_count=2,
    file_events=5,
    registry_events=1,
    dns=DnsLookup.ANSWERED,
    report_present=True,
)


def judged(
    *,
    outcome: AnalysisOutcome = FINISHED,
    evidence: Evidence | None = FULL_EVIDENCE,
    checks: SelfTestChecks | ChecksRefused | None = None,
    signals: list[str] | None = None,
) -> Any:
    return judge(
        ALL_SIGNALS if signals is None else signals,
        outcome,
        evidence,
        clean_checks() if checks is None else checks,
    )


def test_everything_present_and_clean_checks_pass() -> None:
    verdict = judged()

    assert verdict.passed is True
    assert verdict.details["message"] == "all checks passed"
    assert verdict.details["analysis_id"] == 41
    assert verdict.details["giveaways"] == []
    assert {
        signal: result["ok"] for signal, result in verdict.details["signals"].items()
    } == dict.fromkeys(ALL_SIGNALS, True)


@pytest.mark.parametrize(
    ("signal", "evidence", "words"),
    [
        ("events.process", dataclasses.replace(FULL_EVIDENCE, process_count=1), "child process"),
        ("events.process", dataclasses.replace(FULL_EVIDENCE, process_count=0), "no process"),
        ("events.file", dataclasses.replace(FULL_EVIDENCE, file_events=0), "file event"),
        ("events.registry", dataclasses.replace(FULL_EVIDENCE, registry_events=0), "registry"),
        ("report.present", dataclasses.replace(FULL_EVIDENCE, report_present=False), "no report"),
        (
            "report.dns_answer",
            dataclasses.replace(FULL_EVIDENCE, dns=DnsLookup.ABSENT),
            "tartarus-selftest.example was not seen",
        ),
    ],
)
def test_each_missing_signal_alone_fails_with_its_own_message(
    signal: str, evidence: Evidence, words: str
) -> None:
    verdict = judged(evidence=evidence)

    assert verdict.passed is False
    assert words in verdict.details["message"]
    failing = [name for name, result in verdict.details["signals"].items() if not result["ok"]]
    assert failing == [signal]
    assert words in verdict.details["signals"][signal]["message"]


def test_a_lookup_nobody_answered_still_passes_and_says_so() -> None:
    verdict = judged(evidence=dataclasses.replace(FULL_EVIDENCE, dns=DnsLookup.UNANSWERED))

    assert verdict.passed is True
    assert "no answer recorded" in verdict.details["signals"]["report.dns_answer"]["message"]


def test_every_signal_missing_at_once_names_each_of_them() -> None:
    nothing = Evidence(0, 0, 0, DnsLookup.ABSENT, report_present=False)

    verdict = judged(evidence=nothing)

    assert verdict.passed is False
    assert all(not result["ok"] for result in verdict.details["signals"].values())
    for words in ("no process", "file event", "registry", "no report", "tartarus-selftest"):
        assert words in verdict.details["message"]


def test_a_signal_the_backend_does_not_know_fails_instead_of_passing_unchecked() -> None:
    verdict = judged(signals=[*ALL_SIGNALS, "report.child_process"])

    assert verdict.passed is False
    assert "report.child_process" in verdict.details["signals"]["report.child_process"]["message"]


def test_only_the_signals_of_the_profile_are_judged() -> None:
    nothing = Evidence(0, 0, 0, DnsLookup.ABSENT, report_present=False)

    verdict = judged(evidence=nothing, signals=["events.process"])

    assert list(verdict.details["signals"]) == ["events.process"]


@pytest.mark.parametrize(
    ("outcome", "words"),
    [
        (AnalysisOutcome(41, "failed", finished=True, error="the guest agent timed out"), "agent"),
        (AnalysisOutcome(41, "report_failed", finished=True), "report_failed"),
        (AnalysisOutcome(41, "cancelled", finished=True), "cancelled"),
        (AnalysisOutcome(41, "running", finished=False), "did not finish"),
    ],
)
def test_an_analysis_that_did_not_end_done_fails_without_reading_events_or_checks(
    outcome: AnalysisOutcome, words: str
) -> None:
    verdict = judge(ALL_SIGNALS, outcome, evidence=None, checks=None)

    assert verdict.passed is False
    assert words in verdict.details["message"]
    assert verdict.details["analysis_id"] == 41
    assert verdict.details["signals"] == {}


def test_a_finished_analysis_without_its_evidence_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match="evidence"):
        judge(ALL_SIGNALS, FINISHED, evidence=None, checks=clean_checks())


def test_every_giveaway_is_listed_and_fails() -> None:
    checks = clean_checks().model_copy(
        update={"giveaways": ["scheduled task: SandboxAgent", "local account: analyst"]}
    )

    verdict = judged(checks=checks)

    assert verdict.passed is False
    assert verdict.details["giveaways"] == checks.giveaways
    assert "SandboxAgent" in verdict.details["message"]
    assert "analyst" in verdict.details["message"]


def test_a_failing_proof_fails_with_its_message() -> None:
    checks = clean_checks().model_copy(
        update={"proofs": {"eicar": ProofResult(ok=False, message="Defender removed the file")}}
    )

    verdict = judged(checks=checks)

    assert verdict.passed is False
    assert verdict.details["proofs"] == {
        "eicar": {"ok": False, "message": "Defender removed the file"}
    }
    assert "eicar: Defender removed the file" in verdict.details["message"]


def test_a_passing_proof_is_kept_in_the_details() -> None:
    verdict = judged()

    assert verdict.details["proofs"]["eicar"]["ok"] is True


def test_checks_the_control_service_refused_fail_with_its_reason() -> None:
    verdict = judged(checks=ChecksRefused("a build is running"))

    assert verdict.passed is False
    assert "a build is running" in verdict.details["message"]
    assert verdict.details["proofs"] == {}


def test_signal_and_check_failures_are_all_in_one_message() -> None:
    checks = clean_checks().model_copy(update={"giveaways": ["service: Cuckoo Agent"]})
    evidence = dataclasses.replace(FULL_EVIDENCE, registry_events=0)

    verdict = judged(evidence=evidence, checks=checks)

    assert "registry" in verdict.details["message"]
    assert "Cuckoo Agent" in verdict.details["message"]


def test_the_facts_summary_has_a_few_chosen_facts_and_never_the_password() -> None:
    checks = clean_checks().model_copy(
        update={
            "facts": {
                "os.hostname": "DESKTOP-4F7Q",
                "os.user": "jan",
                "defender.realtime_enabled": "False",
                "defender.tamper_protected": "False",
                "password": "hunter2",
                "bios.serial": "ABC123",
            }
        }
    )

    summary = judged(checks=checks).details["facts_summary"]

    assert summary == {
        "os.hostname": "DESKTOP-4F7Q",
        "os.user": "jan",
        "defender.realtime_enabled": "False",
        "defender.tamper_protected": "False",
    }


def test_facts_the_guest_did_not_report_are_left_out_of_the_summary() -> None:
    checks = clean_checks().model_copy(update={"facts": {"os.user": "jan"}})

    assert judged(checks=checks).details["facts_summary"] == {"os.user": "jan"}
