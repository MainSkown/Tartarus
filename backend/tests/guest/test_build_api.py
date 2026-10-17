from typing import Any

import pytest
from sqlalchemy import select

from app.db.models import Job
from app.db.models.analysis import AnalysisStatus
from app.db.models.job import JobStatus, JobType
from app.guest.errors import GuestControlRejected, GuestControlUnreachable
from tests.guest.fakes import BUILD_ID, FakeGuestControl, Poll, a_build
from tests.guest.harness import Harness
from tests.guest.test_api import error_of

BUILD_BODY: dict[str, Any] = {
    "profile": "windows",
    "name": "lab3",
    "media": {"file": "win11.iso", "variant": "Windows 11 Pro"},
    "options": {"defender": False},
    "resources": {"vcpus": 2, "ram_mb": 4096, "disk_gb": 80},
}
CLONE_BODY: dict[str, Any] = {"name": "lab4", "options": {"defender": True}}
BUILD_ACTIONS = ["resume", "restart", "continue"]
ACTIVE_ANALYSIS_STATUSES = [AnalysisStatus.QUEUED, AnalysisStatus.STARTING, AnalysisStatus.RUNNING]


async def jobs_of(harness: Harness) -> list[Job]:
    async with harness.factory() as session:
        return list(await session.scalars(select(Job)))


def started(harness: Harness, *, guest: str = "lab3", kind: str = "build") -> FakeGuestControl:
    harness.control.polls = [Poll(a_build("running", guest=guest, kind=kind))]
    return harness.control


# --- POST /guests/build ---------------------------------------------------------------------------


async def test_starting_a_build_hands_the_parameters_to_the_control_service_and_tracks_it(
    harness: Harness,
) -> None:
    control = started(harness)

    response = await harness.client.post("/api/guests/build", json=BUILD_BODY)

    [job] = await jobs_of(harness)
    assert response.status_code == 202
    assert response.json() == {"job_id": job.id, "build_id": BUILD_ID, "guest": "lab3"}
    assert control.calls_named("start_build") == [BUILD_BODY]
    assert (job.type, job.status, job.analysis_id) == (JobType.GUEST_BUILD, JobStatus.PENDING, None)


@pytest.mark.parametrize("body", [[], "text", 3])
async def test_a_build_body_that_is_not_an_object_is_refused_without_asking_anyone(
    harness: Harness, body: object
) -> None:
    response = await harness.client.post("/api/guests/build", json=body)

    assert response.status_code == 422
    assert harness.control.calls == []


@pytest.mark.parametrize("status", ACTIVE_ANALYSIS_STATUSES)
async def test_a_build_is_refused_with_409_while_an_analysis_needs_a_guest(
    harness: Harness, status: AnalysisStatus
) -> None:
    await harness.set_analysis_status(status)

    response = await harness.client.post("/api/guests/build", json=BUILD_BODY)

    assert response.status_code == 409
    assert "queued, starting or running" in str(error_of(response)["message"])
    assert "built" in str(error_of(response)["message"])
    assert harness.control.calls == []
    assert await jobs_of(harness) == []


async def test_a_build_the_control_service_finds_wrong_is_a_422_with_its_fields(
    harness: Harness,
) -> None:
    harness.control.error_by_call["start_build"] = GuestControlRejected(
        "start_build", 422, "the build is not valid", {"name": "that name is taken"}
    )

    response = await harness.client.post("/api/guests/build", json=BUILD_BODY)

    assert response.status_code == 422
    assert error_of(response)["details"] == {
        "fields": [
            {"location": ["body", "name"], "message": "that name is taken", "type": "rejected"}
        ]
    }
    assert await jobs_of(harness) == []


async def test_a_second_build_is_refused_with_the_control_services_409_and_no_job(
    harness: Harness,
) -> None:
    message = "the build of lab1 is running; wait for it to finish"
    harness.control.error_by_call["start_build"] = GuestControlRejected("start_build", 409, message)

    response = await harness.client.post("/api/guests/build", json=BUILD_BODY)

    assert (response.status_code, error_of(response)["message"]) == (409, message)
    assert await jobs_of(harness) == []


async def test_a_build_while_the_control_service_is_down_is_a_502(harness: Harness) -> None:
    harness.use(FakeGuestControl(error=GuestControlUnreachable("start_build", "ConnectError")))

    response = await harness.client.post("/api/guests/build", json=BUILD_BODY)

    assert response.status_code == 502


# --- POST /guests/{name}/clone --------------------------------------------------------------------


