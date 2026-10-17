import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.guest.client import (
    DEFAULT_TIMEOUT,
    SAMPLE_CAP,
    SELFTEST_CHECKS_TIMEOUT_S,
    HttpGuestControl,
)
from app.guest.errors import (
    GuestControlBadResponse,
    GuestControlError,
    GuestControlNotConfigured,
    GuestControlRejected,
    GuestControlUnreachable,
)
from tests.guest.conftest import captured

CONTROL_URL = "http://control-internal.example:8002"
TOKEN = "tok-control-0123456789abcdef"  # noqa: S105

type Handler = Callable[[httpx.Request], httpx.Response]


def json_response(payload: Any, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, content=json.dumps(payload))


class RecordingControl:
    """Serves each (method, path) from `routes` and remembers what it was asked."""

    def __init__(self, routes: dict[tuple[str, str], httpx.Response | Exception]) -> None:
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        outcome = self.routes[(request.method, request.url.path)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    @property
    def only_request(self) -> httpx.Request:
        (request,) = self.requests
        return request


def control_with(handler: Handler, token: str | None = TOKEN) -> HttpGuestControl:
    return HttpGuestControl(CONTROL_URL, token, transport=httpx.MockTransport(handler))


def serving(method: str, path: str, response: httpx.Response | Exception) -> RecordingControl:
    return RecordingControl({(method, path): response})


# --- reading -----------------------------------------------------------------------------------


async def test_guests_gets_the_list_and_parses_every_record() -> None:
    control = serving("GET", "/guests", json_response(captured("guests.json")))

    guests = await control_with(control).guests()

    assert [guest.name for guest in guests] == ["win", "lab1", "lab2"]
    assert str(control.only_request.url) == f"{CONTROL_URL}/guests"


async def test_guest_gets_one_record_by_name() -> None:
    control = serving("GET", "/guests/lab2", json_response(captured("guest_lab2.json")))

    guest = await control_with(control).guest("lab2")

    assert (guest.name, guest.cloned_from) == ("lab2", "lab1")


async def test_profiles_and_media_get_their_lists() -> None:
    control = RecordingControl(
        {
            ("GET", "/profiles"): json_response(captured("profiles.json")),
            ("GET", "/media"): json_response(captured("media.json")),
        }
    )
    client = control_with(control)

    profiles = await client.profiles()
    media = await client.media()

    assert [profile.id for profile in profiles] == ["windows"]
    assert [entry.file for entry in media] == ["Win11_25H2_Polish_x64_v2.iso"]


async def test_check_posts_to_the_guests_check_route() -> None:
    control = serving("POST", "/guests/lab1/check", json_response(captured("check_result.json")))

    result = await control_with(control).check("lab1")

    assert result.name == "lab1"
    assert [check.id for check in result.checks] == ["domain", "snapshot", "registration", "agent"]


async def test_build_gets_its_status() -> None:
    control = serving("GET", "/builds/b2f48f9dcd08a", json_response(captured("build_status.json")))

    build = await control_with(control).build("b2f48f9dcd08a")

    assert (build.guest, build.status, build.percent) == ("lab1", "succeeded", 100)


async def test_build_log_asks_for_the_tail_and_returns_the_lines() -> None:
    control = serving("GET", "/builds/b1/log", json_response(captured("build_log.json")))

    lines = await control_with(control).build_log("b1", tail=3)

    assert lines[-1] == "PROGRESS 100"
    assert control.only_request.url.params["tail"] == "3"


async def test_display_gets_the_host_and_port_of_the_screen() -> None:
    control = serving(
        "GET", "/guests/lab1/display", json_response({"host": "127.0.0.1", "port": 5901})
    )

    display = await control_with(control).display("lab1")

    assert (display.host, display.port) == ("127.0.0.1", 5901)


# --- changing ----------------------------------------------------------------------------------


async def test_delete_guest_sends_delete_and_accepts_no_content() -> None:
    control = serving("DELETE", "/guests/lab2", httpx.Response(204))

    assert await control_with(control).delete_guest("lab2") is None

    assert control.only_request.method == "DELETE"


async def test_start_build_posts_the_parameters_and_returns_the_build_id() -> None:
    control = serving("POST", "/builds", json_response({"id": "b77"}, status_code=202))

    build_id = await control_with(control).start_build({"name": "lab3", "iso": "x.iso"})

    assert build_id == "b77"
    assert json.loads(control.only_request.content) == {"name": "lab3", "iso": "x.iso"}


async def test_start_clone_posts_the_parameters_to_the_sources_clone_route() -> None:
    control = serving("POST", "/guests/lab1/clone", json_response({"id": "c5"}, status_code=202))

    build_id = await control_with(control).start_clone("lab1", {"name": "lab4"})

    assert build_id == "c5"
    assert json.loads(control.only_request.content) == {"name": "lab4"}


@pytest.mark.parametrize("action", ["resume", "restart", "continue_"])
async def test_resume_restart_and_continue_post_to_the_builds_routes(action: str) -> None:
    route = "continue" if action == "continue_" else action
    control = serving("POST", f"/builds/b1/{route}", json_response({"id": "b1"}, status_code=202))

    assert await getattr(control_with(control), action)("b1") is None

    assert control.only_request.method == "POST"


async def test_cancel_build_posts_to_the_builds_cancel_route() -> None:
    control = serving("POST", "/builds/b1/cancel", json_response({"id": "b1"}, status_code=202))

    assert await control_with(control).cancel_build("b1") is None

    assert control.only_request.method == "POST"


async def test_complete_posts_the_verdict_and_the_selftest_record() -> None:
    control = serving("POST", "/builds/b1/complete", httpx.Response(204))

    await control_with(control).complete("b1", passed=True, selftest={"analysis_id": 9})

    assert json.loads(control.only_request.content) == {
        "passed": True,
        "selftest": {"analysis_id": 9},
    }


async def test_finish_task_posts_the_guest_name_to_the_tasks_finish_route() -> None:
    control = serving("POST", "/tasks/7/finish", json_response({"finished": True}))

    await control_with(control).finish_task(7, "lab1")

    assert json.loads(control.only_request.content) == {"guest": "lab1"}


async def test_finish_task_that_is_not_confirmed_is_a_bad_response() -> None:
    control = serving("POST", "/tasks/7/finish", json_response({"finished": False}))

    with pytest.raises(GuestControlBadResponse):
        await control_with(control).finish_task(7, "lab1")


async def test_finish_task_reports_the_reason_when_the_guest_agent_cannot_be_asked() -> None:
    reason = "the guest agent is unreachable (URLError)"
    control = serving("POST", "/tasks/7/finish", json_response({"error": reason}, status_code=502))

    with pytest.raises(GuestControlRejected) as error:
        await control_with(control).finish_task(7, "lab1")

    assert (error.value.status, error.value.message) == (502, reason)


# --- authentication ----------------------------------------------------------------------------


async def test_every_request_carries_the_bearer_token() -> None:
    control = serving("GET", "/guests", json_response([]))

    await control_with(control).guests()

    assert control.only_request.headers["Authorization"] == f"Bearer {TOKEN}"


async def test_without_a_token_nothing_is_sent() -> None:
    control = serving("GET", "/guests", json_response([]))

    with pytest.raises(GuestControlNotConfigured) as error:
        await control_with(control, token=None).guests()

    assert control.requests == []
    assert "GUEST_CONTROL_TOKEN" in str(error.value)


@pytest.mark.parametrize("status", [401, 403])
async def test_a_refused_token_is_reported_as_unreachable_without_the_token(status: int) -> None:
    control = serving("GET", "/guests", json_response({"error": "unauthorized"}, status))

    with pytest.raises(GuestControlUnreachable) as error:
        await control_with(control).guests()

    assert TOKEN not in str(error.value)
    assert "token was refused" in str(error.value)


# --- errors ------------------------------------------------------------------------------------


async def test_a_transport_failure_is_unreachable_with_only_the_exception_type() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to control-internal.example", request=request)

    with pytest.raises(GuestControlUnreachable) as error:
        await control_with(refuse).guests()

    assert "ConnectError" in str(error.value)
    assert "control-internal.example" not in str(error.value)


async def test_a_timeout_is_unreachable() -> None:
    def hang(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(GuestControlUnreachable) as error:
        await control_with(hang).guests()

    assert "ReadTimeout" in str(error.value)


@pytest.mark.parametrize("status", [500, 502, 503])
async def test_a_server_error_is_unreachable(status: int) -> None:
    control = serving("GET", "/guests", httpx.Response(status, content="boom"))

    with pytest.raises(GuestControlUnreachable) as error:
        await control_with(control).guests()

    assert f"HTTP {status}" in str(error.value)


async def test_a_conflict_is_a_rejection_with_the_services_message() -> None:
    message = "the build of lab3 is running; wait for it to finish"
    control = serving("DELETE", "/guests/lab3", json_response({"error": message}, status_code=409))

    with pytest.raises(GuestControlRejected) as error:
        await control_with(control).delete_guest("lab3")

    assert (error.value.status, error.value.message, error.value.fields) == (409, message, {})


async def test_a_missing_guest_is_a_rejection_with_status_404() -> None:
    control = serving("GET", "/guests/nope", json_response({"error": "no guest nope"}, 404))

    with pytest.raises(GuestControlRejected) as error:
        await control_with(control).guest("nope")

    assert (error.value.status, error.value.message) == (404, "no guest nope")


async def test_validation_problems_keep_the_fields_of_the_services_422() -> None:
    body = {"error": "the build parameters are not valid", "fields": {"name": "already taken"}}
    control = serving("POST", "/builds", json_response(body, status_code=422))

    with pytest.raises(GuestControlRejected) as error:
        await control_with(control).start_build({"name": "lab1"})

    assert error.value.status == 422
    assert error.value.fields == {"name": "already taken"}


async def test_a_rejection_without_a_readable_message_still_has_one() -> None:
    control = serving("POST", "/builds", httpx.Response(409, content="<html>conflict</html>"))

    with pytest.raises(GuestControlRejected) as error:
        await control_with(control).start_build({})

    assert error.value.status == 409
    assert error.value.message


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(200, content="<html>not json</html>"),
        httpx.Response(200, content='{"name": "lab1"}'),
        json_response([{"name": "lab1", "state": "sleeping"}]),
        json_response([{"state": "ready"}]),
    ],
    ids=["not-json", "not-a-list", "unknown-state", "missing-name"],
)
async def test_an_answer_of_the_wrong_shape_is_a_bad_response(answer: httpx.Response) -> None:
    control = serving("GET", "/guests", answer)

    with pytest.raises(GuestControlBadResponse):
        await control_with(control).guests()


