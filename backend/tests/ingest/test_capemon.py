import copy
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.ingest.capemon import CapemonNormalizer, api_event_id, call_lane, read_calls
from app.ingest.protocol import IngestContext
from tests.ingest.reports import call, first_seen_at, process, report_of, report_with

Event = dict[str, Any]
CHILD_PATH = "C:\\Users\\Analyst\\AppData\\Local\\Temp\\tartarus-benign.txt"


def normalise(report: dict[str, Any], context: IngestContext) -> list[Event]:
    return list(CapemonNormalizer().normalise(report, context))


def actions(events: list[Event]) -> list[str]:
    return [event["event"]["action"] for event in events]


def derived_of(events: list[Event]) -> list[Event]:
    return [event for event in events if event["event"]["action"] != "api-call"]


def only_derived(report: dict[str, Any], context: IngestContext) -> Event:
    derived = derived_of(normalise(report, context))
    assert len(derived) == 1, actions(derived)
    return derived[0]


@pytest.fixture
def events(full_report: dict[str, Any], context: IngestContext) -> list[Event]:
    return normalise(full_report, context)


def test_source_is_capemon() -> None:
    assert CapemonNormalizer().source == "capemon"


# --- the real report -----------------------------------------------------------------------


def test_every_call_becomes_an_api_event(events: list[Event]) -> None:
    api_events = [event for event in events if event["tartarus"]["lane"] == "api"]
    assert len(api_events) == 471
    assert {event["event"]["action"] for event in api_events} == {"api-call"}


def test_event_counts_per_lane(events: list[Event]) -> None:
    lanes = Counter(event["tartarus"]["lane"] for event in events)
    assert lanes == {"api": 471, "process": 3, "file": 2, "registry": 2, "network": 1}


def test_derived_events_by_action(events: list[Event]) -> None:
    assert Counter(actions(derived_of(events))) == {
        "process-created": 1,
        "process-terminated": 2,
        "file-created": 1,
        "file-written": 1,
        "reg-key-created": 1,
        "reg-value-set": 1,
        "dns-query": 1,
    }


def test_event_ids_are_unique_and_the_same_on_every_run(
    full_report: dict[str, Any], context: IngestContext, events: list[Event]
) -> None:
    ids = [event["event"]["id"] for event in events]
    assert len(set(ids)) == len(ids) == 479
    assert ids == [event["event"]["id"] for event in normalise(full_report, context)]


def test_the_analysis_id_is_part_of_every_event_id(
    full_report: dict[str, Any], events: list[Event]
) -> None:
    other = IngestContext(analysis_id=7, started_at=datetime(2026, 10, 13, tzinfo=UTC))
    other_ids = {event["event"]["id"] for event in normalise(full_report, other)}
    assert other_ids.isdisjoint(event["event"]["id"] for event in events)


def test_process_created_is_derived_once_although_two_calls_create_the_child(
    full_report: dict[str, Any], events: list[Event]
) -> None:
    creating_calls = [
        event
        for event in events
        if event["event"]["action"] == "api-call"
        and event["api"]["name"] in {"NtCreateUserProcess", "CreateProcessInternalW"}
    ]
    assert len(creating_calls) == 2
    created = [event for event in events if event["event"]["action"] == "process-created"]
    assert len(created) == 1
    process = created[0]["process"]
    assert (process["pid"], process["parent"]["pid"]) == (9632, 10116)
    assert process["command_line"] == "cmd.exe /c ver"
    assert process["name"] == "cmd.exe"
    assert process["executable"] == "C:\\Windows\\System32\\cmd.exe"
    assert process["parent"]["name"] == "benign.exe"


def test_process_created_links_to_the_earliest_creating_call(events: list[Event]) -> None:
    created = next(event for event in events if event["event"]["action"] == "process-created")
    [linked] = created["related"]["events"]
    api_event = next(event for event in events if event["event"]["id"] == linked)
    assert api_event["api"]["name"] == "NtCreateUserProcess"


def test_each_process_terminates_once(events: list[Event]) -> None:
    terminated = [event for event in events if event["event"]["action"] == "process-terminated"]
    assert sorted(event["process"]["pid"] for event in terminated) == [9632, 10116]