async def test_cloning_a_guest_starts_the_clone_and_tracks_the_new_guest(harness: Harness) -> None:
    control = started(harness, guest="lab4", kind="clone")

    response = await harness.client.post("/api/guests/lab1/clone", json=CLONE_BODY)

    [job] = await jobs_of(harness)
    assert response.status_code == 202
    assert response.json() == {"job_id": job.id, "build_id": BUILD_ID, "guest": "lab4"}
    assert control.calls_named("start_clone") == [("lab1", CLONE_BODY)]
    assert job.type is JobType.GUEST_BUILD


@pytest.mark.parametrize("status", ACTIVE_ANALYSIS_STATUSES)
async def test_a_clone_is_refused_with_409_while_an_analysis_needs_a_guest(
    harness: Harness, status: AnalysisStatus
) -> None:
    await harness.set_analysis_status(status)

    response = await harness.client.post("/api/guests/lab1/clone", json=CLONE_BODY)

    assert response.status_code == 409
    assert "cloned" in str(error_of(response)["message"])
    assert harness.control.calls == []


@pytest.mark.parametrize(
    ("status", "code", "message"),
    [
        (404, "not_found", "no guest called nope"),
        (409, "conflict", "lab2 is failed; only a ready guest can be cloned"),
        (422, "validation_error", "the clone is not valid"),
    ],
)
async def test_a_clone_the_control_service_refuses_passes_its_answer_on_and_starts_no_job(
    harness: Harness, status: int, code: str, message: str
) -> None:
    harness.control.error_by_call["start_clone"] = GuestControlRejected(
        "start_clone", status, message
    )

    response = await harness.client.post("/api/guests/nope/clone", json=CLONE_BODY)

    assert (response.status_code, error_of(response)["code"]) == (status, code)
    assert error_of(response)["message"] == message
    assert await jobs_of(harness) == []


# --- GET /guests/builds/{build_id} ----------------------------------------------------------------


async def test_a_build_is_read_with_its_status_and_the_last_lines_of_its_log(
    harness: Harness,
) -> None:
    harness.control.polls = [
        Poll(
            a_build("paused", percent=62, message="tamper-off", pause="Switch it off"),
            log=["== step tamper-off", "STEP Switching it off"],
        )
    ]

    response = await harness.client.get(f"/api/guests/builds/{BUILD_ID}")

    body = response.json()
    assert response.status_code == 200
    assert (body["id"], body["guest"], body["status"], body["percent"]) == (
        BUILD_ID,
        "lab1",
        "paused",
        62,
    )
    assert body["pause"] == {"instructions": "Switch it off"}
    assert body["log"] == ["== step tamper-off", "STEP Switching it off"]
    assert len(body["steps"]) == 7


async def test_the_log_tail_defaults_to_200_lines_and_follows_the_tail_parameter(
    harness: Harness,
) -> None:
    await harness.client.get(f"/api/guests/builds/{BUILD_ID}")
    await harness.client.get(f"/api/guests/builds/{BUILD_ID}", params={"tail": 5})

    assert harness.control.calls_named("build_log") == [(BUILD_ID, 200), (BUILD_ID, 5)]


@pytest.mark.parametrize("tail", [0, -1, 2001, "many"])
async def test_a_log_tail_outside_1_to_2000_is_a_422(harness: Harness, tail: object) -> None:
    response = await harness.client.get(f"/api/guests/builds/{BUILD_ID}", params={"tail": tail})

    assert response.status_code == 422
    assert harness.control.calls == []


async def test_an_unknown_build_is_a_404_with_the_services_message(harness: Harness) -> None:
    harness.control.error_by_call["build"] = GuestControlRejected("build", 404, "no build bxx")

    response = await harness.client.get("/api/guests/builds/bxx")

    assert (response.status_code, error_of(response)["message"]) == (404, "no build bxx")


# --- GET /guests/builds/active --------------------------------------------------------------------


async def test_with_no_build_followed_the_active_build_is_a_404(harness: Harness) -> None:
    response = await harness.client.get("/api/guests/builds/active")

    assert response.status_code == 404
    assert "No guest build" in str(error_of(response)["message"])
    assert harness.control.calls == []


async def test_the_active_build_names_its_guest_build_and_job(harness: Harness) -> None:
    started(harness)
    started_response = await harness.client.post("/api/guests/build", json=BUILD_BODY)

    response = await harness.client.get("/api/guests/builds/active")

    assert response.status_code == 200
    assert response.json() == {
        "build_id": BUILD_ID,
        "guest": "lab3",
        "job_id": started_response.json()["job_id"],
    }


# --- POST /guests/builds/{build_id}/resume|restart|continue ---------------------------------------