async def test_a_bad_response_does_not_repeat_the_data_it_could_not_read() -> None:
    secret_record = [{"name": "lab1", "state": "sleeping", "identity": {"password": "hunter2"}}]
    control = serving("GET", "/guests", json_response(secret_record))

    with pytest.raises(GuestControlBadResponse) as error:
        await control_with(control).guests()

    assert "hunter2" not in str(error.value)


async def test_a_start_that_answers_without_an_id_is_a_bad_response() -> None:
    control = serving("POST", "/builds", json_response({"started": True}, status_code=202))

    with pytest.raises(GuestControlBadResponse):
        await control_with(control).start_build({})


async def test_all_failures_share_one_base_class() -> None:
    for error in (
        GuestControlUnreachable("guests", "ConnectError"),
        GuestControlRejected("guests", 409, "no"),
        GuestControlBadResponse("guests", "not JSON"),
    ):
        assert isinstance(error, GuestControlError)


# --- construction ------------------------------------------------------------------------------


async def test_the_client_is_built_from_the_settings() -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://u:p@db/t",
        opensearch_url="http://opensearch:9200",
        guest_control_url=CONTROL_URL,
        guest_control_token=TOKEN,  # type: ignore[arg-type]  # pydantic coerces str to SecretStr
    )
    control = serving("GET", "/guests", json_response([]))

    client = HttpGuestControl.from_settings(settings, transport=httpx.MockTransport(control))
    await client.guests()

    assert str(control.only_request.url) == f"{CONTROL_URL}/guests"
    assert control.only_request.headers["Authorization"] == f"Bearer {TOKEN}"


