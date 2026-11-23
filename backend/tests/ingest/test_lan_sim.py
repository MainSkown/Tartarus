import json
from pathlib import Path
from typing import Any

import pytest

from app.ingest.capemon import CapemonNormalizer
from app.ingest.ecs import event_id
from app.ingest.lan_sim import LanSimNormalizer
from app.ingest.protocol import Normalizer
from tests.ingest.contract import check_normalizer_contract
from tests.ingest.lan_sim_cases import (
    ANALYSIS_ID,
    DOMAIN_CONTROLLER,
    FILE_SERVER,
    GUEST,
    aggregate,
    at,
    context_of,
    file_write,
    login,
    record,
    service_request,
    session_end,
    share_access,
    write_log,
)
from tests.ingest.reports import call, process, report_of

Event = dict[str, Any]
NO_REPORT: dict[str, Any] = {}


def normalise(
    tmp_path: Path, records: list[Any], report: dict[str, Any] | None = None, **context: Any
) -> list[Event]:
    write_log(tmp_path, records)
    return list(LanSimNormalizer().normalise(report or NO_REPORT, context_of(tmp_path, **context)))


def stamp_of(seconds: float) -> str:
    return at(seconds).strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]


def connect(address: str, port: int, seconds: float) -> dict[str, Any]:
    return call("connect", {"ip": address, "port": str(port)}, timestamp=stamp_of(seconds))


def report_of_process(pid: int, *calls: dict[str, Any]) -> dict[str, Any]:
    return report_of(process(pid, list(calls), name=f"p{pid}.exe"))


def actions(events: list[Event]) -> list[str]:
    return [event["event"]["action"] for event in events]


def test_the_source_is_lan_sim() -> None:
    assert LanSimNormalizer().source == "lan-sim"
    assert isinstance(LanSimNormalizer(), Normalizer)


# --- nothing to do ---------------------------------------------------------------------------


def test_without_fake_hosts_it_yields_nothing_whatever_the_log_holds(tmp_path: Path) -> None:
    write_log(tmp_path, [login(), share_access(), aggregate()])
    report = report_of_process(
        7, *(connect(a, 445, n) for n, a in enumerate(context_of(None).lan_hosts))
    )

    assert list(LanSimNormalizer().normalise(report, context_of(tmp_path, {}))) == []


def test_without_a_log_file_or_a_folder_there_are_no_log_events(tmp_path: Path) -> None:
    assert list(LanSimNormalizer().normalise(NO_REPORT, context_of(tmp_path))) == []
    assert list(LanSimNormalizer().normalise(NO_REPORT, context_of(None))) == []


def test_an_empty_log_yields_nothing(tmp_path: Path) -> None:
    assert normalise(tmp_path, []) == []


# --- the log's events ------------------------------------------------------------------------


def test_every_event_carries_both_endpoints_the_host_name_and_the_lan_fields(
    tmp_path: Path,
) -> None:
    events = normalise(tmp_path, [login(), share_access(), file_write(), service_request(port=445)])

    assert len(events) == 4
    for event in events:
        assert event["source"] == {"ip": GUEST, "port": 50123}
        assert event["destination"] == {"ip": FILE_SERVER, "port": 445, "domain": "fs01.corp.local"}
        assert event["network"] == {"transport": "tcp", "protocol": "smb"}
        assert event["tartarus"]["lane"] == "network"
        assert event["tartarus"]["lan"]["simulated"] is True
        assert event["tartarus"]["lan"]["host"] == "fs01.corp.local"
        assert event["tartarus"]["lan"]["role"] == "file-server"
        assert event["tartarus"]["lan"]["preset"] == "small-office"
        assert event["tartarus"]["lan"]["service"] == "smb"
        assert event["event"]["kind"] == "event"
        assert event["event"]["module"] == "lan-sim"
        assert event["event"]["dataset"] == "lan-sim.log"
        assert event["event"]["severity"] == 0
        assert "\n" not in event["tartarus"]["summary"]


