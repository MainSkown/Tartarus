from collections.abc import Mapping
from pathlib import Path
from types import TracebackType
from typing import Any, BinaryIO, Self

import httpx
from pydantic import BaseModel, TypeAdapter, ValidationError

from app.cape.errors import (
    CapeAuthError,
    CapeBadResponse,
    CapeNotConfigured,
    CapeRejected,
    CapeTaskNotFound,
    CapeUnreachable,
)
from app.cape.models import CuckooStatus, Machine, TaskView
from app.config import Settings

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=5.0)
API_PREFIX = "/apiv2"
AUTO_PACKAGE = "auto"
# CAPE answers a missing task differently on `tasks/status` and on `tasks/view`.
MISSING_TASK_MESSAGES = frozenset({"Task does not exist", "Task not found in database"})
# `tasks/delete` reports its failures under these keys instead of `error_value`.
DELETE_FAILURE_KEYS = ("failed", "orphaned")
NO_MESSAGE = "CAPE reported an error without a message"

_MACHINES = TypeAdapter(list[Machine])


class CapeClient:
    """Async client for CAPE's `apiv2`. It never retries: the tracker decides about failures."""

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
        token = settings.cape_api_token
        return cls(
            settings.cape_api_url,
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

    async def create_file_task(  # noqa: PLR0913 - one argument per CAPE form field
        self,
        source: Path | BinaryIO,
        filename: str,
        *,
        machine: str,
        route: str,
        timeout: int,  # noqa: ASYNC109 - CAPE's analysis timeout, not an asyncio one
        package: str = AUTO_PACKAGE,
        options: str = "",
        task_fields: Mapping[str, bool | int | str] | None = None,
    ) -> int:
        """Submit a file to CAPE and return the id of the task it created.

        `options` is CAPE's task options string and `task_fields` its further form fields (a
        guest profile supplies both for an interactive run). Raises `CapeRejected` when CAPE
        answers `error: true`, which it does with HTTP 200 for a machine it does not know.
        """
        fields = {
            **_form_fields(task_fields or {}),
            "machine": machine,
            "route": route,
            "timeout": str(timeout),
        }
        if package != AUTO_PACKAGE:
            fields["package"] = package
        if options:
            fields["options"] = options
        return await self._submit_file(source, filename, fields)

    async def create_pcap_task(self, source: Path | BinaryIO, filename: str) -> int:
        """Submit a packet capture for CAPE's network processing alone and return the task id.

        CAPE's `pcap` category runs no guest and takes no machine, route or timeout.
        Raises `CapeRejected` when CAPE refuses the upload, for one over its size limit.
        """
        return await self._submit_file(source, filename, {"pcap": "1"})

    async def _submit_file(
        self, source: Path | BinaryIO, filename: str, fields: Mapping[str, str]
    ) -> int:
        call = "tasks/create/file"
        if isinstance(source, Path):
            with source.open("rb") as stream:
                body = await self._send(call, "POST", f"{call}/", fields, (filename, stream))
        else:
            body = await self._send(call, "POST", f"{call}/", fields, (filename, source))
        return _first_task_id(call, _data(call, body))

    async def task_status(self, task_id: int) -> str:
        call = "tasks/status"
        status = _data(call, await self._send_for_task(call, task_id))
        if not isinstance(status, str):
            raise CapeBadResponse(call, "status is not text")
        return status

    async def task_view(self, task_id: int) -> TaskView:
        call = "tasks/view"
        return _parse(call, TaskView, _data(call, await self._send_for_task(call, task_id)))

    async def delete_task(self, task_id: int, task_status: str | None = None) -> None:
        """Delete a task. CAPE only deletes `reported` tasks unless told the task's own status."""
        suffix = f"{task_status}/" if task_status else ""
        await self._send("tasks/delete", "GET", f"tasks/delete/{task_id}/{suffix}")

    async def cuckoo_status(self) -> CuckooStatus:
        call = "cuckoo/status"
        return _parse(call, CuckooStatus, _data(call, await self._send(call, "GET", f"{call}/")))

    async def list_machines(self) -> list[Machine]:
        call = "machines/list"
        data = _data(call, await self._send(call, "GET", f"{call}/"))
        try:
            return _MACHINES.validate_python(data)
        except ValidationError:
            raise CapeBadResponse(call, "machines are not in the expected shape") from None

    async def _send_for_task(self, call: str, task_id: int) -> dict[str, Any]:
        try:
            return await self._send(call, "GET", f"{call}/{task_id}/")
        except CapeRejected as rejected:
            if rejected.message in MISSING_TASK_MESSAGES:
                raise CapeTaskNotFound(call, task_id, rejected.message) from None
            raise

    async def _send(
        self,
        call: str,
        method: str,
        path: str,
        fields: Mapping[str, str] | None = None,
        upload: tuple[str, BinaryIO] | None = None,
    ) -> dict[str, Any]:
        if not self._token:
            raise CapeNotConfigured
        try:
            response = await self._http.request(
                method,
                f"{API_PREFIX}/{path}",
                headers={"Authorization": f"Token {self._token}"},
                data=fields,
                files={"file": upload} if upload else None,
            )
        except httpx.TransportError as error:
            # Only the type: httpx messages can carry the URL.
            raise CapeUnreachable(call, type(error).__name__) from None
        return _read(call, response)


def _read(call: str, response: httpx.Response) -> dict[str, Any]:
    if response.status_code in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
        raise CapeAuthError(call)
    if response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
        raise CapeUnreachable(call, f"HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError:
        raise CapeBadResponse(call, f"HTTP {response.status_code}, body is not JSON") from None
    if not isinstance(body, dict):
        raise CapeBadResponse(call, "body is not a JSON object")
    # Success is `error: false` on task calls and `error: []` on status calls; `tasks/delete`
    # omits the field on success. Any truthy value is a failure.
    if body.get("error"):
        raise CapeRejected(call, _error_message(body))
    if response.is_error:
        raise CapeBadResponse(call, f"HTTP {response.status_code}")
    return body


def _form_fields(task_fields: Mapping[str, bool | int | str]) -> dict[str, str]:
    # CAPE reads a flag as present or absent, so a false one is left out.
    return {
        name: "1" if value is True else str(value)
        for name, value in task_fields.items()
        if value is not False
    }


def _error_message(body: dict[str, Any]) -> str:
    for key in ("error_value", *DELETE_FAILURE_KEYS):
        if body.get(key):
            return str(body[key])
    return NO_MESSAGE


def _parse[Model: BaseModel](call: str, model: type[Model], data: object) -> Model:
    try:
        return model.model_validate(data)
    except ValidationError:
        raise CapeBadResponse(call, f"{model.__name__} is not in the expected shape") from None


def _data(call: str, body: dict[str, Any]) -> object:
    if "data" not in body:
        raise CapeBadResponse(call, "no data in the answer")
    return body["data"]


def _first_task_id(call: str, data: object) -> int:
    task_ids = data.get("task_ids") if isinstance(data, dict) else None
    if not isinstance(task_ids, list) or not task_ids or not isinstance(task_ids[0], int):
        raise CapeBadResponse(call, "no task id in the answer")
    return task_ids[0]