async def test_the_client_built_from_settings_without_a_token_refuses_to_send() -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://u:p@db/t", opensearch_url="http://opensearch:9200"
    )

    async with HttpGuestControl.from_settings(settings) as client:
        with pytest.raises(GuestControlNotConfigured):
            await client.guests()


async def test_the_token_is_in_no_log_line_and_no_exception_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("DEBUG")
    failures = [
        httpx.Response(401, content='{"error": "unauthorized"}'),
        httpx.Response(500, content="boom"),
        httpx.Response(409, content='{"error": "busy"}'),
        httpx.Response(200, content="not json"),
    ]
    texts: list[str] = []

    for failure in failures:
        with pytest.raises(GuestControlError) as error:
            await control_with(serving("GET", "/guests", failure)).guests()
        texts.append(str(error.value))

    assert TOKEN not in caplog.text
    assert all(TOKEN not in text for text in texts)


# --- the self-test -----------------------------------------------------------------------------

CHECKS_ANSWER = {
    "facts": {"os.hostname": "DESKTOP-4F7Q", "os.user": "jan"},
    "giveaways": ["scheduled task: SandboxAgent"],
    "proofs": {"eicar": {"ok": False, "message": "the file is still there"}},
    "log": ["restored the snapshot", "ran guest-facts"],
}


