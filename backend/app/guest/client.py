from collections.abc import Mapping
from types import TracebackType
from typing import Any, Protocol, Self

import httpx
from pydantic import TypeAdapter, ValidationError

from app.config import Settings
from app.guest.errors import (
    GuestControlBadResponse,
    GuestControlNotConfigured,
    GuestControlRejected,
    GuestControlUnreachable,
)
from app.guest.schemas import (
    BuildStatus,
    Guest,
    GuestDisplay,
    GuestProfile,
    HealthCheckResult,
    MediaEntry,
)

# A check restores the guest's snapshot and waits for its agent (up to two minutes).
DEFAULT_TIMEOUT = httpx.Timeout(150.0, connect=5.0)
NO_MESSAGE = "the guest control service refused the request without saying why"
AUTH_REFUSED_STATUSES = frozenset({httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN})

_PROFILES = TypeAdapter(list[GuestProfile])
_MEDIA = TypeAdapter(list[MediaEntry])
_GUESTS = TypeAdapter(list[Guest])
_GUEST = TypeAdapter(Guest)
_CHECK = TypeAdapter(HealthCheckResult)
_BUILD = TypeAdapter(BuildStatus)
_LOG_LINES = TypeAdapter(list[str])
_DISPLAY = TypeAdapter(GuestDisplay)


class GuestControl(Protocol):
    """What the backend asks of the guest control service in the cape container.

    Every method raises a `GuestControlError`. `start_build` and `start_clone` return the id of
    the build they started.
    """

    async def profiles(self) -> list[GuestProfile]: ...

    async def media(self) -> list[MediaEntry]: ...

    async def guests(self) -> list[Guest]: ...

    async def guest(self, name: str) -> Guest: ...

    async def delete_guest(self, name: str) -> None: ...

    async def check(self, name: str) -> HealthCheckResult: ...

    async def start_build(self, params: Mapping[str, Any]) -> str: ...

    async def start_clone(self, source: str, params: Mapping[str, Any]) -> str: ...

    async def build(self, build_id: str) -> BuildStatus: ...

    async def build_log(self, build_id: str, tail: int) -> list[str]: ...

    async def resume(self, build_id: str) -> None: ...

    async def restart(self, build_id: str) -> None: ...

    async def continue_(self, build_id: str) -> None: ...

    async def complete(
        self, build_id: str, *, passed: bool, selftest: Mapping[str, Any]
    ) -> None: ...

    async def display(self, name: str) -> GuestDisplay: ...

    async def finish_task(self, task_id: int, guest: str) -> None: ...