def test_a_failed_login_attempt_is_an_authentication_event_with_the_credential(
    tmp_path: Path,
) -> None:
    [event] = normalise(tmp_path, [login(user="Administrator", success=False)])

    assert event["event"]["action"] == "lan-login-attempt"
    assert event["event"]["category"] == ["network", "authentication"]
    assert event["event"]["type"] == ["start"]
    assert event["event"]["outcome"] == "failure"
    assert event["user"] == {"name": "Administrator", "domain": "CORP"}
    assert event["tartarus"]["lan"]["mechanism"] == "ntlm"
    assert event["tartarus"]["lan"]["credential"] == "Password1"
    assert "Password1" not in event["tartarus"]["summary"]
    assert event["@timestamp"] == "2026-11-23T12:00:01.000Z"


def test_a_successful_login_attempt_has_the_success_outcome(tmp_path: Path) -> None:
    [event] = normalise(tmp_path, [login(success=True)])

    assert event["event"]["outcome"] == "success"


def test_an_anonymous_login_has_no_user_name_and_no_credential(tmp_path: Path) -> None:
    [event] = normalise(tmp_path, [login(user="", domain="", secret="")])

    assert "user" not in event
    assert "credential" not in event["tartarus"]["lan"]


@pytest.mark.parametrize(
    ("operation", "expected_type"),
    [
        ("tree-connect", "access"),
        ("open", "access"),
        ("read", "access"),
        ("list", "access"),
        ("create", "creation"),
        ("delete", "deletion"),
        ("rename", "change"),
        ("write", "change"),
        ("something-new", "access"),
    ],
)
def test_a_share_access_names_the_operation_and_maps_it_to_an_ecs_type(
    tmp_path: Path, operation: str, expected_type: str
) -> None:
    [event] = normalise(tmp_path, [share_access(operation=operation, path="\\dir\\a.txt")])

    assert event["event"]["action"] == "lan-share-access"
    assert event["event"]["category"] == ["network", "file"]
    assert event["event"]["type"] == [expected_type]
    assert event["tartarus"]["lan"]["request"] == operation
    assert event["tartarus"]["lan"]["share"] == "ADMIN$"
    assert event["file"] == {"path": "\\dir\\a.txt", "name": "a.txt", "extension": "txt"}


def test_a_share_access_at_the_share_root_has_no_file(tmp_path: Path) -> None:
    [event] = normalise(tmp_path, [share_access(operation="tree-connect", path="")])

    assert "file" not in event


def test_a_rename_gives_the_old_path_and_the_target_path(tmp_path: Path) -> None:
    [event] = normalise(tmp_path, [share_access(operation="rename", path="\\a.tmp -> \\a.exe")])

    assert event["file"]["path"] == "\\a.tmp"
    assert event["file"]["target_path"] == "\\a.exe"


def test_a_file_write_carries_path_size_and_hash(tmp_path: Path) -> None:
    [event] = normalise(tmp_path, [file_write()])

    assert event["event"]["action"] == "lan-file-write"
    assert event["event"]["category"] == ["network", "file"]
    assert event["event"]["type"] == ["change"]
    assert event["file"] == {
        "path": "\\evil.exe",
        "name": "evil.exe",
        "extension": "exe",
        "size": 61440,
        "hash": {"sha256": "ab" * 32},
    }
    assert event["tartarus"]["lan"]["share"] == "ADMIN$"
    assert "61440" in event["tartarus"]["summary"]


def test_a_file_write_whose_stored_copy_is_incomplete_says_so_in_its_summary(
    tmp_path: Path,
) -> None:
    [event] = normalise(tmp_path, [file_write(truncated=True)])

    assert "truncated" in event["tartarus"]["summary"]


def test_a_service_request_has_the_request_name_and_its_detail(tmp_path: Path) -> None:
    [event] = normalise(tmp_path, [service_request()])

    assert event["event"]["action"] == "lan-service-request"
    assert event["event"]["category"] == ["network"]
    assert event["event"]["type"] == ["protocol"]
    assert event["tartarus"]["lan"]["request"] == "svcctl CreateService"
    assert event["tartarus"]["lan"]["detail"] == "evil, C:\\Windows\\evil.exe"
    assert "process" not in event
    assert "command_line" not in str(event.get("process", ""))
    assert "svcctl CreateService" in event["tartarus"]["summary"]


def test_a_request_of_another_service_names_it(tmp_path: Path) -> None:
    [event] = normalise(
        tmp_path,
        [login(host="dc01.corp.local", service="ldap", port=389, mechanism="ldap-simple")],
    )

    assert event["network"]["protocol"] == "ldap"
    assert event["tartarus"]["lan"]["role"] == "domain-controller"
    assert event["destination"]["ip"] == DOMAIN_CONTROLLER


