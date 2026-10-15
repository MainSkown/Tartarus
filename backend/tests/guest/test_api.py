from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.dependencies import get_guest_control
from app.api.guests import router as guests_router
from app.api.operation_ids import generate_operation_id
from app.db import analysis_repository as repository
from app.db.base import Base
from app.db.models.analysis import AnalysisStatus
from app.errors import install_error_handlers
from app.guest.errors import (
    GuestControlBadResponse,
    GuestControlRejected,
    GuestControlUnreachable,
)
from app.guest.http_errors import install_guest_control_error_handler
from app.guest.schemas import Guest
from tests.guest.fakes import FakeGuestControl
from tests.test_analysis_repository import seeded_analysis

UNREACHABLE_MESSAGE = "The guest control service is not reachable"


@dataclass
class Harness:
    client: httpx.AsyncClient
    app: FastAPI
    factory: async_sessionmaker[AsyncSession]
    control: FakeGuestControl

    async def set_analysis_status(self, status: AnalysisStatus) -> None:
        async with self.factory() as session:
            created = await seeded_analysis(session)
            await repository.update_analysis(session, created.id, status=status)

    def use(self, control: FakeGuestControl) -> FakeGuestControl:
        self.app.dependency_overrides[get_guest_control] = lambda: control
        self.control = control
        return control


def _enable_foreign_keys(dbapi_connection: object, _record: object) -> None:
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture
async def harness(
    tmp_path: Path, make_client: Callable[[FastAPI], httpx.AsyncClient]
) -> AsyncIterator[Harness]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'guests.sqlite3'}")
    event.listen(engine.sync_engine, "connect", _enable_foreign_keys)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI(generate_unique_id_function=generate_operation_id)
    install_error_handlers(app)
    install_guest_control_error_handler(app)
    app.state.session_factory = factory
    app.include_router(guests_router, prefix="/api")
    control = FakeGuestControl()
    app.dependency_overrides[get_guest_control] = lambda: control
    async with make_client(app) as client:
        yield Harness(client, app, factory, control)
    await engine.dispose()


def error_of(response: httpx.Response) -> dict[str, object]:
    error: dict[str, object] = response.json()["error"]
    return error


# --- GET /guests -------------------------------------------------------------------------------


async def test_listing_returns_every_guest_with_what_the_card_shows(harness: Harness) -> None:
    response = await harness.client.get("/api/guests")

    assert response.status_code == 200
    guests = response.json()
    assert [guest["name"] for guest in guests] == ["win", "lab1", "lab2"]
    lab2 = guests[2]
    assert lab2["state"] == "ready"
    assert lab2["badges"] == ["DEFENDER OFF"]
    assert lab2["ip"] == "192.168.150.12"
    assert lab2["resources"] == {"vcpus": 2, "ram_mb": 4096, "disk_gb": 80}
    assert lab2["identity"]["account"] == "Alice"


async def test_listing_with_no_guest_is_an_empty_list(harness: Harness) -> None:
    harness.use(FakeGuestControl(guests=[]))

    response = await harness.client.get("/api/guests")

    assert (response.status_code, response.json()) == (200, [])


async def test_listing_keeps_a_guest_that_is_building_a_failed_one_and_a_broken_one(
    harness: Harness,
) -> None:
    harness.use(
        FakeGuestControl(
            guests=[
                Guest(name="lab3", state="building"),
                Guest(name="lab4", state="failed"),
                Guest(name="lab9", state="broken", error="guest.json is not valid JSON"),
            ]
        )
    )

    response = await harness.client.get("/api/guests")

    assert [(guest["name"], guest["state"]) for guest in response.json()] == [
        ("lab3", "building"),
        ("lab4", "failed"),
        ("lab9", "broken"),
    ]
    assert response.json()[2]["error"] == "guest.json is not valid JSON"


async def test_listing_while_the_control_service_is_down_is_a_502_with_a_fixed_message(
    harness: Harness,
) -> None:
    harness.use(
        FakeGuestControl(error=GuestControlUnreachable("guests", "ConnectError to cape-control"))
    )

    response = await harness.client.get("/api/guests")

    assert response.status_code == 502
    assert error_of(response)["message"] == UNREACHABLE_MESSAGE
    assert "cape-control" not in response.text
    assert "ConnectError" not in response.text


async def test_an_answer_the_backend_cannot_read_is_a_502_that_repeats_nothing_of_it(
    harness: Harness,
) -> None:
    harness.use(FakeGuestControl(error=GuestControlBadResponse("guests", "wrong shape")))

    response = await harness.client.get("/api/guests")

    assert response.status_code == 502
    assert "wrong shape" not in response.text


