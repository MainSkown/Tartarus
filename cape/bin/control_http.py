"""The HTTP plumbing of the services in this directory (`guest-control`, `finish-run`).

A service declares a route table of `Route`s whose handlers take a `Request` and return
`(status, json_body)`, or `(status, Binary(...))` for a file; this module does the rest: matching,
bearer-token authentication, the body size limit, JSON in and out, the generic 500, and a log line
per request that never holds a secret (no headers, no body).
"""

import hmac
import json
import re
import sys
import traceback
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar
from urllib.parse import parse_qs

MAX_BODY_BYTES = 64 * 1024
# A rejected oversized body is read and dropped up to this much, so the client sees the 413
# instead of a connection reset; beyond it the connection is simply closed.
MAX_DISCARDED_BYTES = 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 30
INTERNAL_ERROR = {"error": "internal error"}
UNAUTHORIZED = {"error": "unauthorized"}
NUMBER = re.compile(r"[0-9]{1,18}")

type Answer = tuple[int, Any]


@dataclass(frozen=True)
class Binary:
    """A handler's answer that is a file, not JSON: its bytes, content type and extra headers."""

    data: bytes
    content_type: str
    headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Request:
    method: str
    arguments: dict[str, str]
    query: dict[str, str]
    body: dict[str, Any]


@dataclass(frozen=True)
class Route:
    """`pattern` is a regular expression for the whole path, its named groups become `arguments`."""

    method: str
    pattern: str
    handler: Callable[[Request], Answer]
    public: bool = False
    matcher: re.Pattern[str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "matcher", re.compile(self.pattern))


class HttpError(Exception):
    def __init__(self, status: int, body: dict[str, Any]) -> None:
        super().__init__(status, body)
        self.status = status
        self.body = body


def bearer_token_matches(authorization: str | None, token: str) -> bool:
    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.lower() != "bearer":
        return False
    return hmac.compare_digest(supplied.encode(), token.encode())


def log(service: str, message: str) -> None:
    sys.stdout.write(f"{service}: {message}\n")
    sys.stdout.flush()


def make_server(
    address: str, port: int, handler: type[BaseHTTPRequestHandler]
) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((address, port), handler)


def make_handler(
    routes: list[Route],
    *,
    service: str,
    token: str | None = None,
    wrong_method_status: int = 405,
) -> type[BaseHTTPRequestHandler]:
    """`token` None means no authentication. `wrong_method_status` exists for `finish-run`,
    which has always answered 404 to a method its one route does not take."""
    attributes = {
        "routes": routes,
        "service": service,
        "token": token,
        "wrong_method_status": wrong_method_status,
    }
    return type("ControlHandler", (ControlHandler,), attributes)


class ControlHandler(BaseHTTPRequestHandler):
    routes: ClassVar[list[Route]]
    service: ClassVar[str]
    token: ClassVar[str | None]
    wrong_method_status: ClassVar[int]
    timeout = REQUEST_TIMEOUT_SECONDS

    def _handle(self) -> None:
        path, _, query_string = self.path.partition("?")
        matches = [(r, m) for r in self.routes if (m := r.matcher.fullmatch(path))]
        route, match = next(((r, m) for r, m in matches if r.method == self.command), (None, None))
        if not self._authorized(route):
            self._discard_declared_body()
            self._answer(401, UNAUTHORIZED, {"WWW-Authenticate": "Bearer"})
        elif route is None or match is None:
            self._discard_declared_body()
            self._answer(*self._unrouted_answer(sorted({r.method for r, _ in matches})))
        else:
            arguments = match.groupdict()
            self._answer(*self._run(route, arguments, _first_values(query_string)))

    def _authorized(self, route: Route | None) -> bool:
        if self.token is None or (route is not None and route.public):
            return True
        return bearer_token_matches(self.headers.get("Authorization"), self.token)

    def _unrouted_answer(self, allowed_methods: list[str]) -> tuple[int, dict, dict | None]:
        if not allowed_methods:
            return 404, {"error": "not found"}, None
        if self.wrong_method_status != 405:  # noqa: PLR2004 - 405 is the HTTP status, not a tuning value
            return self.wrong_method_status, {"error": "not found"}, None
        return 405, {"error": "method not allowed"}, {"Allow": ", ".join(allowed_methods)}

    def _run(self, route: Route, arguments: dict[str, str], query: dict[str, str]) -> Answer:
        try:
            request = Request(self.command, arguments, query, self._read_json_object())
            return route.handler(request)
        except HttpError as refused:
            return refused.status, refused.body
        except Exception:  # noqa: BLE001 - the last line of defence: the detail goes to the log only
            log(self.service, f"{self.command} {self.path} failed\n{traceback.format_exc()}")
            return 500, INTERNAL_ERROR

    def _read_json_object(self) -> dict[str, Any]:
        if "Transfer-Encoding" in self.headers:
            raise HttpError(
                411, {"error": "send a Content-Length, chunked bodies are not supported"}
            )
        declared = self.headers.get("Content-Length", "0")
        if not NUMBER.fullmatch(declared):
            raise HttpError(400, {"error": "the Content-Length is not a number"})
        length = int(declared)
        if length > MAX_BODY_BYTES:
            self._discard(length)
            raise HttpError(
                413, {"error": f"the request body is larger than {MAX_BODY_BYTES} bytes"}
            )
        return _json_object(self.rfile.read(length))

    def _discard_declared_body(self) -> None:
        declared = self.headers.get("Content-Length", "0")
        if NUMBER.fullmatch(declared):
            self._discard(int(declared))

    def _discard(self, length: int) -> None:
        self.close_connection = True
        remaining = min(length, MAX_DISCARDED_BYTES)
        while remaining > 0:
            chunk = self.rfile.read(min(remaining, 65536))
            if not chunk:
                return
            remaining -= len(chunk)

    def _answer(self, status: int, body: Any, headers: Mapping[str, str] | None = None) -> None:
        if isinstance(body, Binary):
            payload, content_type = body.data, body.content_type
            headers = {**body.headers, **(headers or {})}
        else:
            try:
                payload = b"" if body is None else json.dumps(body).encode()
            except (TypeError, ValueError):
                log(self.service, f"{self.command} {self.path} produced a body that is not JSON")
                status, body, payload = 500, INTERNAL_ERROR, json.dumps(INTERNAL_ERROR).encode()
            content_type = "application/json" if payload else ""
        self.send_response(status)
        if content_type:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)
        self.log_message("%s %s -> %s%s", self.command, self.path, status, _logged_error(body))

    # http.server dispatches on the method name, so these are not ours to rename.
    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = _handle  # noqa: N815

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - BaseHTTPRequestHandler's signature
        log(self.service, format % args)


def _json_object(raw: bytes) -> dict[str, Any]:
    if not raw.strip():
        return {}
    try:
        body = json.loads(raw)
    except ValueError as invalid:  # JSONDecodeError and UnicodeDecodeError alike
        raise HttpError(400, {"error": "the request body is not valid JSON"}) from invalid
    if not isinstance(body, dict):
        raise HttpError(400, {"error": "the request body must be a JSON object"})
    return body


def _first_values(query_string: str) -> dict[str, str]:
    parsed = parse_qs(query_string, keep_blank_values=True)
    return {name: values[0] for name, values in parsed.items()}


def _logged_error(body: Any) -> str:
    return f" ({body['error']})" if isinstance(body, dict) and "error" in body else ""