def sample_response(content: bytes = b"MZ pretend", filename: str = "benign.exe") -> httpx.Response:
    return httpx.Response(200, content=content, headers={"X-Filename": filename})


async def test_selftest_sample_gets_the_bytes_and_the_file_name_from_the_header() -> None:
    control = serving("GET", "/guests/lab1/selftest/sample", sample_response())

    sample = await control_with(control).selftest_sample("lab1")

    assert (sample.filename, sample.content) == ("benign.exe", b"MZ pretend")


async def test_selftest_sample_without_a_file_name_header_is_a_bad_response() -> None:
    control = serving("GET", "/guests/lab1/selftest/sample", httpx.Response(200, content=b"MZ"))

    with pytest.raises(GuestControlBadResponse):
        await control_with(control).selftest_sample("lab1")


async def test_selftest_sample_of_exactly_the_cap_is_accepted() -> None:
    control = serving("GET", "/guests/lab1/selftest/sample", sample_response(b"x" * SAMPLE_CAP))

    sample = await control_with(control).selftest_sample("lab1")

    assert len(sample.content) == SAMPLE_CAP


async def test_selftest_sample_over_the_cap_is_refused_whatever_the_headers_say() -> None:
    chunk = b"x" * 1024 * 1024

    async def endless() -> AsyncIterator[bytes]:
        for _ in range(SAMPLE_CAP // len(chunk) + 1):
            yield chunk

    response = httpx.Response(200, content=endless(), headers={"X-Filename": "big.exe"})
    control = serving("GET", "/guests/lab1/selftest/sample", response)

    with pytest.raises(GuestControlBadResponse) as error:
        await control_with(control).selftest_sample("lab1")

    assert "too large" in str(error.value)


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (404, "no guest named lab1"),
        (409, "the profile defines no sample"),
        (500, "building the sample failed: gcc exited 1"),
    ],
)
async def test_selftest_sample_refusals_are_rejections_with_the_services_message(
    status: int, message: str
) -> None:
    control = serving(
        "GET", "/guests/lab1/selftest/sample", json_response({"error": message}, status)
    )

    with pytest.raises(GuestControlRejected) as error:
        await control_with(control).selftest_sample("lab1")

    assert (error.value.status, error.value.message) == (status, message)


async def test_selftest_checks_posts_and_parses_the_facts_giveaways_proofs_and_log() -> None:
    control = serving("POST", "/guests/lab1/selftest/checks", json_response(CHECKS_ANSWER))

    checks = await control_with(control).selftest_checks("lab1")

    assert checks.facts["os.hostname"] == "DESKTOP-4F7Q"
    assert checks.giveaways == ["scheduled task: SandboxAgent"]
    assert checks.proofs["eicar"].ok is False
    assert checks.proofs["eicar"].message == "the file is still there"
    assert checks.log == ["restored the snapshot", "ran guest-facts"]


async def test_selftest_checks_waits_longer_than_the_other_calls() -> None:
    control = RecordingControl(
        {
            ("POST", "/guests/lab1/selftest/checks"): json_response(CHECKS_ANSWER),
            ("GET", "/guests"): json_response([]),
        }
    )
    client = control_with(control)

    await client.selftest_checks("lab1")
    await client.guests()

    checks_request, guests_request = control.requests
    assert checks_request.extensions["timeout"]["read"] == SELFTEST_CHECKS_TIMEOUT_S
    assert guests_request.extensions["timeout"]["read"] == DEFAULT_TIMEOUT.read


@pytest.mark.parametrize("status", [404, 409, 502])
async def test_selftest_checks_refusals_are_rejections_with_the_services_message(
    status: int,
) -> None:
    control = serving(
        "POST",
        "/guests/lab1/selftest/checks",
        json_response({"error": "a build is running"}, status),
    )

    with pytest.raises(GuestControlRejected) as error:
        await control_with(control).selftest_checks("lab1")

    assert (error.value.status, error.value.message) == (status, "a build is running")


async def test_selftest_checks_of_the_wrong_shape_is_a_bad_response() -> None:
    control = serving("POST", "/guests/lab1/selftest/checks", json_response({"facts": 3}))

    with pytest.raises(GuestControlBadResponse):
        await control_with(control).selftest_checks("lab1")
