import io
from collections.abc import Callable
from datetime import UTC, datetime
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import HTTP
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from app.cape.client import CapeClient
from app.cape.errors import (
    CapeAuthError,
    CapeBadResponse,
    CapeError,
    CapeNotConfigured,
    CapeRejected,
    CapeTaskNotFound,
    CapeUnreachable,
)
from app.config import Settings
from tests.cape.conftest import (
    BASE_URL,
    TOKEN,
    Handler,
    RecordingCape,
    captured_response,
    json_response,
)

type ClientFactory = Callable[[Handler, str | None], CapeClient]

# Built by hand from the `tasks_create_file` view in CAPE's web/apiv2/views.py, not captured:
# the real container was not used for a submission while this client was written. The view
# answers `error: []`, `data.task_ids` and a human message; `url` only appears when
# [filecreate] status is on.
SUBMITTED = {
    "error": [],
    "data": {"task_ids": [7], "message": "Task ID 7 has been submitted"},
    "errors": [],
}


def multipart_parts(request: httpx.Request) -> dict[str, EmailMessage]:
    raw = b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n"
    message = BytesParser(policy=HTTP).parsebytes(raw + request.content)
    return {
        str(part.get_param("name", header="content-disposition")): part
        for part in message.iter_parts()
    }  # type: ignore[misc]


def parse_multipart(request: httpx.Request) -> dict[str, bytes]:
    return {name: part.get_payload(decode=True) for name, part in multipart_parts(request).items()}


def multipart_filename(request: httpx.Request) -> str | None:
    return multipart_parts(request)["file"].get_filename()


async def test_calls_carry_the_token_in_an_authorization_header(
    cape_client: ClientFactory,
) -> None:
    cape = RecordingCape({"/apiv2/tasks/status/6/": captured_response("task_status_reported.json")})

    await cape_client(cape, TOKEN).task_status(6)

    assert cape.requests[0].headers["Authorization"] == f"Token {TOKEN}"


async def test_a_call_without_a_token_fails_before_any_request_is_sent(
    cape_client: ClientFactory,
) -> None:
    cape = RecordingCape({})

    with pytest.raises(CapeNotConfigured, match="CAPE_API_TOKEN"):
        await cape_client(cape, None).task_status(6)

    assert cape.requests == []


async def test_a_401_is_an_auth_error_naming_the_call_not_the_token(
    cape_client: ClientFactory,
) -> None:
    cape = RecordingCape({"/apiv2/cuckoo/status/": captured_response("unauthorized.json")})

    with pytest.raises(CapeAuthError) as error:
        await cape_client(cape, "wrong-token").cuckoo_status()

    assert "cuckoo/status" in str(error.value)
    assert "wrong-token" not in str(error.value)


@pytest.mark.parametrize(
    ("fixture", "call", "path"),
    [
        ("task_status_reported.json", "task_status", "/apiv2/tasks/status/6/"),
        ("cuckoo_status.json", "cuckoo_status", "/apiv2/cuckoo/status/"),
        ("machines_list.json", "list_machines", "/apiv2/machines/list/"),
    ],
    ids=["error-false", "error-empty-list-status", "error-empty-list-machines"],
)
async def test_both_spellings_of_a_successful_error_field_are_accepted(
    cape_client: ClientFactory, fixture: str, call: str, path: str
) -> None:
    cape = RecordingCape({path: captured_response(fixture)})
    client = cape_client(cape, TOKEN)

    result = await (client.task_status(6) if call == "task_status" else getattr(client, call)())

    assert result


async def test_error_true_on_http_200_is_rejected_with_capes_message(
    cape_client: ClientFactory,
) -> None:
    cape = RecordingCape(
        {"/apiv2/tasks/create/file/": captured_response("create_without_file.json")}
    )

    with pytest.raises(CapeRejected) as error:
        await cape_client(cape, TOKEN).create_file_task(
            io.BytesIO(b"x"), "a.exe", machine="win", route="none", timeout=60
        )

    assert error.value.message == "No file was submitted"
    assert "tasks/create/file" in str(error.value)
    assert "No file was submitted" in str(error.value)


