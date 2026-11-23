"""The wire contract between the control service and the lan-sim daemon.

`lan_session.py` is copied into both images, so it is tested on its own: every value a session file
or a status file may carry is validated, and anything else is refused with a message.
"""

import json
import os
import threading
from pathlib import Path

import pytest

from guest_engine import lan_session
from guest_engine.lan_session import (
    HostSpec,
    Layout,
    ServiceSpec,
    SessionFormatError,
    SessionSpec,
    SessionStatus,
)

GUEST = "192.168.150.10"


def a_host(**changes) -> HostSpec:
    fields = {
        "fqdn": "fs01.corp.local",
        "address": "192.168.150.201",
        "os_banner": "Windows Server 2019",
        "accounts": (("Administrator", "Password1"),),
        "services": (ServiceSpec("smb", 445, {"shares": ["Public"]}), ServiceSpec("rdp", 3389)),
    }
    return HostSpec(**{**fields, **changes})


def a_session(**changes) -> SessionSpec:
    fields = {
        "key": "task-17",
        "guest_address": GUEST,
        "preset_id": "small-office",
        "hosts": (a_host(), a_host(fqdn="dc01.corp.local", address="192.168.150.200")),
    }
    return SessionSpec(**{**fields, **changes})


def as_dict(spec: SessionSpec) -> dict:
    return json.loads(spec.to_json())


def rejected(document, message: str):
    text = document if isinstance(document, str | bytes) else json.dumps(document)
    with pytest.raises(SessionFormatError, match=message or None):
        SessionSpec.from_json(text)


# --- the session file -----------------------------------------------------------------------------


def test_a_session_survives_a_round_trip():
    spec = a_session()

    assert SessionSpec.from_json(spec.to_json()) == spec


def test_a_session_file_is_accepted_as_bytes_too():
    spec = a_session()

    assert SessionSpec.from_json(spec.to_json().encode()) == spec


def test_the_wire_shape_is_plain_json_with_named_account_fields():
    document = as_dict(a_session())

    assert set(document) == {"key", "guest_address", "preset_id", "hosts"}
    assert document["hosts"][0]["accounts"] == [{"user": "Administrator", "password": "Password1"}]
    assert document["hosts"][0]["services"][0] == {
        "kind": "smb",
        "port": 445,
        "options": {"shares": ["Public"]},
    }


@pytest.mark.parametrize("key", ["1", "task-17", "A" * 64, "0a-b-c"])
def test_a_key_of_letters_digits_and_dashes_is_accepted(key):
    assert SessionSpec.from_json(a_session(key=key).to_json()).key == key


@pytest.mark.parametrize(
    "key",
    ["", "a b", "a;b", "a\nb", "-leading", "x" * 65, "../x", "a/b", "a.b", "ü", "a\n", "..", "."],
)
def test_a_key_that_is_not_letters_digits_and_dashes_is_refused(key):
    document = as_dict(a_session())
    document["key"] = key

    rejected(document, "key")


def test_a_non_string_key_is_refused():
    document = as_dict(a_session())
    document["key"] = 17

    rejected(document, "key")


@pytest.mark.parametrize(
    "address",
    [
        "",
        "192.168.150",
        "192.168.150.256",
        "::1",
        "192.168.150.1/24",
        "a.b.c.d",
        " 192.168.150.1",
        "0.0.0.0",  # noqa: S104 - a value the contract must refuse
        "255.255.255.255",
        "224.0.0.1",
        "0192.168.150.10",
        "192.168.150.010",
    ],
)
def test_an_address_that_is_not_a_unicast_ipv4_is_refused(address):
    document = as_dict(a_session())
    document["guest_address"] = address

    rejected(document, "guest_address")


def test_a_host_address_is_validated_like_the_guest_address():
    document = as_dict(a_session())
    document["hosts"][0]["address"] = "0.0.0.0"  # noqa: S104 - a value the contract must refuse

    rejected(document, "address")


