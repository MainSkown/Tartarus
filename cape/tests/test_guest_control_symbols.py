"""Tests of `POST /symbols` in `bin/guest-control`, in front of `symbols_logic`.

`symbols_logic` is tested on its own in test_symbols_logic.py.

The service runs for real on a loopback port; the symbol server and the converter are fakes and the
symbol directory is a temp folder.
"""

import tempfile

import memory_logic
import pytest
import symbols_logic
from test_control_http import AUTH, TOKEN, load_script, served
from test_guest_control import FakeEngine
from test_symbols_logic import (
    FILE_NAME,
    GUID,
    URL,
    FakeConvert,
    FakeFetch,
    files_under,
)

guest_control = load_script("guest-control")


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    return symbols_logic.SymbolStore(tmp_path / "symbols", FakeFetch(), FakeConvert())


def client_of(store):
    handler = guest_control.make_handler(FakeEngine(), token=TOKEN, symbols=store)
    return served(handler)


def test_a_new_id_answers_200_with_the_file_and_created_true(store):
    with client_of(store) as client:
        reply = client.request("POST", "/symbols", {"guid": GUID, "age": 1}, AUTH)

    assert (reply.status, reply.json) == (200, {"file": FILE_NAME, "created": True})
    assert store.fetch.calls[0][0] == URL
    assert files_under(store.directory) == [FILE_NAME]


def test_the_same_id_again_answers_created_false_without_fetching(store):
    with client_of(store) as client:
        client.request("POST", "/symbols", {"guid": GUID, "age": 1}, AUTH)
        reply = client.request("POST", "/symbols", {"guid": GUID.lower(), "age": "1"}, AUTH)

    assert reply.json == {"file": FILE_NAME, "created": False}
    assert len(store.fetch.calls) == 1


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"guid": GUID},
        {"guid": "../../etc/passwd", "age": 1},
        {"guid": GUID, "age": 0},
        {"guid": GUID, "age": "not hex"},
        {"guid": GUID, "age": 1, "url": "https://evil.example.com/x"},
    ],
)
def test_a_body_that_is_not_a_valid_id_answers_400_and_fetches_nothing(store, body):
    with client_of(store) as client:
        reply = client.request("POST", "/symbols", body, AUTH)

    assert reply.status == 400
    assert reply.json["error"]
    assert store.fetch.calls == []


def test_a_body_that_is_not_json_answers_400(store):
    with client_of(store) as client:
        reply = client.request("POST", "/symbols", raw=b"not json", headers=AUTH)

    assert reply.status == 400
    assert store.fetch.calls == []


def test_a_symbol_server_that_cannot_be_reached_answers_502_with_a_readable_error(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    failing = symbols_logic.SymbolStore(
        tmp_path / "symbols",
        FakeFetch(
            symbols_logic.FetchFailedError("the symbol server could not be reached (no DNS)")
        ),
        FakeConvert(),
    )
    with client_of(failing) as client:
        reply = client.request("POST", "/symbols", {"guid": GUID, "age": 1}, AUTH)

    assert reply.status == 502
    assert reply.json == {"error": "the symbol server could not be reached (no DNS)"}


def test_the_route_needs_the_bearer_token(store):
    with client_of(store) as client:
        reply = client.request("POST", "/symbols", {"guid": GUID, "age": 1})

    assert reply.status == 401
    assert store.fetch.calls == []


def test_the_route_accepts_only_post(store):
    with client_of(store) as client:
        assert client.request("GET", "/symbols", headers=AUTH).status == 405


def test_the_route_works_while_the_guest_engine_is_not_installed(store):
    handler = guest_control.make_handler(guest_control.NotReadyEngine(), token=TOKEN, symbols=store)
    with served(handler) as client:
        reply = client.request("POST", "/symbols", {"guid": GUID, "age": 1}, AUTH)

    assert reply.status == 200


def test_in_the_image_the_service_uses_the_real_fetcher_converter_and_directory():
    real = symbols_logic.in_container()

    assert real.directory == memory_logic.SYMBOLS_DIRECTORY
    assert real.fetch is symbols_logic.fetch_from_symbol_server
    assert real.convert is symbols_logic.convert_with_volatility