async def test_a_missing_task_is_a_task_not_found_error(cape_client: ClientFactory) -> None:
    cape = RecordingCape({"/apiv2/tasks/status/99/": captured_response("task_status_missing.json")})

    with pytest.raises(CapeTaskNotFound) as error:
        await cape_client(cape, TOKEN).task_status(99)

    assert error.value.task_id == 99
    assert isinstance(error.value, CapeRejected)


async def test_a_task_view_of_a_missing_task_is_a_task_not_found_error(
    cape_client: ClientFactory,
) -> None:
    missing = json_response({"error": True, "error_value": "Task not found in database"})
    cape = RecordingCape({"/apiv2/tasks/view/99/": missing})

    with pytest.raises(CapeTaskNotFound):
        await cape_client(cape, TOKEN).task_view(99)


@pytest.mark.parametrize(
    "body",
    [b"<html>502 Bad Gateway</html>", b"", b'["not", "an", "object"]', b'{"error": false}'],
    ids=["html", "empty", "json-array", "no-data"],
)
async def test_an_unreadable_body_is_a_bad_response(
    cape_client: ClientFactory, body: bytes
) -> None:
    cape = RecordingCape({"/apiv2/tasks/status/6/": httpx.Response(200, content=body)})

    with pytest.raises(CapeBadResponse) as error:
        await cape_client(cape, TOKEN).task_status(6)

    assert "tasks/status" in str(error.value)


async def test_data_of_the_wrong_shape_is_a_bad_response(cape_client: ClientFactory) -> None:
    cape = RecordingCape({"/apiv2/cuckoo/status/": json_response({"error": [], "data": "oops"})})

    with pytest.raises(CapeBadResponse):
        await cape_client(cape, TOKEN).cuckoo_status()


@pytest.mark.parametrize("status_code", [500, 502, 503])
async def test_a_server_error_means_cape_is_unreachable(
    cape_client: ClientFactory, status_code: int
) -> None:
    cape = RecordingCape({"/apiv2/cuckoo/status/": httpx.Response(status_code, content="boom")})

    with pytest.raises(CapeUnreachable) as error:
        await cape_client(cape, TOKEN).cuckoo_status()

    assert str(status_code) in str(error.value)


@pytest.mark.parametrize(
    "failure",
    [httpx.ConnectError("refused"), httpx.ConnectTimeout("slow"), httpx.ReadTimeout("slow")],
    ids=["refused", "connect-timeout", "read-timeout"],
)
async def test_a_transport_failure_means_cape_is_unreachable(
    cape_client: ClientFactory, failure: httpx.HTTPError
) -> None:
    cape = RecordingCape({"/apiv2/cuckoo/status/": failure})

    with pytest.raises(CapeUnreachable) as error:
        await cape_client(cape, TOKEN).cuckoo_status()

    assert "cuckoo/status" in str(error.value)


async def test_unreachable_and_rejected_are_told_apart_by_type() -> None:
    assert not issubclass(CapeUnreachable, CapeRejected)
    assert not issubclass(CapeRejected, CapeUnreachable)
    assert all(
        issubclass(kind, CapeError)
        for kind in (
            CapeUnreachable,
            CapeRejected,
            CapeAuthError,
            CapeTaskNotFound,
            CapeBadResponse,
        )
    )


@pytest.mark.parametrize(
    "outcome",
    [
        httpx.ConnectError(f"cannot reach {BASE_URL} with Token {TOKEN}"),
        httpx.ReadTimeout(f"timed out for {BASE_URL} Authorization: Token {TOKEN}"),
        captured_response("unauthorized.json"),
        captured_response("task_status_missing.json"),
        httpx.Response(200, content=f"<html>{TOKEN}</html>"),
        httpx.Response(502, content=f"{TOKEN}"),
    ],
    ids=["refused", "timeout", "401", "missing", "garbage", "5xx"],
)
async def test_no_error_text_contains_the_token_or_the_url(
    cape_client: ClientFactory, outcome: httpx.Response | Exception
) -> None:
    cape = RecordingCape({"/apiv2/tasks/status/6/": outcome})

    with pytest.raises(CapeError) as error:
        await cape_client(cape, TOKEN).task_status(6)

    for text in (str(error.value), repr(error.value), repr(error.value.args)):
        assert TOKEN not in text
        assert BASE_URL not in text
        assert "cape-internal" not in text


