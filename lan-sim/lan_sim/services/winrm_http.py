"""HTTP/1.x framing for the WinRM listener: the request head and body read strictly, and replies.

Every byte here comes from a client that may be hostile, so anything outside what WinRM clients
send is refused with a status before it is interpreted. The head is read with the connection's
own cap, so a client cannot make the daemon buffer more than `MAX_HEAD_BYTES` for one request.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass

from lan_sim.limits import KIB
from lan_sim.service import Connection, ReadCapExceeded

MAX_HEAD_BYTES = 8 * KIB
MAX_HEADERS = 50
MAX_BODY_BYTES = 64 * KIB
HEAD_END = b"\r\n\r\n"
REQUEST_LINE = re.compile(rb"([A-Z]{1,16}) (/[\x21-\x7e]*) (HTTP/1\.[01])")
HEADER_NAME = re.compile(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,256}")
HEADER_VALUE = re.compile(rb"[\x20-\x7e\t]*")
CONTENT_LENGTH = re.compile(r"[0-9]{1,10}")
REASONS = {
    200: "OK",
    400: "Bad Request",
    401: "Unauthorized",
    404: "Not Found",
    413: "Payload Too Large",
}


class MalformedRequestError(Exception):
    """The request cannot be answered as sent; `status` is the reply to give."""

    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


@dataclass(frozen=True)
class Request:
    method: str
    target: str
    version: str
    headers: Mapping[str, str]
    body: bytes

    def header(self, name: str) -> str | None:
        return self.headers.get(name)

    @property
    def keeps_alive(self) -> bool:
        return self.version == "HTTP/1.1" and self.headers.get("connection", "").lower() != "close"


@dataclass(frozen=True)
class Reply:
    """A reply to one request. `keeps_open` asks for the connection to stay for another request."""

    status: int
    headers: tuple[tuple[str, str], ...] = ()
    body: bytes = b""
    keeps_open: bool = False


def render(reply: Reply, *, close: bool) -> bytes:
    lines = [f"HTTP/1.1 {reply.status} {REASONS[reply.status]}", "Server: Microsoft-HTTPAPI/2.0"]
    lines += [f"{name}: {value}" for name, value in reply.headers]
    lines.append(f"Content-Length: {len(reply.body)}")
    if close:
        lines.append("Connection: close")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii") + reply.body


async def read_request(connection: Connection) -> Request:
    try:
        head = await connection.read_until(HEAD_END, MAX_HEAD_BYTES)
    except ReadCapExceeded as error:
        raise MalformedRequestError(400) from error
    method, target, version, headers = parse_head(head[: -len(HEAD_END)])
    length = body_length(headers)
    if length == 0:
        return Request(method, target, version, headers, b"")
    try:
        body = await connection.read_exactly(length)
    except ReadCapExceeded as error:
        raise MalformedRequestError(413) from error
    return Request(method, target, version, headers, body)


def parse_head(block: bytes) -> tuple[str, str, str, dict[str, str]]:
    request_line, *header_lines = block.split(b"\r\n")
    match = REQUEST_LINE.fullmatch(request_line)
    if match is None or len(header_lines) > MAX_HEADERS:
        raise MalformedRequestError(400)
    method, target, version = (part.decode("ascii") for part in match.groups())
    return method, target, version, _headers(header_lines)


def body_length(headers: Mapping[str, str]) -> int:
    if "transfer-encoding" in headers:
        raise MalformedRequestError(400)
    raw = headers.get("content-length")
    if raw is None:
        return 0
    if CONTENT_LENGTH.fullmatch(raw) is None:
        raise MalformedRequestError(400)
    length = int(raw)
    if length > MAX_BODY_BYTES:
        raise MalformedRequestError(413)
    return length


def _headers(lines: list[bytes]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in lines:
        name, colon, value = line.partition(b":")
        if not colon or HEADER_NAME.fullmatch(name) is None or not HEADER_VALUE.fullmatch(value):
            raise MalformedRequestError(400)
        key = name.decode("ascii").lower()
        if key in headers:
            raise MalformedRequestError(400)
        headers[key] = value.strip(b" \t").decode("ascii")
    return headers