@pytest.mark.parametrize("action", BUILD_ACTIONS)
async def test_a_build_action_is_asked_of_the_control_service_and_a_new_job_follows_the_build(
    harness: Harness, action: str
) -> None:
    started(harness)

    response = await harness.client.post(f"/api/guests/builds/{BUILD_ID}/{action}")

    [job] = await jobs_of(harness)
    assert response.status_code == 202
    assert response.json() == {"job_id": job.id, "build_id": BUILD_ID, "guest": "lab3"}
    assert harness.control.calls_named(action) == [BUILD_ID]


@pytest.mark.parametrize("action", BUILD_ACTIONS)
async def test_no_second_job_follows_a_build_that_already_has_one(
    harness: Harness, action: str
) -> None:
    started(harness)
    first = await harness.client.post("/api/guests/build", json=BUILD_BODY)

    second = await harness.client.post(f"/api/guests/builds/{BUILD_ID}/{action}")

    assert second.status_code == 202
    assert second.json()["job_id"] == first.json()["job_id"]
    assert len(await jobs_of(harness)) == 1


@pytest.mark.parametrize("action", BUILD_ACTIONS)
async def test_a_build_action_is_refused_with_409_while_an_analysis_needs_a_guest(
    harness: Harness, action: str
) -> None:
    await harness.set_analysis_status(AnalysisStatus.RUNNING)

    response = await harness.client.post(f"/api/guests/builds/{BUILD_ID}/{action}")

    assert response.status_code == 409
    assert harness.control.calls == []


@pytest.mark.parametrize("action", BUILD_ACTIONS)
@pytest.mark.parametrize(("status", "code"), [(404, "not_found"), (409, "conflict")])
async def test_a_build_action_the_control_service_refuses_passes_its_answer_on_and_starts_no_job(
    harness: Harness, action: str, status: int, code: str
) -> None:
    harness.control.error_by_call[action] = GuestControlRejected(action, status, "not now")

    response = await harness.client.post(f"/api/guests/builds/{BUILD_ID}/{action}")

    assert (response.status_code, error_of(response)["code"]) == (status, code)
    assert await jobs_of(harness) == []


# --- POST /guests/builds/{build_id}/cancel --------------------------------------------------------


async def test_cancelling_a_build_is_asked_of_the_control_service_and_starts_no_job(
    harness: Harness,
) -> None:
    started(harness)

    response = await harness.client.post(f"/api/guests/builds/{BUILD_ID}/cancel")

    assert response.status_code == 202
    assert harness.control.calls_named("cancel") == [BUILD_ID]
    assert await jobs_of(harness) == []


async def test_cancelling_leaves_the_job_that_already_follows_the_build_in_place(
    harness: Harness,
) -> None:
    started(harness)
    first = await harness.client.post("/api/guests/build", json=BUILD_BODY)

    await harness.client.post(f"/api/guests/builds/{BUILD_ID}/cancel")

    [job] = await jobs_of(harness)
    assert job.id == first.json()["job_id"]


async def test_cancelling_is_refused_with_409_while_an_analysis_needs_a_guest(
    harness: Harness,
) -> None:
    await harness.set_analysis_status(AnalysisStatus.RUNNING)

    response = await harness.client.post(f"/api/guests/builds/{BUILD_ID}/cancel")

    assert response.status_code == 409
    assert harness.control.calls == []


@pytest.mark.parametrize(("status", "code"), [(404, "not_found"), (409, "conflict")])
async def test_a_cancel_the_control_service_refuses_passes_its_answer_on(
    harness: Harness, status: int, code: str
) -> None:
    harness.control.error_by_call["cancel"] = GuestControlRejected("cancel", status, "not now")

    response = await harness.client.post(f"/api/guests/builds/{BUILD_ID}/cancel")

    assert (response.status_code, error_of(response)["code"]) == (status, code)
    assert await jobs_of(harness) == []


async def test_cancelling_while_the_control_service_is_down_is_a_502(harness: Harness) -> None:
    harness.use(FakeGuestControl(error=GuestControlUnreachable("cancel", "ReadTimeout")))

    response = await harness.client.post(f"/api/guests/builds/{BUILD_ID}/cancel")

    assert response.status_code == 502


# --- routing --------------------------------------------------------------------------------------


async def test_the_fixed_build_paths_are_not_taken_for_a_guest_name(harness: Harness) -> None:
    await harness.client.get("/api/guests/builds/active")
    await harness.client.get(f"/api/guests/builds/{BUILD_ID}")

    assert harness.control.calls_named("guest") == []