async def test_task_status_returns_capes_status_string(cape_client: ClientFactory) -> None:
    cape = RecordingCape({"/apiv2/tasks/status/6/": captured_response("task_status_reported.json")})

    assert await cape_client(cape, TOKEN).task_status(6) == "reported"


async def test_task_view_exposes_the_options_string_cape_keeps(cape_client: ClientFactory) -> None:
    cape = RecordingCape({"/apiv2/tasks/view/6/": captured_response("task_view_reported.json")})

    view = await cape_client(cape, TOKEN).task_view(6)

    assert view.options == "vnc_port=5900"


async def test_task_view_exposes_the_timings_as_utc_datetimes(cape_client: ClientFactory) -> None:
    cape = RecordingCape({"/apiv2/tasks/view/6/": captured_response("task_view_reported.json")})

    view = await cape_client(cape, TOKEN).task_view(6)

    assert view.id == 6
    assert view.status == "reported"
    assert view.machine == "win"
    assert view.route == "inetsim"
    assert view.package == "exe"
    assert view.timedout is False
    assert view.added_on == datetime(2026, 10, 13, 12, 12, 18, tzinfo=UTC)
    assert view.started_on == datetime(2026, 10, 13, 12, 12, 18, tzinfo=UTC)
    assert view.completed_on == datetime(2026, 10, 13, 12, 13, 13, tzinfo=UTC)
    assert view.reporting_finished_on == datetime(2026, 10, 13, 12, 13, 21, tzinfo=UTC)


async def test_task_view_of_a_task_that_has_not_started_has_empty_timings(
    cape_client: ClientFactory,
) -> None:
    pending = {
        "error": False,
        "data": {
            "id": 8,
            "status": "pending",
            "machine": None,
            "route": None,
            "package": "",
            "timedout": False,
            "added_on": "2026-10-13 12:30:00",
            "started_on": None,
            "completed_on": None,
            "reporting_finished_on": None,
        },
    }
    cape = RecordingCape({"/apiv2/tasks/view/8/": json_response(pending)})

    view = await cape_client(cape, TOKEN).task_view(8)

    assert view.status == "pending"
    assert view.started_on is None
    assert view.completed_on is None
    assert view.reporting_finished_on is None


async def test_cuckoo_status_reads_version_and_task_counts(cape_client: ClientFactory) -> None:
    cape = RecordingCape({"/apiv2/cuckoo/status/": captured_response("cuckoo_status.json")})

    status = await cape_client(cape, TOKEN).cuckoo_status()

    assert status.version == "2.5"
    assert status.machines.total == 1
    assert status.machines.available == 1
    assert status.tasks.pending == 0
    assert status.tasks.reported == 6


async def test_list_machines_reads_the_guest(cape_client: ClientFactory) -> None:
    cape = RecordingCape({"/apiv2/machines/list/": captured_response("machines_list.json")})

    (machine,) = await cape_client(cape, TOKEN).list_machines()

    assert machine.label == "win"
    assert machine.status == "poweroff"
    assert machine.locked is False
    assert machine.reserved is False
    assert machine.ip == "192.168.150.10"


async def test_delete_task_succeeds_on_a_response_without_an_error_field(
    cape_client: ClientFactory,
) -> None:
    deleted = json_response({"data": "Task(s) ID(s) 6 has been deleted"})
    cape = RecordingCape({"/apiv2/tasks/delete/6/": deleted})

    await cape_client(cape, TOKEN).delete_task(6)

    assert cape.requests[0].method == "GET"