@pytest.mark.parametrize("port", [0, 65536, -1, 1.5, "445", True, None])
def test_a_port_outside_1_to_65535_or_not_an_integer_is_refused(port):
    document = as_dict(a_session())
    document["hosts"][0]["services"][0]["port"] = port

    rejected(document, "port")


@pytest.mark.parametrize("kind", ["", "SMB", "sm b", "1smb", "x" * 33, "smb\n", "../smb"])
def test_a_service_kind_that_is_not_a_lowercase_word_is_refused(kind):
    document = as_dict(a_session())
    document["hosts"][0]["services"][0]["kind"] = kind

    rejected(document, "kind")


@pytest.mark.parametrize(
    "fqdn",
    [
        "",
        "fs01",
        "fs_01.corp.local",
        "FS01.corp.local",
        "fs01..local",
        "a.b\n",
        "-a.local",
        ("a" * 64) + ".local",
        ".".join(["a" * 60] * 5),
    ],
)
def test_a_host_name_that_is_not_an_fqdn_is_refused(fqdn):
    document = as_dict(a_session())
    document["hosts"][0]["fqdn"] = fqdn

    rejected(document, "fqdn")


@pytest.mark.parametrize("preset_id", ["", "A", "a", "x" * 33, "a b", "../a", "a\n"])
def test_a_preset_id_that_is_not_a_slug_is_refused(preset_id):
    document = as_dict(a_session())
    document["preset_id"] = preset_id

    rejected(document, "preset_id")


@pytest.mark.parametrize("field", ["os_banner", "user", "password"])
def test_a_control_character_in_a_text_field_is_refused(field):
    document = as_dict(a_session())
    target = document["hosts"][0] if field == "os_banner" else document["hosts"][0]["accounts"][0]
    target[field] = "bad\x00value"

    rejected(document, field)


@pytest.mark.parametrize("field", ["os_banner", "user", "password"])
def test_an_overlong_text_field_is_refused(field):
    document = as_dict(a_session())
    target = document["hosts"][0] if field == "os_banner" else document["hosts"][0]["accounts"][0]
    target[field] = "x" * 1000

    rejected(document, field)


def test_an_unknown_field_is_refused_at_every_level():
    for path in ([], ["hosts", 0], ["hosts", 0, "accounts", 0], ["hosts", 0, "services", 0]):
        document = as_dict(a_session())
        target = document
        for step in path:
            target = target[step]
        target["extra"] = 1

        rejected(document, "extra")


def test_a_missing_field_is_refused_at_every_level():
    for path, name in (
        ([], "preset_id"),
        (["hosts", 0], "fqdn"),
        (["hosts", 0, "accounts", 0], "password"),
        (["hosts", 0, "services", 0], "port"),
    ):
        document = as_dict(a_session())
        target = document
        for step in path:
            target = target[step]
        del target[name]

        rejected(document, name)


@pytest.mark.parametrize(
    "text",
    ["", "not json", "[]", "null", "17", '"x"', '{"key": ', "\x00"],
)
def test_a_file_that_is_not_a_json_object_is_refused(text):
    rejected(text, "")


def test_bytes_that_are_not_utf8_are_refused():
    rejected(b'{"key": "\xff\xfe"}', "")


def test_a_duplicate_key_in_the_json_is_refused():
    text = a_session().to_json().replace('"preset_id"', '"key": "other", "preset_id"')

    rejected(text, "duplicate")


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_a_non_finite_number_in_the_options_is_refused(constant):
    document = a_session().to_json().replace('"shares":["Public"]', f'"limit":{constant}')

    rejected(document, "")


def test_a_file_over_the_size_cap_is_refused_before_it_is_parsed():
    rejected(" " * (lan_session.MAX_SESSION_FILE_BYTES + 1), "too large")


def test_a_deeply_nested_option_is_refused_without_a_recursion_error():
    nested = "[" * 5000 + "]" * 5000
    text = a_session().to_json().replace('["Public"]', nested)

    rejected(text, "")


