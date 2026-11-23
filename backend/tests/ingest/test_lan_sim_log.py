import json
from pathlib import Path

import pytest

from app.ingest import lan_sim_log
from app.ingest.lan_sim_log import ELLIPSIS, MAX_LINE_BYTES, LanLog, read_lan_log
from tests.ingest.lan_sim_cases import (
    STARTED,
    aggregate,
    file_write,
    login,
    record,
    service_request,
    session_end,
    share_access,
    write_log,
)


def read(tmp_path: Path, *lines: object) -> LanLog:
    return read_lan_log(write_log(tmp_path, lines))  # type: ignore[arg-type]


def test_a_missing_file_is_an_empty_log(tmp_path: Path) -> None:
    log = read_lan_log(tmp_path / "lansim" / "events.jsonl")

    assert log == LanLog([], None)


def test_the_records_of_a_session_are_read_in_file_order_with_their_line_numbers(
    tmp_path: Path,
) -> None:
    log = read(tmp_path, login(), share_access(), file_write(), service_request(), aggregate())

    assert [(r.index, r.type) for r in log.records] == [
        (0, "login-attempt"),
        (1, "share-access"),
        (2, "file-write"),
        (3, "service-request"),
        (4, "aggregate"),
    ]


def test_a_login_attempt_keeps_its_endpoints_host_and_typed_fields(tmp_path: Path) -> None:
    [parsed] = read(tmp_path, login(user="Administrator", success=True)).records

    assert parsed.time == STARTED.replace(second=1)
    assert (parsed.host, parsed.service) == ("fs01.corp.local", "smb")
    assert parsed.source is not None
    assert (parsed.source.ip, parsed.source.port) == (
        "192.168.150.10",
        50123,
    )
    assert parsed.destination is not None
    assert (parsed.destination.ip, parsed.destination.port) == (
        "192.168.150.201",
        445,
    )
    assert parsed.fields == {
        "user": "Administrator",
        "domain": "CORP",
        "mechanism": "ntlm",
        "secret": "Password1",
        "success": True,
    }


def test_a_connection_record_is_not_kept_because_the_pcap_already_has_the_flow(
    tmp_path: Path,
) -> None:
    log = read(tmp_path, record("connection", bytes_in=1, bytes_out=2, duration_ms=3), login())

    assert [r.type for r in log.records] == ["login-attempt"]


def test_the_session_end_is_kept_apart_with_the_truncation_flag(tmp_path: Path) -> None:
    log = read(tmp_path, login(), session_end(log_truncated=True))

    assert [r.type for r in log.records] == ["login-attempt"]
    assert log.session_end is not None
    assert log.session_end.log_truncated is True
    assert log.session_end.counters["events_logged"] == 3


def test_a_log_reopened_under_the_same_key_is_truncated_if_any_of_its_ends_says_so(
    tmp_path: Path,
) -> None:
    log = read(tmp_path, session_end(log_truncated=True), login(), session_end())

    assert log.session_end is not None
    assert log.session_end.log_truncated is True