def test_a_host_the_preset_does_not_know_is_still_simulated_without_role_or_preset(
    tmp_path: Path,
) -> None:
    record_of_unknown = {**login(), "dst": {"ip": "192.168.150.240", "port": 445}}

    [event] = normalise(tmp_path, [record_of_unknown])

    assert event["tartarus"]["lan"] == {
        "simulated": True,
        "host": "fs01.corp.local",
        "service": "smb",
        "mechanism": "ntlm",
        "credential": "Password1",
    }


def test_the_raw_record_is_kept_for_the_detail_view(tmp_path: Path) -> None:
    [event] = normalise(tmp_path, [login(user="Administrator")])

    assert event["tartarus"]["raw"]["user"] == "Administrator"
    assert event["tartarus"]["raw"]["type"] == "login-attempt"


def test_ids_come_from_the_line_number_so_a_skipped_line_moves_nothing(tmp_path: Path) -> None:
    events = normalise(tmp_path, [login(user="a"), "garbage", login(user="b")])

    assert [e["event"]["id"] for e in events] == [
        event_id(ANALYSIS_ID, "lan-sim", "events", 0),
        event_id(ANALYSIS_ID, "lan-sim", "events", 2),
    ]


def test_a_connection_record_is_not_an_event_because_the_pcap_has_the_flow(
    tmp_path: Path,
) -> None:
    events = normalise(tmp_path, [record("connection", bytes_in=1, bytes_out=1, duration_ms=1)])

    assert events == []


# --- a flood the daemon already aggregated ------------------------------------------------------


def test_an_aggregate_becomes_one_event_with_the_counts_so_a_flood_is_not_lost(
    tmp_path: Path,
) -> None:
    [event] = normalise(tmp_path, [aggregate()])

    assert event["event"]["action"] == "lan-aggregate"
    assert event["event"]["category"] == ["network"]
    assert event["event"]["type"] == ["info"]
    assert event["tartarus"]["lan"]["count"] == 9800
    assert event["tartarus"]["lan"]["host"] == "fs01.corp.local"
    assert event["tartarus"]["lan"]["service"] == "smb"
    assert event["user"] == {"name": ["admin", "root"]}
    assert event["tartarus"]["lan"]["credential"] == ["Password1"]
    assert event["destination"] == {"ip": FILE_SERVER, "domain": "fs01.corp.local"}
    assert "9800" in event["tartarus"]["summary"]
    assert event["tartarus"]["raw"]["by_type"] == {"connection": 4900, "login-attempt": 4900}


def test_an_aggregate_is_placed_where_the_flood_began(tmp_path: Path) -> None:
    [event] = normalise(tmp_path, [aggregate()])

    assert event["@timestamp"] == "2026-11-23T12:00:02.000Z"


def test_an_aggregate_without_users_or_secrets_has_neither_field(tmp_path: Path) -> None:
    [event] = normalise(tmp_path, [aggregate(users=[], secrets=[])])

    assert "user" not in event
    assert "credential" not in event["tartarus"]["lan"]


def test_the_session_end_is_no_event_but_is_kept_on_the_normaliser(tmp_path: Path) -> None:
    write_log(tmp_path, [login(), session_end(log_truncated=True)])
    normalizer = LanSimNormalizer()

    events = list(normalizer.normalise(NO_REPORT, context_of(tmp_path)))

    assert len(events) == 1
    assert normalizer.session_end is not None
    assert normalizer.session_end.log_truncated is True


def test_the_session_end_of_an_earlier_ingest_is_not_kept(tmp_path: Path) -> None:
    write_log(tmp_path, [session_end(log_truncated=True)])
    normalizer = LanSimNormalizer()
    list(normalizer.normalise(NO_REPORT, context_of(tmp_path)))

    list(normalizer.normalise(NO_REPORT, context_of(None)))

    assert normalizer.session_end is None


# --- a log that is damaged or hostile ----------------------------------------------------------


