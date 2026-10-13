from types import TracebackType
from typing import Self

import httpx

from app.cape.errors import CapeBadResponse, CapeRejected, CapeUnreachable
from app.config import Settings

DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=3.0)
FINISH_CALL = "finish"


class CapeControl:
    """Client of `finish-run`, the helper in the cape container that ends a run early.

    The guest network exists only inside that container, so this is the only way to reach the
    guest agent. It never retries; finishing is idempotent and the analyst can ask again.
    """

    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    ) -> None:
        self._http = httpx.AsyncClient(base_url=base_url, transport=transport, timeout=timeout)

    @classmethod
    def from_settings(
        cls, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> Self:
        return cls(settings.cape_control_url, transport=transport)

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

    async def finish_task(self, task_id: int) -> None:
        """Ask the guest to end the analysis of a CAPE task; the analyzer notices within seconds."""
        try:
            response = await self._http.post(f"/tasks/{task_id}/finish")
        except httpx.TransportError as error:
            # Only the type: httpx messages can carry the URL.
            raise CapeUnreachable(FINISH_CALL, type(error).__name__) from None
        _require_finished(response)


def _require_finished(response: httpx.Response) -> None:
    body = _json_object(response)
    # The helper answers 502 with its reason when the guest agent could not be asked.
    if response.status_code == httpx.codes.BAD_GATEWAY:
        reason = body.get("error")
        if isinstance(reason, str) and reason:
            raise CapeRejected(FINISH_CALL, reason)
    if response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
        raise CapeUnreachable(FINISH_CALL, f"HTTP {response.status_code}")
    if response.is_error or body.get("finished") is not True:
        raise CapeBadResponse(FINISH_CALL, f"HTTP {response.status_code}, not a finish")


def _json_object(response: httpx.Response) -> dict[str, object]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}
