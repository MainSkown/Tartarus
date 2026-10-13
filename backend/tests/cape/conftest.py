import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.cape.client import CapeClient

FIXTURES = Path(__file__).parent.parent / "fixtures" / "cape"
TOKEN = "tok-0123456789abcdef"  # noqa: S105
BASE_URL = "http://cape-internal.example:8000"

type Handler = Callable[[httpx.Request], httpx.Response]


def captured_response(name: str) -> httpx.Response:
    """A response replayed from a capture; some captures end with a line holding the HTTP status."""
    text = (FIXTURES / name).read_text().rstrip("\n")
    body, _, last_line = text.rpartition("\n")
    if last_line.isdigit():
        return httpx.Response(int(last_line), content=body)
    return httpx.Response(200, content=text)


def json_response(payload: Any, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, content=json.dumps(payload))


class RecordingCape:
    """Serves each request path from `routes` and remembers what it was asked."""

    def __init__(self, routes: dict[str, httpx.Response | Exception]) -> None:
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        outcome = self.routes[request.url.path]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def cape_client() -> Callable[[Handler, str | None], CapeClient]:
    def build(handler: Handler, token: str | None = TOKEN) -> CapeClient:
        return CapeClient(BASE_URL, token, transport=httpx.MockTransport(handler))

    return build
