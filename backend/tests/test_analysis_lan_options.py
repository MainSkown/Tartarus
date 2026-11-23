import pytest
from pydantic import ValidationError

from app.schemas.analysis_requests import AnalysisOptions
from tests import test_analyses_api
from tests.test_analyses_api import Harness

# pytest finds a fixture by its name in the test module, so the shared harness is bound here.
harness = test_analyses_api.harness


def messages(error: ValidationError) -> str:
    return " | ".join(str(each["msg"]) for each in error.errors(include_input=False))


def test_the_fake_lan_is_off_by_default() -> None:
    assert AnalysisOptions().lan_preset is None


@pytest.mark.parametrize("route", ["inetsim", "none", "drop"])
def test_a_preset_is_accepted_on_a_route_that_keeps_the_sample_off_the_analysts_connection(
    route: str,
) -> None:
    options = AnalysisOptions.model_validate({"route": route, "lan_preset": "small-office"})

    assert options.lan_preset == "small-office"


def test_a_preset_with_the_internet_route_is_refused_saying_why() -> None:
    with pytest.raises(ValidationError) as refused:
        AnalysisOptions.model_validate({"route": "internet", "lan_preset": "small-office"})

    text = messages(refused.value)
    assert "lan_preset" in text
    assert "internet" in text
    assert "analyst's own connection" in text


@pytest.mark.parametrize("preset", ["", "Small Office", "../etc", "a", "-office", "x" * 33])
def test_a_preset_that_is_not_a_slug_is_refused(preset: str) -> None:
    with pytest.raises(ValidationError):
        AnalysisOptions.model_validate({"lan_preset": preset})


def test_an_unset_preset_is_left_out_of_the_stored_options() -> None:
    assert "lan_preset" not in AnalysisOptions().model_dump(exclude_none=True)


async def test_the_preset_is_stored_in_the_options_and_read_back(harness: Harness) -> None:
    response = await harness.upload(options={"lan_preset": "small-office"})

    assert response.status_code == 201
    assert response.json()["options"]["lan_preset"] == "small-office"
    (analysis,) = await harness.rows(test_analyses_api.Analysis)
    assert analysis.options["lan_preset"] == "small-office"


async def test_the_internet_route_with_a_preset_is_a_422_naming_the_field(
    harness: Harness,
) -> None:
    response = await harness.upload(options={"route": "internet", "lan_preset": "small-office"})

    assert test_analyses_api.error_locations(response) == [["body", "options", "lan_preset"]]
    assert harness.guests.lan_calls() == []