def test_options_must_be_json_values_with_string_keys_and_bounded_depth():
    document = as_dict(a_session())
    document["hosts"][0]["services"][0]["options"] = {"a": {"b": {"c": {"d": {"e": {"f": 1}}}}}}

    rejected(document, "options")


def test_options_must_be_an_object():
    document = as_dict(a_session())
    document["hosts"][0]["services"][0]["options"] = ["a"]

    rejected(document, "options")


def test_a_session_with_too_many_hosts_services_or_accounts_is_refused():
    base = as_dict(a_session())

    hosts = {
        **base,
        "hosts": [
            {**base["hosts"][0], "address": f"192.168.150.{n}", "fqdn": f"h{n}.corp.local"}
            for n in range(1, 60)
        ],
    }
    rejected(hosts, "hosts")

    services = as_dict(a_session())
    services["hosts"][0]["services"] = [
        {"kind": "smb", "port": 1000 + n, "options": {}} for n in range(40)
    ]
    rejected(services, "services")

    accounts = as_dict(a_session())
    accounts["hosts"][0]["accounts"] = [{"user": f"u{n}", "password": "p"} for n in range(40)]
    rejected(accounts, "accounts")


def test_a_session_without_hosts_is_refused():
    document = as_dict(a_session())
    document["hosts"] = []

    rejected(document, "hosts")


def test_two_hosts_may_not_share_an_address_or_a_name():
    clash = as_dict(a_session())
    clash["hosts"][1]["address"] = clash["hosts"][0]["address"]
    rejected(clash, "address")

    same_name = as_dict(a_session())
    same_name["hosts"][1]["fqdn"] = same_name["hosts"][0]["fqdn"]
    rejected(same_name, "fqdn")


def test_a_host_may_not_list_a_port_twice():
    document = as_dict(a_session())
    document["hosts"][0]["services"][1]["port"] = 445

    rejected(document, "port")


def test_the_guest_address_may_not_be_a_host_address():
    document = as_dict(a_session())
    document["guest_address"] = document["hosts"][0]["address"]

    rejected(document, "guest_address")


def test_constructing_an_invalid_session_directly_is_refused_too():
    with pytest.raises(SessionFormatError, match="key"):
        a_session(key="../x")


# --- the status file ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status",
    [SessionStatus("listening"), SessionStatus("closed"), SessionStatus("failed", "port in use")],
)
def test_a_status_survives_a_round_trip(status):
    assert SessionStatus.from_json(status.to_json()) == status


def test_a_failed_status_must_say_why_and_the_others_must_not():
    with pytest.raises(SessionFormatError, match="error"):
        SessionStatus("failed")
    with pytest.raises(SessionFormatError, match="error"):
        SessionStatus("listening", "oops")


def test_an_unknown_state_is_refused():
    with pytest.raises(SessionFormatError, match="state"):
        SessionStatus("opening")


def test_a_long_error_is_cut_instead_of_refused():
    status = SessionStatus("failed", "x" * 5000)

    assert len(status.error) <= lan_session.MAX_ERROR_LENGTH


def test_a_control_character_in_an_error_is_replaced():
    status = SessionStatus("failed", "bad\nvalue\x00")

    assert "\n" not in status.error
    assert "\x00" not in status.error


@pytest.mark.parametrize(
    "text",
    [
        '{"state": "listening", "extra": 1}',
        '{"state": "bogus", "error": null}',
        "[]",
        "",
        '{"error": null}',
        '{"state": "closed", "error": 5}',
    ],
)
def test_a_malformed_status_file_is_refused(text):
    with pytest.raises(SessionFormatError):
        SessionStatus.from_json(text)


# --- the directory layout -------------------------------------------------------------------------


def test_the_layout_puts_each_file_kind_in_its_own_directory(tmp_path):
    layout = Layout(tmp_path)

    assert layout.session_file("task-1") == tmp_path / "sessions" / "task-1.json"
    assert layout.status_file("task-1") == tmp_path / "status" / "task-1.json"
    assert layout.log_file("task-1") == tmp_path / "logs" / "task-1.jsonl"