# --- GET /guests/{name} ------------------------------------------------------------------------


async def test_reading_one_guest_returns_its_record(harness: Harness) -> None:
    response = await harness.client.get("/api/guests/lab1")

    assert response.status_code == 200
    assert response.json()["name"] == "lab1"
    assert response.json()["build_id"] == "b2f48f9dcd08a"


async def test_reading_a_missing_guest_is_a_404_with_the_services_message(
    harness: Harness,
) -> None:
    harness.use(FakeGuestControl(error=GuestControlRejected("guest", 404, "no guest called nope")))

    response = await harness.client.get("/api/guests/nope")

    assert response.status_code == 404
    assert error_of(response) == {
        "code": "not_found",
        "message": "no guest called nope",
        "details": {},
    }


# --- DELETE /guests/{name} ---------------------------------------------------------------------


async def test_deleting_a_guest_answers_204_and_asks_the_control_service(harness: Harness) -> None:
    response = await harness.client.delete("/api/guests/lab2")

    assert response.status_code == 204
    assert response.content == b""
    assert harness.control.calls == [("delete_guest", "lab2")]


@pytest.mark.parametrize(
    "status", [AnalysisStatus.QUEUED, AnalysisStatus.STARTING, AnalysisStatus.RUNNING]
)
async def test_deleting_a_guest_is_refused_with_409_while_an_analysis_needs_a_guest(
    harness: Harness, status: AnalysisStatus
) -> None:
    await harness.set_analysis_status(status)

    response = await harness.client.delete("/api/guests/lab2")

    assert response.status_code == 409
    message = str(error_of(response)["message"])
    assert "delete" in message
    assert "queued, starting or running" in message
    assert harness.control.calls == []


@pytest.mark.parametrize(
    "status", [AnalysisStatus.PROCESSING, AnalysisStatus.DONE, AnalysisStatus.FAILED]
)
async def test_deleting_a_guest_is_allowed_while_only_finished_analyses_exist(
    harness: Harness, status: AnalysisStatus
) -> None:
    await harness.set_analysis_status(status)

    assert (await harness.client.delete("/api/guests/lab2")).status_code == 204


async def test_the_control_services_own_409_is_passed_on_with_its_message(
    harness: Harness,
) -> None:
    message = "the build of lab3 is running; wait for it to finish"
    harness.use(FakeGuestControl(error=GuestControlRejected("delete_guest", 409, message)))

    response = await harness.client.delete("/api/guests/lab3")

    assert response.status_code == 409
    assert error_of(response)["message"] == message


async def test_deleting_a_missing_guest_is_a_404(harness: Harness) -> None:
    harness.use(FakeGuestControl(error=GuestControlRejected("delete_guest", 404, "no guest nope")))

    assert (await harness.client.delete("/api/guests/nope")).status_code == 404


async def test_deleting_while_the_control_service_is_down_is_a_502(harness: Harness) -> None:
    harness.use(FakeGuestControl(error=GuestControlUnreachable("delete_guest", "ReadTimeout")))

    response = await harness.client.delete("/api/guests/lab2")

    assert response.status_code == 502
    assert error_of(response)["message"] == UNREACHABLE_MESSAGE


# --- POST /guests/{name}/check -----------------------------------------------------------------


async def test_a_check_returns_each_probe_with_its_message(harness: Harness) -> None:
    response = await harness.client.post("/api/guests/lab1/check")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "lab1"
    assert [(check["id"], check["ok"]) for check in body["checks"]] == [
        ("domain", True),
        ("snapshot", True),
        ("registration", True),
        ("agent", False),
    ]
    assert harness.control.calls == [("check", "lab1")]


@pytest.mark.parametrize(
    "status", [AnalysisStatus.QUEUED, AnalysisStatus.STARTING, AnalysisStatus.RUNNING]
)
async def test_a_check_is_refused_with_409_while_an_analysis_needs_a_guest(
    harness: Harness, status: AnalysisStatus
) -> None:
    await harness.set_analysis_status(status)

    response = await harness.client.post("/api/guests/lab1/check")

    assert response.status_code == 409
    assert "check" in str(error_of(response)["message"])
    assert harness.control.calls == []


async def test_a_check_the_control_service_refuses_is_a_409_with_its_message(
    harness: Harness,
) -> None:
    message = "the build of lab3 is running; checks restore a snapshot and wait until it is done"
    harness.use(FakeGuestControl(error=GuestControlRejected("check", 409, message)))

    response = await harness.client.post("/api/guests/lab1/check")

    assert (response.status_code, error_of(response)["message"]) == (409, message)


