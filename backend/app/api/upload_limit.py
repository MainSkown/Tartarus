import inspect
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import HTTPException, Request, Response
from fastapi.routing import APIRoute

from app.api.dependencies import get_sample_store
from app.config import get_settings
from app.imports.upload import ImportLimits

# The multipart framing and the form's other fields on top of the file itself.
MULTIPART_ALLOWANCE = 1024**2

type LimitOf = Callable[[Request], int]


def sample_limit(request: Request) -> int:
    return int(_provided(request, get_sample_store).max_bytes)


def pcap_limit(request: Request) -> int:
    return _import_limits(request).pcap_bytes


def memory_image_limit(request: Request) -> int:
    return _import_limits(request).memory_image_bytes


def refusing_oversized_bodies(limit_of: LimitOf) -> type[APIRoute]:
    """A route class that answers `413` when `Content-Length` announces more than the limit.

    Starlette spools a whole multipart body to disk before any dependency or handler runs, so
    the size check has to happen when the request reaches the route, before the body is read.
    """

    class _Route(APIRoute):
        def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
            handler = super().get_route_handler()

            async def refusing(request: Request) -> Response:
                announced = request.headers.get("content-length", "")
                limit = limit_of(request)
                if announced.isdigit() and int(announced) > limit + MULTIPART_ALLOWANCE:
                    raise HTTPException(413, f"The file is larger than {limit} bytes")
                return await handler(request)

            return refusing

    return _Route


def _import_limits(request: Request) -> ImportLimits:
    settings = _provided(request, get_settings)
    return ImportLimits(settings.import_pcap_max_bytes, settings.import_memory_image_max_bytes)


def _provided(request: Request, dependency: Callable[..., Any]) -> Any:
    """What the route would be given for `dependency`, honouring a test's override of it."""
    provider = request.app.dependency_overrides.get(dependency, dependency)
    return provider(request) if inspect.signature(provider).parameters else provider()