def test_the_default_root_is_run_lan_sim():
    assert Layout().root == Path("/run/lan-sim")


@pytest.mark.parametrize("key", ["../x", "a/b", "", "..", "x" * 65, "a\n", "/etc/passwd"])
def test_a_key_that_could_leave_the_directory_never_becomes_a_path(tmp_path, key):
    layout = Layout(tmp_path)

    for build in (layout.session_file, layout.status_file, layout.log_file):
        with pytest.raises(SessionFormatError, match="key"):
            build(key)


def test_make_directories_creates_the_three_directories_and_is_repeatable(tmp_path):
    layout = Layout(tmp_path / "root")

    layout.make_directories()
    layout.make_directories()

    assert sorted(path.name for path in (tmp_path / "root").iterdir()) == [
        "logs",
        "sessions",
        "status",
    ]


def test_publishing_writes_the_session_file_and_retracting_removes_it(tmp_path):
    layout = Layout(tmp_path)
    spec = a_session()

    lan_session.publish_session(layout, spec)
    assert lan_session.read_session(layout, "task-17") == spec

    lan_session.retract_session(layout, "task-17")
    assert not layout.session_file("task-17").exists()
    lan_session.retract_session(layout, "task-17")


def test_publishing_clears_a_stale_status_of_the_same_key(tmp_path):
    layout = Layout(tmp_path)
    lan_session.write_status(layout, "task-17", SessionStatus("closed"))

    lan_session.publish_session(layout, a_session())

    assert lan_session.read_status(layout, "task-17") is None


def test_session_keys_lists_only_well_named_regular_files(tmp_path):
    layout = Layout(tmp_path)
    layout.make_directories()
    for name in (
        "task-1.json",
        "task-2.json",
        "bad name.json",
        "task-3.json.tmp",
        ".hidden.json",
        "-bad.json",
        "task-4.txt",
    ):
        (layout.sessions_dir / name).write_text("{}")
    (layout.sessions_dir / "task-5.json").symlink_to(layout.sessions_dir / "task-1.json")
    (layout.sessions_dir / "task-6.json").mkdir()

    assert lan_session.session_keys(layout) == ["task-1", "task-2"]


def test_status_keys_lists_the_status_files_by_the_same_rule(tmp_path):
    layout = Layout(tmp_path)
    lan_session.write_status(layout, "task-1", SessionStatus("closed"))
    lan_session.write_status(layout, "task-2", SessionStatus("listening"))
    (layout.status_dir / "bad name.json").write_text("{}")

    assert lan_session.status_keys(layout) == ["task-1", "task-2"]


def test_session_keys_of_a_missing_directory_is_empty(tmp_path):
    assert lan_session.session_keys(Layout(tmp_path / "nothing")) == []


def test_reading_an_oversized_session_file_is_refused(tmp_path):
    layout = Layout(tmp_path)
    layout.make_directories()
    layout.session_file("task-1").write_text(" " * (lan_session.MAX_SESSION_FILE_BYTES + 10))

    with pytest.raises(SessionFormatError, match="too large"):
        lan_session.read_session(layout, "task-1")


def test_a_session_file_whose_key_differs_from_its_name_is_refused(tmp_path):
    layout = Layout(tmp_path)
    layout.make_directories()
    layout.session_file("task-1").write_text(a_session(key="task-2").to_json())

    with pytest.raises(SessionFormatError, match="name"):
        lan_session.read_session(layout, "task-1")


def test_a_status_that_does_not_exist_reads_as_none(tmp_path):
    assert lan_session.read_status(Layout(tmp_path), "task-1") is None


# --- atomic write ---------------------------------------------------------------------------------