async def test_delete_task_can_name_the_status_so_cape_deletes_a_failed_task(
    cape_client: ClientFactory,
) -> None:
    deleted = json_response({"data": "Task(s) ID(s) 6 has been deleted"})
    cape = RecordingCape({"/apiv2/tasks/delete/6/failed_analysis/": deleted})

    await cape_client(cape, TOKEN).delete_task(6, task_status="failed_analysis")

    assert len(cape.requests) == 1


async def test_delete_task_surfaces_capes_disabled_message(cape_client: ClientFactory) -> None:
    cape = RecordingCape({"/apiv2/tasks/delete/6/": captured_response("delete_missing.json")})

    with pytest.raises(CapeRejected, match="Task Deletion API is Disabled"):
        await cape_client(cape, TOKEN).delete_task(6)


async def test_delete_task_surfaces_the_failed_list_when_cape_cannot_remove_it(
    cape_client: ClientFactory,
) -> None:
    failed = json_response({"error": True, "failed": "Task(s) ID(s) 6 failed to remove"})
    cape = RecordingCape({"/apiv2/tasks/delete/6/": failed})

    with pytest.raises(CapeRejected, match="failed to remove"):
        await cape_client(cape, TOKEN).delete_task(6)


async def test_create_file_task_posts_multipart_with_capes_field_names(
    cape_client: ClientFactory,
) -> None:
    cape = RecordingCape({"/apiv2/tasks/create/file/": json_response(SUBMITTED)})

    task_id = await cape_client(cape, TOKEN).create_file_task(
        io.BytesIO(b"MZ-sample"),
        "benign.exe",
        machine="win",
        route="inetsim",
        timeout=120,
        package="exe",
    )

    (request,) = cape.requests
    assert task_id == 7
    assert request.method == "POST"
    assert request.headers["content-type"].startswith("multipart/form-data")
    assert multipart_filename(request) == "benign.exe"
    assert parse_multipart(request) == {
        "file": b"MZ-sample",
        "machine": b"win",
        "route": b"inetsim",
        "timeout": b"120",
        "package": b"exe",
    }


async def test_create_file_task_omits_package_when_it_is_auto(cape_client: ClientFactory) -> None:
    cape = RecordingCape({"/apiv2/tasks/create/file/": json_response(SUBMITTED)})

    await cape_client(cape, TOKEN).create_file_task(
        io.BytesIO(b"x"), "a.bin", machine="win", route="none", timeout=60, package="auto"
    )

    assert "package" not in parse_multipart(cape.requests[0])


async def test_create_file_task_sends_the_task_options_it_is_given(
    cape_client: ClientFactory,
) -> None:
    cape = RecordingCape({"/apiv2/tasks/create/file/": json_response(SUBMITTED)})

    await cape_client(cape, TOKEN).create_file_task(
        io.BytesIO(b"x"),
        "a.bin",
        machine="win",
        route="none",
        timeout=60,
        options="interactive=1,nohuman=yes",
    )

    assert parse_multipart(cape.requests[0])["options"] == b"interactive=1,nohuman=yes"


async def test_create_file_task_sends_no_options_unless_given_some(
    cape_client: ClientFactory,
) -> None:
    cape = RecordingCape({"/apiv2/tasks/create/file/": json_response(SUBMITTED)})

    await cape_client(cape, TOKEN).create_file_task(
        io.BytesIO(b"x"), "a.bin", machine="win", route="none", timeout=60
    )

    assert "options" not in parse_multipart(cape.requests[0])


async def test_create_file_task_sends_the_extra_task_fields_as_capes_form_fields(
    cape_client: ClientFactory,
) -> None:
    cape = RecordingCape({"/apiv2/tasks/create/file/": json_response(SUBMITTED)})

    await cape_client(cape, TOKEN).create_file_task(
        io.BytesIO(b"x"),
        "a.bin",
        machine="lin1",
        route="none",
        timeout=60,
        task_fields={"enforce_timeout": True, "priority": 3, "free": False, "tlp": "red"},
    )

    fields = parse_multipart(cape.requests[0])
    assert fields["enforce_timeout"] == b"1"
    assert fields["priority"] == b"3"
    assert fields["tlp"] == b"red"
    assert "free" not in fields