def test_file_written_carries_the_real_path_not_the_console_device(events: list[Event]) -> None:
    written = [event for event in events if event["event"]["action"] == "file-written"]
    assert [event["file"]["path"] for event in written] == [CHILD_PATH]
    assert written[0]["file"]["name"] == "tartarus-benign.txt"
    assert written[0]["file"]["extension"] == "txt"
    assert written[0]["tartarus"]["summary"] == f"benign.exe wrote {CHILD_PATH}"


def test_file_created_comes_from_the_call_that_found_no_file_before(events: list[Event]) -> None:
    [created] = [event for event in events if event["event"]["action"] == "file-created"]
    assert created["file"]["path"] == CHILD_PATH


def test_registry_events_carry_hive_key_and_value(events: list[Event]) -> None:
    [key] = [event for event in events if event["event"]["action"] == "reg-key-created"]
    assert key["registry"] == {
        "path": "HKEY_CURRENT_USER\\Software\\Tartarus",
        "hive": "HKCU",
        "key": "Software\\Tartarus",
    }
    [value] = [event for event in events if event["event"]["action"] == "reg-value-set"]
    assert value["registry"] == {
        "path": "HKEY_CURRENT_USER\\Software\\Tartarus\\SelfTest",
        "hive": "HKCU",
        "key": "Software\\Tartarus",
        "value": "SelfTest",
        "data": {"type": "REG_SZ", "strings": ["benign"]},
    }


def test_dns_query_carries_the_name(events: list[Event]) -> None:
    [query] = [event for event in events if event["event"]["action"] == "dns-query"]
    assert query["dns"] == {"question": {"name": "tartarus-selftest.example"}}
    assert query["tartarus"]["lane"] == "network"


def test_every_derived_event_points_at_an_existing_api_event_of_the_same_call(
    events: list[Event],
) -> None:
    api_by_id = {
        event["event"]["id"]: event for event in events if event["event"]["action"] == "api-call"
    }
    for event in derived_of(events):
        [linked] = event["related"]["events"]
        assert api_by_id[linked]["tartarus"]["raw"] is event["tartarus"]["raw"]


def test_api_event_carries_the_call(events: list[Event]) -> None:
    event = next(
        e
        for e in events
        if e["event"]["action"] == "api-call"
        and e["api"]["name"] == "NtWriteFile"
        and e["api"]["arguments"]["HandleName"] == CHILD_PATH
    )
    assert event["api"] == {
        "name": "NtWriteFile",
        "category": "filesystem",
        "status": True,
        "return_value": "0x00000000",
        "arguments": {
            "FileHandle": "0x0000020c",
            "HandleName": CHILD_PATH,
            "Buffer": "tartarus benign sample was here\r\n",
            "Length": "33",
        },
        "repeated": 0,
    }
    assert event["tartarus"]["raw"]["id"] == 45
    assert event["tartarus"]["lane"] == "api"
    assert event["event"]["dataset"] == "capemon.api"
    assert event["event"]["module"] == "capemon"
    assert event["event"]["category"] == ["file"]


def test_api_events_carry_the_owning_process(events: list[Event]) -> None:
    api_events = [e for e in events if e["event"]["action"] == "api-call"]
    child = next(e for e in api_events if e["process"]["pid"] == 9632)
    assert child["process"]["command_line"] == "cmd.exe /c ver"
    assert child["process"]["parent"] == {"pid": 10116, "name": "benign.exe"}
    assert child["process"]["entity_id"] == "6:9632@2026-10-13T12:12:41.613Z"
    assert child["process"]["start"] == "2026-10-13T12:12:41.613Z"
    parent = next(e for e in api_events if e["process"]["pid"] == 10116)
    assert (
        parent["process"]["command_line"]
        == '"C:\\Users\\Analyst\\AppData\\Local\\Temp\\benign.exe"'
    )
    assert parent["process"]["parent"] == {"pid": 4336}
    assert isinstance(parent["process"]["thread"]["id"], int)


def test_timestamps_are_the_guest_clock_shifted_to_utc(events: list[Event]) -> None:
    first = events[0]
    assert first["@timestamp"] == "2026-10-13T12:12:41.383Z"
    assert first["tartarus"]["raw"]["timestamp"] == "2026-10-13 10:12:41,383"