def test_an_atomic_write_leaves_the_whole_new_content_and_no_temporary_file(tmp_path):
    target = tmp_path / "x.json"
    lan_session.atomic_write(target, "old")

    lan_session.atomic_write(target, "new")

    assert target.read_text() == "new"
    assert [path.name for path in tmp_path.iterdir()] == ["x.json"]


def test_a_failed_atomic_write_keeps_the_old_content_and_cleans_up(tmp_path, monkeypatch):
    target = tmp_path / "x.json"
    lan_session.atomic_write(target, "old")

    def fail(*_arguments):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError, match="disk full"):
        lan_session.atomic_write(target, "new")

    assert target.read_text() == "old"
    assert [path.name for path in tmp_path.iterdir()] == ["x.json"]


def test_a_reader_never_sees_a_half_written_file(tmp_path):
    target = tmp_path / "x.json"
    payload = "x" * 200_000
    lan_session.atomic_write(target, payload)
    seen: set[int] = set()
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            seen.add(len(target.read_text()))

    thread = threading.Thread(target=reader)
    thread.start()
    for _ in range(40):
        lan_session.atomic_write(target, payload)
    stop.set()
    thread.join()

    assert seen == {len(payload)}


def test_a_temporary_file_never_matches_the_session_glob(tmp_path, monkeypatch):
    layout = Layout(tmp_path)
    layout.make_directories()
    seen: list[list[str]] = []
    original = os.replace

    def spy(source, destination):
        seen.append(lan_session.session_keys(layout))
        original(source, destination)

    monkeypatch.setattr(os, "replace", spy)
    lan_session.atomic_write(layout.session_file("task-1"), a_session(key="task-1").to_json())

    assert seen == [[]]


# --- waiting for the daemon -----------------------------------------------------------------------


class ManualTime:
    def __init__(self):
        self.now = 0.0

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_wait_for_status_returns_the_first_status_in_the_wanted_states(tmp_path):
    layout = Layout(tmp_path)
    lan_session.write_status(layout, "task-1", SessionStatus("failed", "port in use"))
    waiting = ManualTime()

    status = lan_session.wait_for_status(
        tmp_path,
        "task-1",
        {"listening", "failed"},
        timeout=5,
        clock=waiting.clock,
        sleep=waiting.sleep,
    )

    assert status == SessionStatus("failed", "port in use")


def test_wait_for_status_polls_until_the_status_appears(tmp_path):
    layout = Layout(tmp_path)
    waiting = ManualTime()

    def sleep(seconds: float) -> None:
        waiting.sleep(seconds)
        if waiting.now >= 1.0:
            lan_session.write_status(layout, "task-1", SessionStatus("listening"))

    status = lan_session.wait_for_status(
        tmp_path,
        "task-1",
        {"listening"},
        timeout=5,
        clock=waiting.clock,
        sleep=sleep,
    )

    assert status.state == "listening"
    assert waiting.now < 5


def test_wait_for_status_ignores_a_status_in_another_state(tmp_path):
    lan_session.write_status(Layout(tmp_path), "task-1", SessionStatus("closed"))
    waiting = ManualTime()

    with pytest.raises(TimeoutError, match="task-1"):
        lan_session.wait_for_status(
            tmp_path,
            "task-1",
            {"listening"},
            timeout=2,
            clock=waiting.clock,
            sleep=waiting.sleep,
        )

    assert waiting.now >= 2


def test_wait_for_status_keeps_waiting_through_an_unreadable_status_file(tmp_path):
    layout = Layout(tmp_path)
    layout.make_directories()
    layout.status_file("task-1").write_text("{not json")
    waiting = ManualTime()

    with pytest.raises(TimeoutError):
        lan_session.wait_for_status(
            tmp_path,
            "task-1",
            {"listening"},
            timeout=1,
            clock=waiting.clock,
            sleep=waiting.sleep,
        )


def test_wait_for_status_refuses_a_key_that_is_not_a_key(tmp_path):
    with pytest.raises(SessionFormatError, match="key"):
        lan_session.wait_for_status(tmp_path, "../x", {"listening"}, timeout=1)
