"""Tests of `bin/control_http.py`, the HTTP plumbing `guest-control` and `finish-run` share.

The server runs for real on a loopback port; requests go through `http.client` so paths reach it
exactly as written.
"""

import http.client
import importlib
import importlib.machinery
import importlib.util
import json
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

BIN = Path(__file__).resolve().parents[1] / "bin"
# The scripts in bin/ are not a package: they import their siblings from their own directory.
sys.path.insert(0, str(BIN))
control_http = importlib.import_module("control_http")

TOKEN = "t" * 40
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def load_script(name: str):
    """Imports an extensionless script from bin/ the way its tests need it: as a module."""
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), str(BIN / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@dataclass
class Reply:
    status: int
    headers: dict[str, str]
    text: str

    @property
    def json(self):
        return json.loads(self.text)


class Client:
    def __init__(self, port: int) -> None:
        self.port = port

    def request(
        self, method: str, path: str, body=None, headers=None, raw: bytes | None = None
    ) -> Reply:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        payload = (
            raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        )
        try:
            connection.request(method, path, body=payload, headers=headers or {})
            answer = connection.getresponse()
            return Reply(
                answer.status,
                {k.lower(): v for k, v in answer.getheaders()},
                answer.read().decode(),
            )
        finally:
            connection.close()


@contextmanager
def served(handler_class) -> Iterator[Client]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        yield Client(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def echo(request):
    return 200, {
        "method": request.method,
        "arguments": request.arguments,
        "query": request.query,
        "body": request.body,
    }


def health(request):
    return 200, {"ok": True}


def boom(request):
    raise RuntimeError("secret detail: password=hunter2")


def refuse(request):
    raise control_http.HttpError(418, {"error": "teapot"})


def nothing(request):
    return 204, None


def unserialisable(request):
    return 200, {"value": object()}


ROUTES = [
    control_http.Route("GET", "/health", health, public=True),
    control_http.Route("GET", r"/things/(?P<name>[^/]*)", echo),
    control_http.Route("POST", r"/things/(?P<name>[^/]*)", echo),
    control_http.Route("DELETE", r"/things/(?P<name>[^/]*)", nothing),
    control_http.Route("GET", "/boom", boom),
    control_http.Route("GET", "/refuse", refuse),
    control_http.Route("GET", "/unserialisable", unserialisable),
]


@pytest.fixture
def client() -> Iterator[Client]:
    handler = control_http.make_handler(ROUTES, service="test", token=TOKEN)
    with served(handler) as running:
        yield running


def test_a_route_gets_its_path_arguments_query_and_json_body(client):
    reply = client.request("POST", "/things/abc?tail=5&tail=6&x=", {"k": [1]}, AUTH)

    assert reply.status == 200
    assert reply.json == {
        "method": "POST",
        "arguments": {"name": "abc"},
        "query": {"tail": "5", "x": ""},
        "body": {"k": [1]},
    }


def test_path_arguments_are_not_percent_decoded(client):
    reply = client.request("GET", "/things/%2e%2e", headers=AUTH)

    assert reply.json["arguments"] == {"name": "%2e%2e"}


def test_a_request_without_a_body_has_an_empty_object(client):
    assert client.request("POST", "/things/a", headers=AUTH).json["body"] == {}


def test_answers_are_json(client):
    reply = client.request("GET", "/things/a", headers=AUTH)

    assert reply.headers["content-type"] == "application/json"
    assert int(reply.headers["content-length"]) == len(reply.text.encode())


def test_a_none_body_answers_with_no_content(client):
    reply = client.request("DELETE", "/things/a", headers=AUTH)

    assert (reply.status, reply.text) == (204, "")


def test_an_unknown_path_is_404(client):
    reply = client.request("GET", "/nowhere", headers=AUTH)

    assert (reply.status, reply.json) == (404, {"error": "not found"})


def test_the_wrong_method_is_405_and_names_the_allowed_ones(client):
    reply = client.request("PUT", "/things/a", headers=AUTH)

    assert reply.status == 405
    assert reply.headers["allow"] == "DELETE, GET, POST"


def test_the_wrong_method_status_can_be_set_by_the_service():
    handler = control_http.make_handler(ROUTES, service="test", wrong_method_status=404)
    with served(handler) as client:
        assert client.request("PUT", "/things/a").status == 404


def test_head_answers_the_status_and_no_body(client):
    reply = client.request("HEAD", "/things/a", headers=AUTH)

    assert (reply.status, reply.text) == (405, "")


def test_a_handler_can_answer_with_an_http_error(client):
    reply = client.request("GET", "/refuse", headers=AUTH)

    assert (reply.status, reply.json) == (418, {"error": "teapot"})


def test_any_other_exception_is_a_generic_500_and_the_detail_stays_in_the_log(client, capsys):
    reply = client.request("GET", "/boom", headers=AUTH)

    assert reply.status == 500
    assert reply.json == {"error": "internal error"}
    assert "hunter2" not in reply.text
    assert "hunter2" in capsys.readouterr().out


def test_a_body_that_cannot_be_serialised_is_a_500(client):
    reply = client.request("GET", "/unserialisable", headers=AUTH)

    assert (reply.status, reply.json) == (500, {"error": "internal error"})


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer wrong"}, {"Authorization": TOKEN}, {"Authorization": "Bearer "}],
)
def test_without_the_right_token_the_answer_is_401_with_nothing_to_learn(client, headers):
    reply = client.request("GET", "/things/a", headers=headers)

    assert reply.status == 401
    assert reply.json == {"error": "unauthorized"}
    assert reply.headers["www-authenticate"] == "Bearer"


def test_an_unknown_path_without_the_token_is_401_not_404(client):
    assert client.request("GET", "/nowhere").status == 401
    assert client.request("PUT", "/things/a").status == 401


def test_the_scheme_is_case_insensitive(client):
    assert (
        client.request("GET", "/things/a", headers={"Authorization": f"bearer {TOKEN}"}).status
        == 200
    )


def test_a_public_route_needs_no_token(client):
    reply = client.request("GET", "/health")

    assert (reply.status, reply.json) == (200, {"ok": True})


def test_the_token_is_compared_in_constant_time(monkeypatch):
    compared = []

    def spy(left, right):
        compared.append((left, right))
        return left == right

    monkeypatch.setattr(control_http.hmac, "compare_digest", spy)

    assert control_http.bearer_token_matches(f"Bearer {TOKEN}", TOKEN)
    assert compared == [(TOKEN.encode(), TOKEN.encode())]


def test_a_non_ascii_authorization_header_is_refused_not_a_crash(client):
    reply = client.request("GET", "/things/a", headers={"Authorization": "Bearer café"})

    assert reply.status == 401


def test_a_service_without_a_token_does_not_authenticate():
    handler = control_http.make_handler(ROUTES, service="test")
    with served(handler) as client:
        assert client.request("GET", "/things/a").status == 200


def test_a_body_of_exactly_the_limit_is_accepted(client):
    filler = control_http.MAX_BODY_BYTES - len(b'{"k":""}')
    reply = client.request("POST", "/things/a", raw=b'{"k":"' + b"x" * filler + b'"}', headers=AUTH)

    assert reply.status == 200


def test_a_body_over_the_limit_is_413_and_is_not_kept(client):
    reply = client.request(
        "POST", "/things/a", raw=b" " * (control_http.MAX_BODY_BYTES + 1), headers=AUTH
    )

    assert (reply.status, reply.json) == (
        413,
        {"error": "the request body is larger than 65536 bytes"},
    )


def test_the_size_limit_is_checked_after_the_token(client):
    assert (
        client.request("POST", "/things/a", raw=b" " * (control_http.MAX_BODY_BYTES + 1)).status
        == 401
    )


@pytest.mark.parametrize("raw", [b"{nope", b"[1, 2]", b'"text"', b"\xff\xfe"])
def test_a_body_that_is_not_a_json_object_is_400(client, raw):
    reply = client.request("POST", "/things/a", raw=raw, headers=AUTH)

    assert reply.status == 400
    assert "error" in reply.json


def test_a_chunked_body_is_refused(client):
    reply = client.request(
        "POST", "/things/a", raw=b"0\r\n\r\n", headers={**AUTH, "Transfer-Encoding": "chunked"}
    )

    assert reply.status == 411


def test_a_negative_or_garbled_content_length_is_400(client):
    for length in ("-5", "abc"):
        reply = client.request("POST", "/things/a", headers={**AUTH, "Content-Length": length})
        assert reply.status == 400, length


def test_the_log_names_the_request_and_the_error_but_never_the_token_or_the_body(client, capsys):
    client.request("POST", "/things/a?x=1", {"password": "hunter2"}, AUTH)
    client.request("GET", "/refuse", headers=AUTH)
    client.request("GET", "/things/a", headers={"Authorization": "Bearer wrong-token-value"})

    logged = capsys.readouterr().out
    assert "test: POST /things/a?x=1 -> 200" in logged
    assert "test: GET /refuse -> 418 (teapot)" in logged
    assert "test: GET /things/a -> 401 (unauthorized)" in logged
    for secret in (TOKEN, "hunter2", "wrong-token-value"):
        assert secret not in logged


def test_serving_listens_on_the_given_address_only():
    server = control_http.make_server(
        "127.0.0.1", 0, control_http.make_handler(ROUTES, service="test")
    )
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()