async def test_a_task_field_cannot_replace_the_machine_the_backend_chose(
    cape_client: ClientFactory,
) -> None:
    cape = RecordingCape({"/apiv2/tasks/create/file/": json_response(SUBMITTED)})

    await cape_client(cape, TOKEN).create_file_task(
        io.BytesIO(b"x"),
        "a.bin",
        machine="lab1",
        route="none",
        timeout=60,
        task_fields={"machine": "win"},
    )

    assert parse_multipart(cape.requests[0])["machine"] == b"lab1"


async def test_an_unknown_machine_is_a_rejection_although_cape_answers_http_200(
    cape_client: ClientFactory,
) -> None:
    # Captured by S0b: no task is created and the status code gives nothing away.
    unknown = json_response(
        {"error": True, "error_value": "Machine 'nosuch' does not exist. Available: win, win2"}
    )
    cape = RecordingCape({"/apiv2/tasks/create/file/": unknown})

    with pytest.raises(CapeRejected, match="Machine 'nosuch' does not exist"):
        await cape_client(cape, TOKEN).create_file_task(
            io.BytesIO(b"x"), "a.bin", machine="nosuch", route="none", timeout=60
        )


async def test_create_file_task_reads_a_file_from_a_path(
    cape_client: ClientFactory, tmp_path: Path
) -> None:
    sample = tmp_path / "stored-name"
    sample.write_bytes(b"from-disk")
    cape = RecordingCape({"/apiv2/tasks/create/file/": json_response(SUBMITTED)})

    await cape_client(cape, TOKEN).create_file_task(
        sample, "original.dll", machine="win", route="none", timeout=60
    )

    assert parse_multipart(cape.requests[0])["file"] == b"from-disk"
    assert multipart_filename(cape.requests[0]) == "original.dll"


@pytest.mark.parametrize(
    "payload",
    [
        {"error": [], "data": {"task_ids": [], "message": ""}},
        {"error": [], "data": {"message": "no ids"}},
    ],
    ids=["empty-ids", "no-ids"],
)
async def test_a_submission_answer_without_a_task_id_is_a_bad_response(
    cape_client: ClientFactory, payload: dict[str, object]
) -> None:
    cape = RecordingCape({"/apiv2/tasks/create/file/": json_response(payload)})

    with pytest.raises(CapeBadResponse):
        await cape_client(cape, TOKEN).create_file_task(
            io.BytesIO(b"x"), "a.exe", machine="win", route="none", timeout=60
        )


async def test_create_file_task_rejected_when_cape_could_not_add_the_task(
    cape_client: ClientFactory,
) -> None:
    refused = json_response(
        {"error": True, "error_value": "Error adding task to database", "errors": []}
    )
    cape = RecordingCape({"/apiv2/tasks/create/file/": refused})

    with pytest.raises(CapeRejected, match="Error adding task to database"):
        await cape_client(cape, TOKEN).create_file_task(
            io.BytesIO(b"x"), "a.exe", machine="win", route="none", timeout=60
        )


async def test_the_client_does_not_retry_a_failed_call(cape_client: ClientFactory) -> None:
    cape = RecordingCape({"/apiv2/cuckoo/status/": httpx.ConnectError("refused")})

    with pytest.raises(CapeUnreachable):
        await cape_client(cape, TOKEN).cuckoo_status()

    assert len(cape.requests) == 1


async def test_from_settings_uses_the_configured_url_and_token(settings: Settings) -> None:
    configured = settings.model_copy(
        update={"cape_api_url": BASE_URL, "cape_api_token": SecretStr(TOKEN)}
    )
    cape = RecordingCape({"/apiv2/tasks/status/6/": captured_response("task_status_reported.json")})

    async with CapeClient.from_settings(configured, transport=httpx.MockTransport(cape)) as client:
        await client.task_status(6)

    assert str(cape.requests[0].url).startswith(BASE_URL)
    assert cape.requests[0].headers["Authorization"] == f"Token {TOKEN}"