class HttpGuestControl:
    """Async client of the guest control service. It never retries: the callers decide."""

    def __init__(
        self,
        base_url: str,
        token: str | None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    ) -> None:
        self._token = token
        self._http = httpx.AsyncClient(base_url=base_url, transport=transport, timeout=timeout)

    @classmethod
    def from_settings(
        cls, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> Self:
        token = settings.guest_control_token
        return cls(
            settings.guest_control_url,
            token.get_secret_value() if token else None,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def profiles(self) -> list[GuestProfile]:
        return _parsed("profiles", _PROFILES, await self._send("profiles", "GET", "/profiles"))

    async def media(self) -> list[MediaEntry]:
        return _parsed("media", _MEDIA, await self._send("media", "GET", "/media"))

    async def guests(self) -> list[Guest]:
        return _parsed("guests", _GUESTS, await self._send("guests", "GET", "/guests"))

    async def guest(self, name: str) -> Guest:
        body = await self._send("guest", "GET", f"/guests/{name}")
        return _parsed("guest", _GUEST, body)

    async def delete_guest(self, name: str) -> None:
        await self._send("delete_guest", "DELETE", f"/guests/{name}")

    async def check(self, name: str) -> HealthCheckResult:
        body = await self._send("check", "POST", f"/guests/{name}/check")
        return _parsed("check", _CHECK, body)

    async def start_build(self, params: Mapping[str, Any]) -> str:
        return _started_id(
            "start_build", await self._send("start_build", "POST", "/builds", params)
        )

    async def start_clone(self, source: str, params: Mapping[str, Any]) -> str:
        body = await self._send("start_clone", "POST", f"/guests/{source}/clone", params)
        return _started_id("start_clone", body)

    async def build(self, build_id: str) -> BuildStatus:
        body = await self._send("build", "GET", f"/builds/{build_id}")
        return _parsed("build", _BUILD, body)

    async def build_log(self, build_id: str, tail: int) -> list[str]:
        body = await self._send("build_log", "GET", f"/builds/{build_id}/log", query={"tail": tail})
        return _parsed("build_log", _LOG_LINES, body)

    async def resume(self, build_id: str) -> None:
        await self._send("resume", "POST", f"/builds/{build_id}/resume")

    async def restart(self, build_id: str) -> None:
        await self._send("restart", "POST", f"/builds/{build_id}/restart")

    async def continue_(self, build_id: str) -> None:
        await self._send("continue", "POST", f"/builds/{build_id}/continue")

    async def complete(self, build_id: str, *, passed: bool, selftest: Mapping[str, Any]) -> None:
        verdict = {"passed": passed, "selftest": selftest}
        await self._send("complete", "POST", f"/builds/{build_id}/complete", verdict)

    async def display(self, name: str) -> GuestDisplay:
        body = await self._send("display", "GET", f"/guests/{name}/display")
        return _parsed("display", _DISPLAY, body)

    async def finish_task(self, task_id: int, guest: str) -> None:
        body = await self._send("finish_task", "POST", f"/tasks/{task_id}/finish", {"guest": guest})
        if not (isinstance(body, dict) and body.get("finished") is True):
            raise GuestControlBadResponse("finish_task", "not a finish")

    async def _send(
        self,
        call: str,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
        *,
        query: Mapping[str, Any] | None = None,
    ) -> Any:
        if self._token is None:
            raise GuestControlNotConfigured(call)
        try:
            response = await self._http.request(
                method,
                path,
                json=body,
                params=query,
                headers={"Authorization": f"Bearer {self._token}"},
            )
        except httpx.TransportError as error:
            # Only the type: httpx messages can carry the URL.
            raise GuestControlUnreachable(call, type(error).__name__) from None
        return _answer(call, response)


def _answer(call: str, response: httpx.Response) -> Any:
    status = response.status_code
    parsed = _json_or_none(response)
    if status in AUTH_REFUSED_STATUSES:
        raise GuestControlUnreachable(call, "the token was refused")
    # The finish route answers 502 with the reason the guest agent could not be asked.
    if status == httpx.codes.BAD_GATEWAY and _message_of(parsed):
        raise _rejection(call, status, parsed)
    if status >= httpx.codes.INTERNAL_SERVER_ERROR:
        raise GuestControlUnreachable(call, f"HTTP {status}")
    if status >= httpx.codes.BAD_REQUEST:
        raise _rejection(call, status, parsed)
    if status == httpx.codes.NO_CONTENT:
        return None
    if parsed is None:
        raise GuestControlBadResponse(call, "not JSON")
    return parsed


def _rejection(call: str, status: int, parsed: Any) -> GuestControlRejected:
    fields = parsed.get("fields") if isinstance(parsed, dict) else None
    clean_fields = (
        {str(field): str(problem) for field, problem in fields.items()}
        if isinstance(fields, dict)
        else {}
    )
    return GuestControlRejected(call, status, _message_of(parsed) or NO_MESSAGE, clean_fields)


def _message_of(parsed: Any) -> str:
    message = parsed.get("error") if isinstance(parsed, dict) else None
    return message if isinstance(message, str) else ""


def _json_or_none(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _parsed[T](call: str, adapter: TypeAdapter[T], body: Any) -> T:
    try:
        return adapter.validate_python(body)
    except ValidationError:
        # Not the error text: it quotes the offending values, and a guest record holds a password.
        raise GuestControlBadResponse(call, "wrong shape") from None


def _started_id(call: str, body: Any) -> str:
    identifier = body.get("id") if isinstance(body, dict) else None
    if not isinstance(identifier, str) or not identifier:
        raise GuestControlBadResponse(call, "no build id")
    return identifier