def test_a_truncated_last_line_a_garbage_line_and_an_unknown_type_cost_only_themselves(
    tmp_path: Path,
) -> None:
    whole = json.dumps(login(user="cut"))
    events = normalise(
        tmp_path,
        [
            login(user="first"),
            "\x00\xff garbage",
            record("teleport"),
            login(user="second"),
            whole[:40],
        ],
    )

    assert [e["user"]["name"] for e in events] == ["first", "second"]


def test_a_hostile_user_name_reaches_the_event_without_control_or_format_characters(
    tmp_path: Path,
) -> None:
    hostile = "<script>alert(1)</script>\u202e\u0000\n\x1b[2Jadmin"

    [event] = normalise(tmp_path, [login(user=hostile)])

    assert event["user"]["name"] == "<script>alert(1)</script>[2Jadmin"
    assert "\n" not in event["tartarus"]["summary"]
    assert "\u202e" not in event["tartarus"]["summary"]
    assert json.loads(json.dumps(event)) == event


def test_a_ten_megabyte_user_name_costs_its_record_and_nothing_else(tmp_path: Path) -> None:
    events = normalise(
        tmp_path,
        [login(user="before"), login(user="x" * (10 * 1024 * 1024)), login(user="after")],
    )

    assert [e["user"]["name"] for e in events] == ["before", "after"]


def test_every_string_that_reaches_an_event_is_capped_whatever_the_log_says(
    tmp_path: Path,
) -> None:
    [event] = normalise(tmp_path, [service_request(detail="d" * 20000, name="n" * 20000)])

    assert len(event["tartarus"]["lan"]["detail"]) == 1024
    assert len(event["tartarus"]["lan"]["request"]) == 256
    assert len(event["tartarus"]["summary"]) <= 300


# --- who did it ---------------------------------------------------------------------------------


def test_an_event_takes_the_process_that_connected_to_the_endpoint(tmp_path: Path) -> None:
    report = report_of_process(7, connect(FILE_SERVER, 445, 0.5))
    [capemon_connect] = [
        e
        for e in CapemonNormalizer().normalise(report, context_of(tmp_path))
        if e["event"]["action"] == "network-connection"
    ]

    [event] = normalise(tmp_path, [login()], report)

    assert event["process"]["pid"] == 7
    assert event["process"]["name"] == "p7.exe"
    assert "thread" not in event["process"]
    assert event["related"]["events"] == [capemon_connect["event"]["id"]]


def test_without_a_capemon_connect_to_the_endpoint_the_event_has_no_process(
    tmp_path: Path,
) -> None:
    report = report_of_process(7, connect(DOMAIN_CONTROLLER, 445, 0.5))

    [event] = normalise(tmp_path, [login()], report)

    assert "process" not in event
    assert "related" not in event


def test_two_processes_that_connected_to_the_endpoint_leave_the_event_unattributed(
    tmp_path: Path,
) -> None:
    report = report_of(
        process(7, [connect(FILE_SERVER, 445, 0.5)], name="a.exe"),
        process(8, [connect(FILE_SERVER, 445, 0.6)], name="b.exe"),
    )

    [event] = normalise(tmp_path, [login()], report)

    assert "process" not in event


def test_an_event_of_another_port_of_the_same_host_is_not_attributed_by_a_connect_elsewhere(
    tmp_path: Path,
) -> None:
    report = report_of_process(7, connect(FILE_SERVER, 3389, 0.5))

    [event] = normalise(tmp_path, [login()], report)

    assert "process" not in event


# --- the whole run ------------------------------------------------------------------------------


def test_the_contract_holds_on_a_session(tmp_path: Path) -> None:
    write_log(
        tmp_path,
        [login(), share_access(), file_write(), service_request(), aggregate(), session_end()],
    )
    report = report_of_process(7, *(connect(FILE_SERVER, 445, n) for n in range(6)))

    events = check_normalizer_contract(LanSimNormalizer(), report, context_of(tmp_path))

    assert {"lan-login-attempt", "lan-aggregate"} <= set(actions(events))


def test_the_events_of_the_log_come_in_file_order_with_increasing_sequence(
    tmp_path: Path,
) -> None:
    events = normalise(tmp_path, [login(), share_access(), file_write()])

    assert [e["event"]["sequence"] for e in events] == [0, 1, 2]
    assert actions(events) == ["lan-login-attempt", "lan-share-access", "lan-file-write"]