def analysis_window(report: dict[str, Any]) -> tuple[datetime, datetime]:
    def utc(text: str) -> datetime:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)

    return (
        utc(report["info"]["started"]) - timedelta(seconds=5),
        utc(report["info"]["ended"]) + timedelta(seconds=60),
    )


def test_every_event_falls_inside_the_analysis_window(
    full_report: dict[str, Any], events: list[Event]
) -> None:
    start, end = analysis_window(full_report)
    for event in events:
        assert start <= datetime.fromisoformat(event["@timestamp"]) <= end, event["@timestamp"]


def test_without_the_calibration_every_event_would_precede_the_window(
    full_report: dict[str, Any], context: IngestContext
) -> None:
    uncalibrated = copy.deepcopy(full_report)
    del uncalibrated["info"]
    start, _ = analysis_window(full_report)
    moments = [
        datetime.fromisoformat(event["@timestamp"]) for event in normalise(uncalibrated, context)
    ]
    assert max(moments) < start - timedelta(hours=1, minutes=59)


def test_the_winter_offset_of_one_hour_is_found_not_assumed(
    full_report: dict[str, Any], context: IngestContext
) -> None:
    winter = copy.deepcopy(full_report)
    winter["info"]["started"] = "2026-10-13 11:12:18"
    shifted = datetime.fromisoformat(normalise(winter, context)[0]["@timestamp"])
    assert shifted == datetime(2026, 10, 13, 11, 12, 41, 383000, tzinfo=UTC)


def test_the_process_start_is_calibrated_like_the_calls(
    full_report: dict[str, Any], events: list[Event]
) -> None:
    assert full_report["behavior"]["processes"][0]["first_seen"] == "2026-10-13 10:12:41,164"
    parent = next(e for e in events if e["process"]["pid"] == 10116)
    assert parent["process"]["start"] == "2026-10-13T12:12:41.164Z"


def test_sequence_follows_timestamp_then_call_id(events: list[Event]) -> None:
    assert [e["event"]["sequence"] for e in events] == list(range(len(events)))
    api_keys = [
        (e["@timestamp"], e["tartarus"]["raw"]["id"])
        for e in events
        if e["event"]["action"] == "api-call"
    ]
    assert api_keys == sorted(api_keys)
    timestamps = [e["@timestamp"] for e in events]
    assert timestamps == sorted(timestamps)


def test_derived_event_directly_follows_its_api_event(events: list[Event]) -> None:
    for position, event in enumerate(events):
        if event["event"]["action"] != "api-call":
            assert events[position - 1]["event"]["id"] == event["related"]["events"][0]


# --- what other normalisers read from capemon ---------------------------------------------


def test_api_event_id_is_the_id_the_normaliser_gave_the_call(
    full_report: dict[str, Any], context: IngestContext, events: list[Event]
) -> None:
    calls = read_calls(full_report, context)
    api_ids = [e["event"]["id"] for e in events if e["event"]["action"] == "api-call"]
    assert [api_event_id(context.analysis_id, call) for call in calls] == api_ids


def test_read_calls_returns_the_calibrated_calls_in_sequence_order(
    full_report: dict[str, Any], context: IngestContext
) -> None:
    calls = read_calls(full_report, context)
    assert len(calls) == 471
    assert calls[0].timestamp == datetime(2026, 10, 13, 12, 12, 41, 383000, tzinfo=UTC)
    assert [call.timestamp for call in calls] == sorted(call.timestamp for call in calls)


@pytest.mark.parametrize(
    ("category", "lane"),
    [
        ("filesystem", "file"),
        ("registry", "registry"),
        ("network", "network"),
        ("process", "process"),
        ("threading", "process"),
        ("system", "process"),
        ("hooking", "process"),
        (None, "process"),
    ],
)
def test_a_call_belongs_to_the_semantic_lane_of_its_category(
    category: str | None, lane: str, context: IngestContext
) -> None:
    raw = call("X") if category is None else call("X", category=category)
    if category is None:
        del raw["category"]
    [read] = read_calls(report_with(raw), context)
    assert call_lane(read) == lane


# --- ordering ------------------------------------------------------------------------------


