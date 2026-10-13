import httpx
import pytest

from app.cape.control import CapeControl
from app.cape.errors import CapeBadResponse, CapeRejected, CapeUnreachable
from app.config import Settings
from tests.cape.conftest import Handler, RecordingCape, json_response

CONTROL_URL = "http://cape-internal.example:8001"
FINISH_PATH = "/tasks/7/finish"


def control_with(handler: Handler) -> CapeControl:
    return CapeControl(CONTROL_URL, transport=httpx.MockTransport(handler))


async def test_finishing_a_task_posts_to_its_finish_route() -> None:
    cape = RecordingCape({FINISH_PATH: json_response({"finished": True})})

    await control_with(cape).finish_task(7)

    (request,) = cape.requests
    assert (request.method, str(request.url)) == ("POST", f"{CONTROL_URL}{FINISH_PATH}")


async def test_the_helpers_reason_for_refusing_is_a_rejection_naming_the_call() -> None:
    reason = "the guest agent refused (HTTP 500): Error creating directory"
    cape = RecordingCape({FINISH_PATH: json_response({"error": reason}, status_code=502)})

    with pytest.raises(CapeRejected) as error:
        await control_with(cape).finish_task(7)

    assert error.value.message == reason
    assert "finish" in str(error.value)


async def test_a_helper_that_cannot_be_reached_is_unreachable_without_its_address() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to cape-internal.example", request=request)

    with pytest.raises(CapeUnreachable) as error:
        await control_with(refuse).finish_task(7)

    assert "ConnectError" in str(error.value)
    assert "cape-internal.example" not in str(error.value)


async def test_a_helper_server_error_is_unreachable() -> None:
    cape = RecordingCape({FINISH_PATH: httpx.Response(500, content="boom")})

    with pytest.raises(CapeUnreachable):
        await control_with(cape).finish_task(7)


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(404, content='{"error": "not found"}'),
        httpx.Response(200, content="<html>not json</html>"),
        httpx.Response(200, content='{"finished": false}'),
        httpx.Response(200, content='["finished"]'),
        httpx.Response(400, content='{"error": "the task id must be digits only"}'),
    ],
    ids=["unknown-route", "not-json", "not-finished", "not-an-object", "bad-id"],
)
async def test_an_answer_that_is_not_a_finish_is_a_bad_response(answer: httpx.Response) -> None:
    cape = RecordingCape({FINISH_PATH: answer})

    with pytest.raises(CapeBadResponse):
        await control_with(cape).finish_task(7)


async def test_the_client_is_built_from_the_control_url_setting() -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://u:p@db/t",
        opensearch_url="http://opensearch:9200",
        cape_control_url=CONTROL_URL,
    )
    cape = RecordingCape({FINISH_PATH: json_response({"finished": True})})

    await CapeControl.from_settings(settings, transport=httpx.MockTransport(cape)).finish_task(7)

    assert str(cape.requests[0].url) == f"{CONTROL_URL}{FINISH_PATH}"
