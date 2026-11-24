"""The fake hosts of an analysis, looked up at ingest from its preset."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analyses.lan_models import LanPresetRef, LanSummary, LanTotals
from app.analyses.lan_sessions import LanSessions
from app.analyses.ports import IngestResult, ReportOutcome
from app.analyses.runner import Runner
from app.db.models.analysis import AnalysisStatus
from app.guest.errors import GuestControlRejected, GuestControlUnreachable
from app.guest.lan_schemas import LanHost as PresetHost
from app.guest.lan_schemas import LanPreset, LanService
from app.ingest.protocol import LanHost
from tests.analyses.fakes import FakeCape, FakeIngester, FakeReports
from tests.analyses.guest_fakes import ScriptedGuestControl
from tests.analyses.helpers import enqueue, load
from tests.guest.fakes import a_preset
from tests.test_analysis_repository import OPTIONS

type Factory = async_sessionmaker[AsyncSession]

PRESET = "small-office"
WITH_LAN = {**OPTIONS, "lan_preset": PRESET}
OUTCOME = ReportOutcome(score=1.0, max_severity=None, detected_families=[], summary={})
DOMAIN_CONTROLLER = LanHost(
    "dc01.corp.example", "domain-controller", PRESET, {445: "smb"}, "Small office"
)
NAMED_FILE_SERVER = LanHost(
    "fs01.corp.example", "file-server", PRESET, {445: "smb", 3389: "rdp"}, "Small office"
)


class FakeAnalysis:
    def __init__(self, options: dict[str, object]) -> None:
        self.id = 4
        self.options = options


def asked_for(preset: str | None) -> FakeAnalysis:
    return FakeAnalysis({} if preset is None else {"lan_preset": preset})


async def test_an_analysis_without_a_preset_has_no_hosts_and_asks_nothing(
    guests: ScriptedGuestControl,
) -> None:
    hosts, warnings = await LanSessions(guests).hosts_of(asked_for(None))  # type: ignore[arg-type]

    assert (hosts, warnings) == ({}, [])
    assert guests.calls == []


async def test_the_hosts_of_the_preset_are_keyed_by_address_with_their_services_by_port(
    guests: ScriptedGuestControl,
) -> None:
    guests.lan_presets_listed = [
        LanPreset(
            id=PRESET,
            name="Small office",
            description="",
            hosts=[
                PresetHost(
                    fqdn="fs01.corp.example",
                    address="192.168.150.201",
                    role="file-server",
                    services=[LanService(kind="smb", port=445), LanService(kind="rdp", port=3389)],
                )
            ],
        ),
        a_preset("other"),
    ]

    hosts, warnings = await LanSessions(guests).hosts_of(asked_for(PRESET))  # type: ignore[arg-type]

    assert warnings == []
    assert hosts == {"192.168.150.201": NAMED_FILE_SERVER}


async def test_a_preset_the_control_service_no_longer_offers_gives_no_hosts_and_a_warning(
    guests: ScriptedGuestControl,
) -> None:
    guests.lan_presets_listed = [a_preset("other")]

    hosts, warnings = await LanSessions(guests).hosts_of(asked_for(PRESET))  # type: ignore[arg-type]

    assert hosts == {}
    assert len(warnings) == 1
    assert PRESET in warnings[0]


@pytest.mark.parametrize(
    "failure",
    [
        GuestControlUnreachable("lan_presets", "ConnectError"),
        GuestControlRejected("lan_presets", 503, "down"),
    ],
)
async def test_a_control_service_that_cannot_answer_gives_a_warning_and_never_raises(
    guests: ScriptedGuestControl, failure: Exception
) -> None:
    guests.error_by_call["lan_presets"] = failure

    hosts, warnings = await LanSessions(guests).hosts_of(asked_for(PRESET))  # type: ignore[arg-type]

    assert hosts == {}
    assert len(warnings) == 1


async def run_to_the_end(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    options: dict[str, object],
) -> int:
    reports.outcome = OUTCOME
    cape.script_for_new_tasks = ["reported"]
    analysis_id = await enqueue(session_factory, options=options)
    await runner.run_once()
    await runner.run_once()
    return analysis_id


async def test_the_ingest_gets_the_fake_hosts_of_the_analysis(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    ingester: FakeIngester,
) -> None:
    analysis_id = await run_to_the_end(runner, session_factory, cape, reports, WITH_LAN)

    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.DONE
    assert ingester.lan_hosts[analysis_id] == {"192.168.150.200": DOMAIN_CONTROLLER}


async def test_without_a_preset_the_ingest_gets_no_hosts_and_the_lan_is_not_asked(  # noqa: PLR0913, PLR0917 - the runner's fakes
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    ingester: FakeIngester,
    guests: ScriptedGuestControl,
) -> None:
    analysis_id = await run_to_the_end(runner, session_factory, cape, reports, OPTIONS)

    assert not ingester.lan_hosts[analysis_id]
    assert "lan_presets" not in [name for name, _ in guests.calls]
    done = await load(session_factory, analysis_id)
    assert done.summary is not None
    assert "warnings" not in done.summary


async def test_a_lookup_that_fails_ingests_without_the_hosts_and_warns_on_the_analysis(  # noqa: PLR0913, PLR0917 - the runner's fakes
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    ingester: FakeIngester,
    guests: ScriptedGuestControl,
) -> None:
    guests.error_by_call["lan_presets"] = GuestControlUnreachable("lan_presets", "ReadTimeout")
    ingester.result = IngestResult(3, {"network": 3})

    analysis_id = await run_to_the_end(runner, session_factory, cape, reports, WITH_LAN)

    done = await load(session_factory, analysis_id)
    assert done.status is AnalysisStatus.DONE
    assert not ingester.lan_hosts[analysis_id]
    assert done.summary is not None
    [warning] = done.summary["warnings"]
    assert "fake local network" in warning


async def test_a_lookup_warning_is_added_to_the_warnings_the_report_already_has(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    guests: ScriptedGuestControl,
) -> None:
    guests.error_by_call["lan_presets"] = GuestControlUnreachable("lan_presets", "ReadTimeout")
    reports.outcome = ReportOutcome(
        score=1.0, max_severity=None, detected_families=[], summary={"warnings": ["no sysmon"]}
    )
    cape.script_for_new_tasks = ["reported"]
    analysis_id = await enqueue(session_factory, options=WITH_LAN)
    await runner.run_once()
    await runner.run_once()

    done = await load(session_factory, analysis_id)
    assert done.summary is not None
    assert done.summary["warnings"][0] == "no sysmon"
    assert len(done.summary["warnings"]) == 2


A_LAN_SUMMARY = LanSummary(
    preset=LanPresetRef(id=PRESET, name="Small office"),
    hosts=[],
    totals=LanTotals(hosts=0, attempts=0, credentials=0, files=0),
)


async def test_the_lan_summary_of_the_ingest_is_stored_with_the_analysis(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    ingester: FakeIngester,
) -> None:
    ingester.result = IngestResult(3, {"network": 3}, lan=A_LAN_SUMMARY)

    analysis_id = await run_to_the_end(runner, session_factory, cape, reports, WITH_LAN)

    done = await load(session_factory, analysis_id)
    assert done.summary is not None
    assert done.summary["lan"] == A_LAN_SUMMARY.model_dump(mode="json")


async def test_an_analysis_without_a_preset_stores_no_lan_key(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    ingester: FakeIngester,
) -> None:
    analysis_id = await run_to_the_end(runner, session_factory, cape, reports, OPTIONS)

    done = await load(session_factory, analysis_id)
    assert done.summary is not None
    assert "lan" not in done.summary


async def test_a_preset_whose_hosts_could_not_be_looked_up_stores_an_empty_lan_section(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    guests: ScriptedGuestControl,
) -> None:
    guests.error_by_call["lan_presets"] = GuestControlUnreachable("lan_presets", "ReadTimeout")

    analysis_id = await run_to_the_end(runner, session_factory, cape, reports, WITH_LAN)

    done = await load(session_factory, analysis_id)
    assert done.summary is not None
    assert done.summary["lan"]["preset"] == {"id": PRESET, "name": PRESET}
    assert done.summary["lan"]["hosts"] == []