def test_events_of_different_processes_interleave_by_timestamp_then_call_id(
    context: IngestContext,
) -> None:
    report = report_of(
        process(1, [call("Late", timestamp="2026-10-13 10:12:43,000", id=0)]),
        process(
            2,
            [
                call("SecondOfTwo", timestamp="2026-10-13 10:12:42,000", id=5),
                call("FirstOfTwo", timestamp="2026-10-13 10:12:42,000", id=4),
            ],
        ),
    )
    order = [event["api"]["name"] for event in normalise(report, context)]
    assert order == ["FirstOfTwo", "SecondOfTwo", "Late"]


def test_a_tie_on_timestamp_and_call_id_keeps_report_order(context: IngestContext) -> None:
    report = report_of(process(1, [call("InFirst")]), process(2, [call("InSecond")]))
    assert [e["api"]["name"] for e in normalise(report, context)] == ["InFirst", "InSecond"]


# --- derivation rules ----------------------------------------------------------------------

DERIVING_CALLS = [
    "NtCreateUserProcess",
    "CreateProcessInternalW",
    "NtTerminateProcess",
    "NtWriteFile",
    "NtCreateFile",
    "NtDeleteFile",
    "MoveFileWithProgressW",
    "RegCreateKeyExA",
    "RegCreateKeyExW",
    "RegSetValueExA",
    "RegSetValueExW",
    "NtSetValueKey",
    "RegDeleteValueA",
    "RegDeleteValueW",
    "RegDeleteKeyW",
    "NtDeleteKey",
    "connect",
    "InternetOpenUrlW",
    "getaddrinfo",
    "DnsQuery_W",
    "NtWriteVirtualMemory",
    "NtCreateThreadEx",
    "CreateRemoteThread",
    "NtQueueApcThread",
    "NtMapViewOfSection",
]


@pytest.mark.parametrize("api", DERIVING_CALLS)
def test_a_deriving_call_without_arguments_keeps_only_its_api_event(
    api: str, context: IngestContext
) -> None:
    assert actions(normalise(report_with(call(api)), context)) == ["api-call"]


@pytest.mark.parametrize("arguments", ["not a list", [None, 5, "x"], [{"name": 3}], None])
def test_malformed_arguments_do_not_raise(arguments: Any, context: IngestContext) -> None:
    broken = call("NtWriteFile")
    broken["arguments"] = arguments
    assert actions(normalise(report_with(broken), context)) == ["api-call"]


@pytest.mark.parametrize(
    ("missing", "expected"),
    [
        ("timestamp", ["api-call", "file-written"]),
        ("arguments", ["api-call"]),
        ("status", ["api-call"]),
        ("id", ["api-call", "file-written"]),
        ("return", ["api-call", "file-written"]),
        ("api", []),
    ],
)
def test_a_call_missing_a_field_keeps_what_it_still_can_say(
    missing: str, expected: list[str], context: IngestContext
) -> None:
    broken = call("NtWriteFile", {"HandleName": "C:\\a.txt"})
    del broken[missing]
    assert actions(normalise(report_with(broken), context)) == expected


def test_a_call_without_a_timestamp_falls_back_to_the_analysis_start(
    context: IngestContext,
) -> None:
    broken = call("NtClose", timestamp="garbage")
    [event] = normalise(report_with(broken), context)
    assert event["@timestamp"] == "2026-10-13T12:12:18.000Z"


def test_the_fallback_time_is_already_utc_and_is_not_shifted(
    full_report: dict[str, Any], context: IngestContext
) -> None:
    report = copy.deepcopy(full_report)
    report["behavior"]["processes"][0]["calls"][0]["timestamp"] = "garbage"
    moments = {event["@timestamp"] for event in normalise(report, context)}
    assert "2026-10-13T12:12:18.000Z" in moments


def test_junk_entries_in_the_process_and_call_lists_are_skipped(context: IngestContext) -> None:
    report = {
        "behavior": {
            "processes": [
                "junk",
                {"process_id": "x", "calls": [call("A")]},
                process(1, ["junk", None, call("Kept")]),
                process(2, "not a list"),  # type: ignore[arg-type]
            ]
        }
    }
    assert [e["api"]["name"] for e in normalise(report, context)] == ["Kept"]