def test_a_truncated_last_line_is_skipped_and_the_records_before_it_are_kept(
    tmp_path: Path,
) -> None:
    whole = json.dumps(login(user="second"))
    log = read(tmp_path, login(user="first"), whole[: len(whole) // 2])

    assert [r.fields["user"] for r in log.records] == ["first"]


def test_a_last_record_without_its_newline_is_still_read(tmp_path: Path) -> None:
    path = write_log(tmp_path, [login(user="first")])
    path.write_bytes(path.read_bytes() + json.dumps(login(user="second")).encode())

    assert [r.fields["user"] for r in read_lan_log(path).records] == ["first", "second"]


@pytest.mark.parametrize(
    "junk",
    [
        "not json",
        "[1, 2]",
        "42",
        '"text"',
        "null",
        "",
        "   ",
        '{"type": "login-attempt"',
        "{" * 100000,
    ],
)
def test_a_line_that_is_not_a_json_object_is_skipped_and_the_rest_kept(
    tmp_path: Path, junk: str
) -> None:
    log = read(tmp_path, login(user="before"), junk, login(user="after"))

    assert [r.fields["user"] for r in log.records] == ["before", "after"]
    assert [r.index for r in log.records] == [0, 2]


def test_a_json_constant_python_would_accept_is_refused(tmp_path: Path) -> None:
    log = read(tmp_path, '{"type": "aggregate", "count": NaN}', login())

    assert [r.type for r in log.records] == ["login-attempt"]


def test_an_unknown_type_is_skipped(tmp_path: Path) -> None:
    log = read(tmp_path, record("teleport"), login())

    assert [r.type for r in log.records] == ["login-attempt"]


@pytest.mark.parametrize(
    "broken",
    [
        login(success="yes"),
        login(user=5),
        login(user=None, secret=["a"]),
        file_write(size="big"),
        file_write(size=-1),
        file_write(size=True),
        file_write(sha256="nothex"),
        record("share-access", share=1),
        login(time="yesterday"),
        login(time=None),
        login(time="2026-11-23T12:00:00"),
        {**login(), "src": {"ip": "not-an-ip", "port": 1}},
        {**login(), "dst": {"ip": "192.168.150.201", "port": 70000}},
        {**login(), "dst": "192.168.150.201:445"},
        {**login(), "src": None},
        login(host=None),
        login(service=7),
    ],
)
def test_a_record_with_a_wrong_typed_or_missing_field_is_skipped_and_the_rest_kept(
    tmp_path: Path, broken: dict[str, object]
) -> None:
    log = read(tmp_path, login(user="before"), broken, login(user="after"))

    assert [r.fields["user"] for r in log.records] == ["before", "after"]


def test_a_missing_optional_text_becomes_empty(tmp_path: Path) -> None:
    [parsed] = read(tmp_path, record("share-access", share="C$", operation="list")).records

    assert parsed.fields["path"] == ""


def test_control_and_format_characters_are_removed_from_every_string(tmp_path: Path) -> None:
    hostile = "admin\u202e\u0000\u200b\n\r\t\x1b[31mx\u2028y\ud800z"

    [parsed] = read(tmp_path, login(user=hostile, secret=hostile, host="fs01.corp.local")).records

    assert parsed.fields["user"] == "admin[31mx" + "y" + "\ufffd" + "z"
    assert parsed.fields["secret"] == parsed.fields["user"]


def test_a_string_over_its_cap_is_cut_with_a_final_ellipsis(tmp_path: Path) -> None:
    [parsed] = read(tmp_path, login(user="u" * 5000, secret="s" * 5000)).records

    assert len(parsed.fields["user"]) == 256
    assert parsed.fields["user"].endswith(ELLIPSIS)
    assert len(parsed.fields["secret"]) == 4096
    assert parsed.fields["secret"].endswith(ELLIPSIS)


def test_a_ten_megabyte_string_costs_its_line_and_nothing_else(tmp_path: Path) -> None:
    giant = login(user="x" * (10 * 1024 * 1024))

    log = read(tmp_path, login(user="before"), giant, login(user="after"))

    assert [r.fields["user"] for r in log.records] == ["before", "after"]
    assert [r.index for r in log.records] == [0, 2]


def test_a_line_just_under_the_limit_is_read(tmp_path: Path) -> None:
    line = json.dumps(login(user="padded", secret="s" * 60000))
    assert len(line) < MAX_LINE_BYTES

    assert len(read(tmp_path, line).records) == 1


def test_bytes_that_are_not_utf8_become_replacement_characters(tmp_path: Path) -> None:
    line = json.dumps(login(user="USER")).encode().replace(b"USER", b"\xff\xfeab")

    [parsed] = read(tmp_path, line).records

    assert parsed.fields["user"] == "\ufffd\ufffdab"


def test_reading_stops_at_the_size_limit_and_keeps_what_came_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lines = [login(user=f"u{n}") for n in range(50)]
    one_line = len(json.dumps(lines[0])) + 1
    monkeypatch.setattr(lan_sim_log, "MAX_LOG_BYTES", one_line * 10)

    log = read(tmp_path, *lines)

    assert 9 <= len(log.records) <= 10


def test_an_aggregate_keeps_its_counts_times_and_distinct_users_and_secrets(
    tmp_path: Path,
) -> None:
    [parsed] = read(tmp_path, aggregate()).records

    assert parsed.source is None
    assert parsed.destination is None
    assert parsed.fields["count"] == 9800
    assert parsed.fields["by_type"] == {"connection": 4900, "login-attempt": 4900}
    assert parsed.fields["users"] == ["admin", "root"]
    assert parsed.fields["secrets"] == ["Password1"]
    assert parsed.fields["first_time"] == STARTED.replace(second=2)


def test_an_aggregate_is_held_to_the_lists_and_caps_of_the_schema(tmp_path: Path) -> None:
    flood = aggregate(
        users=[f"user{n}" * 30 for n in range(80)],
        secrets=[f"secret{n}" * 400 for n in range(9)],
        by_type={f"type{n}": n for n in range(100)},
    )

    [parsed] = read(tmp_path, flood).records

    assert len(parsed.fields["users"]) == 50
    assert all(len(u) <= 64 for u in parsed.fields["users"])
    assert len(parsed.fields["secrets"]) == 5
    assert all(len(s) <= 1024 for s in parsed.fields["secrets"])
    assert len(parsed.fields["by_type"]) <= 16


@pytest.mark.parametrize(
    "broken",
    [
        aggregate(count="many"),
        aggregate(count=-3),
        aggregate(users="admin"),
        aggregate(users=[1, 2]),
        aggregate(by_type=[1]),
        aggregate(by_type={"a": "b"}),
        aggregate(first_time="never"),
    ],
)
def test_an_aggregate_with_a_wrong_typed_field_is_skipped(
    tmp_path: Path, broken: dict[str, object]
) -> None:
    assert read(tmp_path, broken, login()).records[0].type == "login-attempt"


def test_the_raw_record_is_the_cleaned_one_and_serialises(tmp_path: Path) -> None:
    [parsed] = read(tmp_path, login(user="a\u202eb")).records

    assert parsed.raw["user"] == "ab"
    assert parsed.raw["type"] == "login-attempt"
    assert json.dumps(parsed.raw)
