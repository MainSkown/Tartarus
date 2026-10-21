"""Tests of the memory routes of `bin/guest-control`: `POST /memory/{id}/analyse` and
`DELETE /memory/{id}/dump`, in front of `memory_logic` (tested on its own in test_memory_logic.py).

The service runs for real on a loopback port with a fake `vol` runner and a temp storage.
"""

import json

import memory_logic
import pytest
from fixtures.volatility_output import (
    BANNER,
    KERNEL_GUID,
    UNSATISFIED,
    failure,
    missing_symbols_log,
    success,
)
from test_control_http import AUTH, TOKEN, load_script, served
from test_guest_control import FakeEngine
from test_memory_logic import report_with_processes

guest_control = load_script("guest-control")


@pytest.fixture
def storage(tmp_path):
    analysis = tmp_path / "storage" / "analyses" / "7"
    (analysis / "reports").mkdir(parents=True)
    (analysis / "memory.dmp").write_bytes(b"dump")
    (analysis / "reports" / "report.json").write_text(json.dumps(report_with_processes()))
    return tmp_path / "storage"


@pytest.fixture
def analyser(storage, tmp_path):
    def runner(command, timeout):
        plugin = next(word for word in command if word.startswith("windows."))
        return success(plugin)

    return memory_logic.MemoryAnalyser(storage, tmp_path / "symbols", runner, log=lambda _m: None)


@pytest.fixture
def client(analyser):
    handler = guest_control.make_handler(FakeEngine(), token=TOKEN, memory=analyser)
    with served(handler) as started:
        yield started


def test_analyse_answers_200_with_the_summary_and_leaves_the_results_beside_the_dump(
    client, storage
):
    reply = client.request("POST", "/memory/7/analyse", headers=AUTH)

    assert reply.status == 200
    assert reply.json["plugins"] == {
        "windows.pslist": 144,
        "windows.cmdline": 144,
        "windows.malware.malfind": 10,
        "windows.malware.hollowprocesses": 2,
    }
    assert reply.json["pids"] == [1384, 1936, 6304]
    assert (storage / "analyses" / "7" / "memory" / "run.json").is_file()


def test_analyse_of_a_task_without_a_dump_is_404(client):
    reply = client.request("POST", "/memory/8/analyse", headers=AUTH)

    assert (reply.status, reply.json) == (404, {"error": "no memory dump for this task"})


@pytest.mark.parametrize("task_id", ["abc", "7a", "..%2F7", "%2e%2e"])
def test_a_task_id_that_is_not_digits_is_400_for_both_routes(client, task_id):
    assert client.request("POST", f"/memory/{task_id}/analyse", headers=AUTH).status == 400
    assert client.request("DELETE", f"/memory/{task_id}/dump", headers=AUTH).status == 400


def test_a_path_with_more_segments_is_not_a_route(client):
    reply = client.request("POST", "/memory/7/../8/analyse", headers=AUTH)

    assert reply.status == 404


def test_delete_removes_the_dump_with_204_and_then_answers_404(client, storage):
    first = client.request("DELETE", "/memory/7/dump", headers=AUTH)
    second = client.request("DELETE", "/memory/7/dump", headers=AUTH)

    assert (first.status, first.raw) == (204, b"")
    assert second.status == 404
    assert not (storage / "analyses" / "7" / "memory.dmp").exists()


@pytest.mark.parametrize(
    ("method", "path"), [("GET", "/memory/7/analyse"), ("POST", "/memory/7/dump")]
)
def test_the_routes_accept_only_their_method(client, method, path):
    assert client.request(method, path, headers=AUTH).status == 405


def test_the_memory_routes_work_while_the_guest_engine_is_not_installed(analyser):
    handler = guest_control.make_handler(
        guest_control.NotReadyEngine(), token=TOKEN, memory=analyser
    )
    with served(handler) as started:
        assert started.request("POST", "/memory/7/analyse", headers=AUTH).status == 200


def test_a_volatility_that_cannot_start_is_502_with_its_message(storage, tmp_path):
    def cannot_start(command, timeout):
        raise FileNotFoundError("vol")

    broken = memory_logic.MemoryAnalyser(storage, tmp_path / "s", cannot_start, log=lambda _m: None)
    handler = guest_control.make_handler(FakeEngine(), token=TOKEN, memory=broken)
    with served(handler) as started:
        reply = started.request("POST", "/memory/7/analyse", headers=AUTH)

    assert (reply.status, reply.json) == (
        502,
        {"error": "volatility could not be started (FileNotFoundError)"},
    )


def test_the_service_builds_the_real_analyser_for_the_container_by_default():
    analyser = memory_logic.in_container(log=print)

    assert analyser.storage == memory_logic.STORAGE_DIRECTORY
    assert analyser.symbols_directory == memory_logic.SYMBOLS_DIRECTORY
    assert analyser.runner.keywords["user"] == "cape"
    # Nothing of the service's own environment (it holds the bearer token) reaches `vol`.
    assert analyser.runner.keywords["environment"] == memory_logic.CAPE_ENVIRONMENT
    assert set(memory_logic.CAPE_ENVIRONMENT) == {"HOME", "PATH", "LANG"}
    assert memory_logic.CAPE_ENVIRONMENT["HOME"] == "/home/cape"


def test_analyse_of_a_dump_without_symbols_names_the_pdb_id_that_would_fix_it(storage, tmp_path):
    def runner(command, timeout):
        plugin = next(word for word in command if word.startswith("windows."))
        if plugin == "windows.info":
            return failure(stdout=UNSATISFIED, stderr=BANNER + missing_symbols_log())
        return success(plugin)

    analyser = memory_logic.MemoryAnalyser(
        storage, tmp_path / "symbols", runner, log=lambda _m: None
    )
    handler = guest_control.make_handler(FakeEngine(), token=TOKEN, memory=analyser)
    with served(handler) as client:
        reply = client.request("POST", "/memory/7/analyse", headers=AUTH)

    assert reply.status == 200
    assert reply.json["missing_symbols"] == {"guid": KERNEL_GUID, "age": 1}
    assert set(reply.json["errors"].values()) == {"no symbols for this Windows build"}


@pytest.fixture
def imports(analyser, tmp_path):
    folder = tmp_path / "imports"
    folder.mkdir()
    (folder / "image.raw").write_bytes(b"image")
    analyser.imports_directory = folder
    return folder


def test_analyse_names_an_image_under_imports_in_its_body(client, storage, imports):
    reply = client.request("POST", "/memory/900001/analyse", {"image": "image.raw"}, headers=AUTH)

    assert reply.status == 200
    assert reply.json["pids"] == []
    assert (storage / "analyses" / "900001" / "memory" / "run.json").is_file()


@pytest.mark.parametrize("image", [7, ["image.raw"]])
def test_an_image_that_is_not_a_string_is_400(client, imports, image):
    reply = client.request("POST", "/memory/900001/analyse", {"image": image}, headers=AUTH)

    assert (reply.status, reply.json) == (400, {"error": "the image must be a file under /imports"})


def test_an_image_outside_imports_is_400_and_a_missing_one_404(client, imports):
    outside = client.request("POST", "/memory/7/analyse", {"image": "../x"}, headers=AUTH)
    missing = client.request("POST", "/memory/7/analyse", {"image": "gone.raw"}, headers=AUTH)

    assert outside.status == 400
    assert missing.status == 404