def test_calls_not_in_the_table_produce_only_the_api_event(context: IngestContext) -> None:
    report = report_with(
        call("NtClose", {"Handle": "0x10"}),
        call("EventUnregister", id=1),
        call("LdrGetDllHandle", {"FileName": "kernel32.dll"}, id=2),
    )
    events = normalise(report, context)
    assert actions(events) == ["api-call"] * 3
    assert all("related" not in event for event in events)


def test_unknown_categories_map_to_the_host_category(context: IngestContext) -> None:
    [event] = normalise(report_with(call("Odd", category="whatever")), context)
    assert event["event"]["category"] == ["host"]


@pytest.mark.parametrize(
    ("category", "ecs_category"),
    [
        ("filesystem", "file"),
        ("registry", "registry"),
        ("network", "network"),
        ("process", "process"),
    ],
)
def test_api_category_maps_to_the_ecs_category(
    category: str, ecs_category: str, context: IngestContext
) -> None:
    [event] = normalise(report_with(call("X", category=category)), context)
    assert event["event"]["category"] == [ecs_category]


def test_a_failed_state_changing_call_derives_nothing(context: IngestContext) -> None:
    report = report_with(call("NtWriteFile", {"HandleName": "C:\\a.txt"}, status=False))
    assert actions(normalise(report, context)) == ["api-call"]


@pytest.mark.parametrize(
    "handle_name", ["\\Device\\ConDrv", "\\Device\\NamedPipe\\x", "\\\\.\\pipe\\y", ""]
)
def test_writes_to_devices_and_pipes_are_not_file_writes(
    handle_name: str, context: IngestContext
) -> None:
    report = report_with(call("NtWriteFile", {"HandleName": handle_name}))
    assert actions(normalise(report, context)) == ["api-call"]


@pytest.mark.parametrize("path", ["C:\\a\\b.txt", "\\??\\C:\\a\\b.txt", "\\\\server\\share\\b.txt"])
def test_writes_to_filesystem_paths_are_file_writes(path: str, context: IngestContext) -> None:
    event = only_derived(report_with(call("NtWriteFile", {"HandleName": path})), context)
    assert event["file"]["path"] == path


def test_opening_an_existing_file_is_not_a_creation(context: IngestContext) -> None:
    arguments = {"FileName": "C:\\a.txt", "ExistedBefore": "yes"}
    assert actions(normalise(report_with(call("NtCreateFile", arguments)), context)) == ["api-call"]


def test_file_deleted(context: IngestContext) -> None:
    event = only_derived(report_with(call("NtDeleteFile", {"FileName": "C:\\a.txt"})), context)
    assert event["event"]["action"] == "file-deleted"
    assert event["event"]["type"] == ["deletion"]
    assert event["file"]["path"] == "C:\\a.txt"


def test_file_moved_carries_both_paths(context: IngestContext) -> None:
    arguments = {"ExistingFileName": "C:\\a.txt", "NewFileName": "C:\\b.txt"}
    event = only_derived(report_with(call("MoveFileWithProgressW", arguments)), context)
    assert event["event"]["action"] == "file-moved"
    assert (event["file"]["path"], event["file"]["target_path"]) == ("C:\\a.txt", "C:\\b.txt")


def test_process_created_by_either_call_alone(context: IngestContext) -> None:
    for api in ("NtCreateUserProcess", "CreateProcessInternalW"):
        arguments = {"ProcessId": "200", "CommandLine": "x.exe /y", "ImagePathName": "C:\\x.exe"}
        event = only_derived(report_with(call(api, arguments)), context)
        assert event["event"]["action"] == "process-created"
        assert event["process"]["pid"] == 200
        assert event["process"]["command_line"] == "x.exe /y"
        assert event["process"]["parent"] == {
            "pid": 100,
            "name": "sample.exe",
            "executable": "C:\\Temp\\sample.exe",
            "command_line": "sample.exe",
        }