async def test_a_check_while_the_control_service_is_down_is_a_502(harness: Harness) -> None:
    harness.use(FakeGuestControl(error=GuestControlUnreachable("check", "ReadTimeout")))

    assert (await harness.client.post("/api/guests/lab1/check")).status_code == 502


# --- GET /guests/media and /guests/profiles ----------------------------------------------------


async def test_media_lists_the_images_with_their_editions(harness: Harness) -> None:
    response = await harness.client.get("/api/guests/media")

    assert response.status_code == 200
    (iso,) = response.json()
    assert iso["file"] == "Win11_25H2_Polish_x64_v2.iso"
    assert iso["variants"][4]["name"] == "Windows 11 Pro"


async def test_profiles_lists_the_option_schema_the_wizard_renders_from(harness: Harness) -> None:
    response = await harness.client.get("/api/guests/profiles")

    assert response.status_code == 200
    (profile,) = response.json()
    assert profile["id"] == "windows"
    assert [option["key"] for option in profile["options"]][:2] == ["defender", "decoys"]
    assert profile["identity"]["account"]["pattern"] == "[A-Za-z][A-Za-z0-9_-]{0,19}"
    assert [badge["label"] for badge in profile["badges"]] == ["DEFENDER ON", "DEFENDER OFF"]


@pytest.mark.parametrize(
    ("path", "call"), [("/api/guests/media", "media"), ("/api/guests/profiles", "profiles")]
)
async def test_media_and_profiles_are_not_guests_named_media_or_profiles(
    harness: Harness, path: str, call: str
) -> None:
    harness.use(FakeGuestControl(guests=[Guest(name="media", state="ready")]))

    response = await harness.client.get(path)

    assert response.status_code == 200
    assert isinstance(response.json(), list)
    assert harness.control.calls == [(call, None)]


@pytest.mark.parametrize("path", ["/api/guests/media", "/api/guests/profiles"])
async def test_media_and_profiles_while_the_control_service_is_down_are_a_502(
    harness: Harness, path: str
) -> None:
    harness.use(FakeGuestControl(error=GuestControlUnreachable("media", "ConnectError")))

    assert (await harness.client.get(path)).status_code == 502


# --- error mapping -----------------------------------------------------------------------------


async def test_a_422_of_the_control_service_keeps_its_field_problems_in_the_error_envelope(
    harness: Harness,
) -> None:
    rejected = GuestControlRejected(
        "check", 422, "the parameters are not valid", {"name": "must be unique"}
    )
    harness.use(FakeGuestControl(error=rejected))

    response = await harness.client.post("/api/guests/lab1/check")

    assert response.status_code == 422
    assert error_of(response) == {
        "code": "validation_error",
        "message": "the parameters are not valid",
        "details": {
            "fields": [
                {"location": ["body", "name"], "message": "must be unique", "type": "rejected"}
            ]
        },
    }


async def test_a_400_of_the_control_service_is_reported_as_a_422(harness: Harness) -> None:
    harness.use(FakeGuestControl(error=GuestControlRejected("guest", 400, "invalid guest name")))

    response = await harness.client.get("/api/guests/Bad_Name")

    assert response.status_code == 422
    assert error_of(response)["message"] == "invalid guest name"


@pytest.mark.parametrize("status", [405, 411, 413])
async def test_a_refusal_the_api_has_no_meaning_for_is_a_502_without_the_services_words(
    harness: Harness, status: int
) -> None:
    harness.use(FakeGuestControl(error=GuestControlRejected("guests", status, "secret internals")))

    response = await harness.client.get("/api/guests")

    assert response.status_code == 502
    assert "secret internals" not in response.text


async def test_the_token_never_appears_in_an_error_response(harness: Harness) -> None:
    token = "tok-control-0123456789abcdef"  # noqa: S105
    harness.use(
        FakeGuestControl(error=GuestControlUnreachable("guests", f"the token {token} was refused"))
    )

    response = await harness.client.get("/api/guests")

    assert token not in response.text


# --- documentation -----------------------------------------------------------------------------


def test_the_routes_have_the_operation_ids_the_generated_client_is_named_after(
    harness: Harness,
) -> None:
    paths = harness.app.openapi()["paths"]

    operations = {
        (path, method): details["operationId"]
        for path, methods in paths.items()
        for method, details in methods.items()
    }
    assert operations == {
        ("/api/guests", "get"): "guests_list",
        ("/api/guests/media", "get"): "guests_media",
        ("/api/guests/profiles", "get"): "guests_profiles",
        ("/api/guests/{name}", "get"): "guests_read",
        ("/api/guests/{name}", "delete"): "guests_delete",
        ("/api/guests/{name}/check", "post"): "guests_check",
    }
