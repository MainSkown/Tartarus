import pytest

from app.analyses.lan_check import LanNotReadyError, LanPresetUnknownError
from app.db.models import Analysis, Sample
from app.guest.errors import GuestControlUnreachable
from app.guest.lan_schemas import LanHealth
from app.schemas.analysis_requests import AnalysisOptions
from tests import test_analyses_api
from tests.analyses import test_submission
from tests.analyses.test_submission import Submission
from tests.test_analyses_api import Harness, error_locations

# pytest finds a fixture by its name in the test module, so the shared ones are bound here.
submission = test_submission.submission
harness = test_analyses_api.harness

WITH_PRESET = AnalysisOptions(lan_preset="small-office")


async def test_without_a_preset_no_lan_endpoint_is_called_at_all(submission: Submission) -> None:
    await submission.submit(AnalysisOptions())
    await submission.submit(AnalysisOptions(route="none"))

    assert submission.control.lan_calls() == []


async def test_a_listed_preset_on_healthy_fake_hosts_is_queued_with_the_preset_stored(
    submission: Submission,
) -> None:
    analysis = await submission.submit(WITH_PRESET)

    assert analysis.options["lan_preset"] == "small-office"
    assert [name for name, _ in submission.control.lan_calls()] == ["lan_presets", "lan_health"]


async def test_a_preset_the_control_service_does_not_list_is_refused_naming_it_and_the_choices(
    submission: Submission,
) -> None:
    with pytest.raises(LanPresetUnknownError) as refused:
        await submission.submit(AnalysisOptions(lan_preset="data-center"))

    assert "data-center" in str(refused.value)
    assert "small-office" in str(refused.value)
    assert await submission.rows(Sample) == []
    assert await submission.rows(Analysis) == []
    assert submission.runner.nudges == 0


async def test_an_unknown_preset_is_refused_before_the_health_is_asked(
    submission: Submission,
) -> None:
    with pytest.raises(LanPresetUnknownError):
        await submission.submit(AnalysisOptions(lan_preset="data-center"))

    assert [name for name, _ in submission.control.lan_calls()] == ["lan_presets"]


async def test_fake_hosts_that_are_not_ready_refuse_with_the_reason_and_store_nothing(
    submission: Submission,
) -> None:
    submission.control.lan_health_answer = LanHealth(ready=False, reason="lan-sim is not running")

    with pytest.raises(LanNotReadyError) as refused:
        await submission.submit(WITH_PRESET)

    assert "lan-sim is not running" in str(refused.value)
    assert await submission.rows(Sample) == []
    assert await submission.rows(Analysis) == []
    assert submission.store.root.exists() is False or not list(submission.store.root.rglob("*.zip"))


async def test_fake_hosts_that_are_not_ready_without_a_reason_still_refuse(
    submission: Submission,
) -> None:
    submission.control.lan_health_answer = LanHealth(ready=False)

    with pytest.raises(LanNotReadyError) as refused:
        await submission.submit(WITH_PRESET)

    assert "not ready" in str(refused.value)


async def test_an_unreachable_control_service_is_not_taken_for_a_missing_preset(
    submission: Submission,
) -> None:
    submission.control.error_by_call["lan_presets"] = GuestControlUnreachable(
        "lan_presets", "ConnectError"
    )

    with pytest.raises(GuestControlUnreachable):
        await submission.submit(WITH_PRESET)


async def test_the_api_answers_422_for_an_unknown_preset(harness: Harness) -> None:
    response = await harness.upload(options={"lan_preset": "data-center"})

    assert error_locations(response) == [["body", "options", "lan_preset"]]
    assert "data-center" in response.text
    assert await harness.rows(Analysis) == []


async def test_the_api_answers_503_with_the_reason_for_fake_hosts_that_are_not_ready(
    harness: Harness,
) -> None:
    harness.guests.lan_health_answer = LanHealth(ready=False, reason="lan-sim is not running")

    response = await harness.upload(options={"lan_preset": "small-office"})

    assert response.status_code == 503
    assert "lan-sim is not running" in response.json()["error"]["message"]
    assert await harness.rows(Analysis) == []


async def test_the_api_without_a_preset_calls_no_lan_endpoint(harness: Harness) -> None:
    assert (await harness.upload()).status_code == 201

    assert harness.guests.lan_calls() == []