def test_the_earliest_creating_call_wins_even_if_listed_later(context: IngestContext) -> None:
    early = call(
        "NtCreateUserProcess",
        {"ProcessId": "200", "CommandLine": "early"},
        id=9,
        timestamp="2026-10-13 10:12:41,100",
    )
    late = call(
        "CreateProcessInternalW",
        {"ProcessId": "200", "CommandLine": "late"},
        id=1,
        timestamp="2026-10-13 10:12:41,900",
    )
    event = only_derived(report_with(late, early), context)
    assert event["process"]["command_line"] == "early"


def test_children_are_deduplicated_by_pid_not_by_parent_call(context: IngestContext) -> None:
    report = report_of(
        process(100, [call("NtCreateUserProcess", {"ProcessId": "300"}, id=1)]),
        process(101, [call("NtCreateUserProcess", {"ProcessId": "301"}, id=1)]),
    )
    pids = [e["process"]["pid"] for e in derived_of(normalise(report, context))]
    assert pids == [300, 301]


@pytest.mark.parametrize("child_pid", ["0", "", "x", "-1"])
def test_process_created_needs_a_usable_child_pid(child_pid: str, context: IngestContext) -> None:
    report = report_with(call("NtCreateUserProcess", {"ProcessId": child_pid}))
    assert actions(normalise(report, context)) == ["api-call"]


def test_a_child_that_has_its_own_record_lends_its_executable_and_start(
    context: IngestContext,
) -> None:
    report = report_of(
        process(
            100, [call("NtCreateUserProcess", {"ProcessId": "200", "CommandLine": "child.exe z"})]
        ),
        process(200, [], name="child.exe", parent_id=100),
    )
    event = only_derived(report, context)["process"]
    assert event["executable"] == "C:\\Temp\\child.exe"
    assert event["name"] == "child.exe"
    assert event["start"] == "2026-10-13T10:12:41.000Z"


@pytest.mark.parametrize(
    ("handle", "terminates_itself"),
    [
        ("0xffffffff", True),
        ("0xffffffffffffffff", True),
        ("0x00000000", False),
        ("0x2c4", False),
        ("", False),
    ],
)
def test_only_a_process_ending_itself_is_process_terminated(
    handle: str, terminates_itself: bool, context: IngestContext
) -> None:
    report = report_with(call("NtTerminateProcess", {"ProcessHandle": handle}))
    derived = derived_of(normalise(report, context))
    assert [e["event"]["action"] for e in derived] == (
        ["process-terminated"] if terminates_itself else []
    )


def created_child(parent: dict[str, Any], context: IngestContext) -> Event:
    return only_derived(report_of(parent), context)


def creating_call(child_pid: int = 200, **fields: Any) -> dict[str, Any]:
    return call("NtCreateUserProcess", {"ProcessId": str(child_pid)}, **fields)


def test_a_child_has_its_parents_path_and_command_line(context: IngestContext) -> None:
    parent = process(
        100, [creating_call()], name="parent.exe", command_line='"C:\\Temp\\parent.exe" --go'
    )
    assert created_child(parent, context)["process"]["parent"] == {
        "pid": 100,
        "name": "parent.exe",
        "executable": "C:\\Temp\\parent.exe",
        "command_line": '"C:\\Temp\\parent.exe" --go',
    }


def test_a_parent_the_report_does_not_describe_leaves_those_fields_out(
    context: IngestContext,
) -> None:
    parent = process(100, [creating_call()], name="parent.exe")
    del parent["module_path"], parent["environ"]
    assert created_child(parent, context)["process"]["parent"] == {"pid": 100, "name": "parent.exe"}


def test_a_reused_pid_gives_each_child_the_parent_that_created_it(context: IngestContext) -> None:
    first = process(100, [creating_call(200, id=1)], name="first.exe", command_line="first.exe")
    second = first_seen_at(
        process(
            100,
            [creating_call(300, id=2, timestamp="2026-10-13 10:13:00,000")],
            name="second.exe",
            command_line="second.exe",
        ),
        "2026-10-13 10:12:59,000",
    )
    children = derived_of(normalise(report_of(first, second), context))
    assert [e["process"]["parent"]["command_line"] for e in children] == [
        "first.exe",
        "second.exe",
    ]


INJECTION_INTO_4242 = call("NtWriteVirtualMemory", {"ProcessHandle": "0x2c4", "ProcessId": "4242"})


