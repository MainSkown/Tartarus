import pytest

from app.db.models.analysis import AnalysisStatus
from tests.guest.fakes import BUILD_ID
from tests.guest.harness import Harness
from tests.guest.test_api import error_of
from tests.guest.test_build_api import BUILD_BODY, CLONE_BODY

GUEST_ROUTES: list[tuple[str, str, object]] = [
    ("POST", "/api/guests/build", BUILD_BODY),
    ("POST", f"/api/guests/builds/{BUILD_ID}/resume", None),
    ("POST", f"/api/guests/builds/{BUILD_ID}/restart", None),
    ("POST", f"/api/guests/builds/{BUILD_ID}/continue", None),
    ("POST", f"/api/guests/builds/{BUILD_ID}/cancel", None),
    ("POST", "/api/guests/lab1/clone", CLONE_BODY),
    ("DELETE", "/api/guests/lab1", None),
    ("POST", "/api/guests/lab1/check", None),
    ("POST", "/api/guests/lab1/selftest", None),
]


@pytest.mark.parametrize(("method", "path", "body"), GUEST_ROUTES)
async def test_every_guest_route_names_both_running_analyses_and_not_the_queued_one(
    harness: Harness, method: str, path: str, body: object
) -> None:
    first = await harness.add_analysis(AnalysisStatus.RUNNING, "lab1")
    second = await harness.add_analysis(AnalysisStatus.RUNNING, "lab2")
    queued = await harness.add_analysis(AnalysisStatus.QUEUED, "lab3")

    response = await harness.client.request(method, path, json=body)

    message = str(error_of(response)["message"])
    assert response.status_code == 409
    assert f"analysis {first} on lab1" in message
    assert f"analysis {second} on lab2" in message
    assert f"analysis {queued} on lab3" not in message
    assert harness.control.calls == []


@pytest.mark.parametrize(("method", "path", "body"), GUEST_ROUTES)
async def test_every_guest_route_is_allowed_once_both_running_analyses_ended(
    harness: Harness, method: str, path: str, body: object
) -> None:
    first = await harness.add_analysis(AnalysisStatus.RUNNING, "lab1")
    second = await harness.add_analysis(AnalysisStatus.RUNNING, "lab2")
    queued = await harness.add_analysis(AnalysisStatus.QUEUED, "lab3")
    await harness.set_status(first, AnalysisStatus.DONE)
    await harness.set_status(second, AnalysisStatus.DONE)
    await harness.set_status(queued, AnalysisStatus.CANCELLED)

    response = await harness.client.request(method, path, json=body)

    assert 200 <= response.status_code < 300


async def test_one_running_analysis_that_ended_no_longer_appears_in_the_refusal(
    harness: Harness,
) -> None:
    ended = await harness.add_analysis(AnalysisStatus.RUNNING, "lab1")
    still = await harness.add_analysis(AnalysisStatus.RUNNING, "lab2")
    await harness.set_status(ended, AnalysisStatus.DONE)

    response = await harness.client.delete("/api/guests/lab3")

    message = str(error_of(response)["message"])
    assert response.status_code == 409
    assert f"analysis {still} on lab2" in message
    assert f"analysis {ended} on lab1" not in message


async def test_a_queued_analysis_alone_holds_the_guest_and_is_named(harness: Harness) -> None:
    queued = await harness.add_analysis(AnalysisStatus.QUEUED, "lab3")

    response = await harness.client.delete("/api/guests/lab1")

    assert response.status_code == 409
    assert f"analysis {queued} on lab3" in str(error_of(response)["message"])