def test_an_injection_event_names_the_process_it_acts_on(context: IngestContext) -> None:
    victim = process(4242, [], name="victim.exe", command_line="victim.exe -k net")
    event = only_derived(report_of(process(100, [INJECTION_INTO_4242]), victim), context)
    assert event["tartarus"]["inject"] == {
        "target_pid": 4242,
        "target_name": "victim.exe",
        "target_executable": "C:\\Temp\\victim.exe",
        "target_command_line": "victim.exe -k net",
    }


def test_an_injection_target_the_report_does_not_know_stays_a_bare_pid(
    context: IngestContext,
) -> None:
    event = only_derived(report_of(process(100, [INJECTION_INTO_4242])), context)
    assert event["tartarus"]["inject"] == {"target_pid": 4242}


def test_an_injection_target_lacking_a_command_line_leaves_only_that_field_out(
    context: IngestContext,
) -> None:
    victim = process(4242, [], name="victim.exe")
    del victim["environ"]
    event = only_derived(report_of(process(100, [INJECTION_INTO_4242]), victim), context)
    assert set(event["tartarus"]["inject"]) == {"target_pid", "target_name", "target_executable"}


def test_a_reused_pid_resolves_to_the_process_current_at_the_injection(
    context: IngestContext,
) -> None:
    early = call("NtWriteVirtualMemory", {"ProcessId": "4242"}, id=1)
    late = call(
        "NtWriteVirtualMemory", {"ProcessId": "4242"}, id=2, timestamp="2026-10-13 10:13:30,000"
    )
    old_victim = first_seen_at(process(4242, [], name="old.exe"), "2026-10-13 10:12:30,000")
    new_victim = first_seen_at(process(4242, [], name="new.exe"), "2026-10-13 10:13:00,000")
    injections = derived_of(
        normalise(report_of(process(100, [early, late]), old_victim, new_victim), context)
    )
    assert [e["tartarus"]["inject"]["target_name"] for e in injections] == ["old.exe", "new.exe"]


def test_an_injection_before_any_holder_of_the_pid_started_names_the_first_one(
    context: IngestContext,
) -> None:
    victim = first_seen_at(process(4242, [], name="victim.exe"), "2026-10-13 10:13:00,000")
    event = only_derived(report_of(process(100, [INJECTION_INTO_4242]), victim), context)
    assert event["tartarus"]["inject"]["target_name"] == "victim.exe"


def test_registry_key_created_only_when_the_key_is_new(context: IngestContext) -> None:
    new = {"FullName": "HKEY_CURRENT_USER\\Software\\X", "Disposition": "1"}
    existing = {"FullName": "HKEY_CURRENT_USER\\Software\\X", "Disposition": "2"}
    assert only_derived(report_with(call("RegCreateKeyExW", new)), context)["registry"]["key"] == (
        "Software\\X"
    )
    assert actions(normalise(report_with(call("RegCreateKeyExW", existing)), context)) == [
        "api-call"
    ]


@pytest.mark.parametrize("api", ["RegSetValueExA", "RegSetValueExW", "NtSetValueKey"])
def test_registry_value_set(api: str, context: IngestContext) -> None:
    arguments = {"FullName": "HKEY_LOCAL_MACHINE\\SOFTWARE\\Run\\Updater", "ValueName": "Updater"}
    event = only_derived(report_with(call(api, arguments)), context)
    assert event["event"]["action"] == "reg-value-set"
    assert event["registry"]["hive"] == "HKLM"
    assert event["registry"]["value"] == "Updater"


@pytest.mark.parametrize(
    ("api", "action"),
    [("RegDeleteValueW", "reg-value-deleted"), ("RegDeleteKeyW", "reg-key-deleted")],
)
def test_registry_deletions(api: str, action: str, context: IngestContext) -> None:
    arguments = {"FullName": "HKEY_CURRENT_USER\\Software\\X\\V", "ValueName": "V"}
    event = only_derived(report_with(call(api, arguments)), context)
    assert event["event"]["action"] == action
    assert event["event"]["type"] == ["deletion"]


def test_connect_is_a_network_connection(context: IngestContext) -> None:
    event = only_derived(report_with(call("connect", {"ip": "10.0.0.5", "port": "443"})), context)
    assert event["event"]["action"] == "network-connection"
    assert event["destination"] == {"ip": "10.0.0.5", "port": 443}
    assert event["tartarus"]["lane"] == "network"


def test_a_failed_connect_is_still_an_attempt(context: IngestContext) -> None:
    report = report_with(call("connect", {"ip": "10.0.0.5", "port": "443"}, status=False))
    assert actions(normalise(report, context)) == ["api-call", "network-connection"]


def test_internet_open_url_is_an_http_request(context: IngestContext) -> None:
    event = only_derived(
        report_with(call("InternetOpenUrlW", {"URL": "http://evil.example/a.exe"})), context
    )
    assert event["event"]["action"] == "http-request"
    assert event["url"] == {"full": "http://evil.example/a.exe"}


def test_dnsquery_is_a_dns_query(context: IngestContext) -> None:
    event = only_derived(report_with(call("DnsQuery_W", {"Name": "evil.example"})), context)
    assert event["dns"]["question"]["name"] == "evil.example"


def test_injection_into_another_process_is_derived(context: IngestContext) -> None:
    arguments = {"ProcessHandle": "0x2c4", "ProcessId": "4242", "BaseAddress": "0x1000"}
    event = only_derived(report_with(call("NtWriteVirtualMemory", arguments)), context)
    assert event["event"]["action"] == "inject-write-memory"
    assert event["tartarus"]["lane"] == "process"
    assert "4242" in event["tartarus"]["summary"]
    assert event["process"]["pid"] == 100
    assert event["tartarus"]["inject"] == {"target_pid": 4242}


@pytest.mark.parametrize(
    ("api", "action"),
    [
        ("NtWriteVirtualMemory", "inject-write-memory"),
        ("NtCreateThreadEx", "inject-thread"),
        ("CreateRemoteThread", "inject-thread"),
        ("NtMapViewOfSection", "inject-map-section"),
    ],
)
def test_injection_calls_by_handle_alone(api: str, action: str, context: IngestContext) -> None:
    event = only_derived(report_with(call(api, {"ProcessHandle": "0x2c4"})), context)
    assert event["event"]["action"] == action
    assert "inject" not in event["tartarus"]


@pytest.mark.parametrize("api", ["NtWriteVirtualMemory", "NtCreateThreadEx", "NtMapViewOfSection"])
@pytest.mark.parametrize("handle", ["0xffffffff", "0x0"])
def test_operations_on_the_own_process_are_not_injection(
    api: str, handle: str, context: IngestContext
) -> None:
    assert actions(normalise(report_with(call(api, {"ProcessHandle": handle})), context)) == [
        "api-call"
    ]


def test_a_process_id_naming_the_own_process_is_not_injection(context: IngestContext) -> None:
    arguments = {"ProcessHandle": "0x2c4", "ProcessId": "100"}
    assert actions(normalise(report_with(call("NtWriteVirtualMemory", arguments)), context)) == [
        "api-call"
    ]


def test_apc_injection_needs_a_foreign_process_id(context: IngestContext) -> None:
    foreign = only_derived(report_with(call("NtQueueApcThread", {"ProcessId": "4242"})), context)
    assert foreign["event"]["action"] == "inject-apc"
    assert foreign["tartarus"]["inject"] == {"target_pid": 4242}
    own = report_with(call("NtQueueApcThread", {"ProcessId": "100"}))
    assert actions(normalise(own, context)) == ["api-call"]


# --- identity -------------------------------------------------------------------------------


def second_process_ids(first_process_calls: int, context: IngestContext) -> list[str]:
    report = report_of(
        process(1, [call("A") for _ in range(first_process_calls)]),
        process(2, [call("B0"), call("B1")]),
    )
    return [e["event"]["id"] for e in normalise(report, context) if e["process"]["pid"] == 2]


def test_a_call_is_identified_by_its_process_and_its_place_in_that_process(
    context: IngestContext,
) -> None:
    assert second_process_ids(3, context) == second_process_ids(1, context)


def test_the_same_place_in_two_processes_is_two_events(context: IngestContext) -> None:
    report = report_of(process(1, [call("A")]), process(2, [call("A")]))
    ids = [e["event"]["id"] for e in normalise(report, context)]
    assert len(set(ids)) == len(ids) == 2
